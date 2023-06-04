#!/usr/bin/env python
'''
Zip the contents of a Python package for deploy to AWS Lambda.

Optionally, upload the zip to S3.

Optionally, invoke AWS Lambda API to update a specified function.
'''
import argparse
import base64
import boto3
import getpass
import git
import hashlib
import json
import logging
import os
import packaging.version
from pathlib import Path
import pdb
import re
import socket
import subprocess
from tempfile import TemporaryDirectory
import time
import toml
import urllib
import yaml
from zipfile import ZipFile

from lambda_zip.aws_lambda_layer import AwsLambdaLayer

local_deps_already_installed = set()
logger = logging.getLogger(__name__)
# Exclude these directories by default, because AWS Lambda environment provides them
zip_omit = set([
    '^boto3',
    '^botocore',
    '^dateutil',
    '^pip',
    '^python_dateutil',
    '^jmespath',
    '^s3transfer',
    '^setuptools',
    '^six',
    '^urllib3',
])

class NewAwsLambdaLayerZip:
    '''
    Use this class to create a new layer ZIP file.

    It may then be uploaded to S3 using .upload_to_s3() and published as a layer version using
    .publish_layer_version().
    '''

    '''
    boto3_lambda_client can be supplied by caller.
    If not, we invoke boto3.client('lambda') to get one the first time we need it.
    '''
    boto3_lambda_client = None
    '''
    boto3_s3_client can be supplied by caller.
    If not, we invoke boto3.client('s3') to get one the first time we need it.
    '''
    boto3_s3_client = None

    layer_metadata_publish_fields = [
        'branch',
        'commit',
        'describe',
        'dirty',
        'sha256',
        'untracked',
    ]

    deps_builtin_to_runtime = set([
        'boto3',
        'botocore',
        'dateutil',
        'pip',
        'python_dateutil',
        'jmespath',
        's3transfer',
        'setuptools',
        'six',
        'urllib3',
    ])

    def __init__(
        self,
        name:str,
        src_dir:Path,
        tmp_dir_for_layer:Path,
        omit_pathnames:set = None,
        omit_path_patterns:set = None,
        omit_projects:set = None,
        s3_url:urllib.parse.ParseResult = None,
        zip_filename:Path = None,
    ):
        '''
        Note: If the given s3_url ends with '/', the layer name followed by '.zip' will be added to it.
        For example, s3://jeff-bucket/artifacts/ becomes s3://jeff-bucket/artifacts/my_layer.zip
        '''
        # copy arguments to object
        self.name = name
        self.src_dir = src_dir
        self.tmp_dir_for_layer = tmp_dir_for_layer
        # args with defaults
        self.omit_pathnames = set() if omit_pathnames == None else omit_pathnames
        self.omit_path_patterns = set() if omit_path_patterns == None else omit_path_patterns
        self.omit_projects = set() if omit_projects == None else omit_projects
        if zip_filename == None:
            self.zip_filename = Path(self.src_dir.parent, self.name + '_layer.zip')
        else:
            self.zip_filename = zip_filename
        # args with complexity
        self.s3_url_set(s3_url)

        # install src_dir project(s) & dependencies into tmp_dir_for_layer + '/python'
        self.tmp_python_path = Path(self.tmp_dir_for_layer, 'python')
        self.tmp_python_path.mkdir(exist_ok=True, mode=0o755, parents=True)
        install_to_dir(
            dst_dir = self.tmp_python_path,
            local_dep_dir = self.src_dir
        )

        # prepend 'python/' onto the beginning of everything in self.omit_pathnames
        self.omit_pathnames = set([ 'python/' + pathn for pathn in self.omit_pathnames ])
        # organize file path/name patterns which will be omitted from the ZIP file
        self.omit_project_patterns = set()
        for project_name in self.omit_projects:
            project_pattern = '^python/' + re.sub(r'[-_]+', '[-_]+', project_name)
            self.omit_project_patterns.add(project_pattern)
        self.omit_patterns = self.omit_project_patterns | self.omit_path_patterns
        for builtin_dep in self.deps_builtin_to_runtime:
            self.omit_patterns.add('^python/' + builtin_dep)

        zf = create_zip_file(
            tmp_dir = self.tmp_dir_for_layer,
            zip_filename = self.zip_filename,
            zip_omit_exact_names = self.omit_pathnames,
            zip_omit_patterns = self.omit_patterns,
        )
        self.zip_namelist = zf.namelist()

        # Our hash digest is not a digest of the ZIP file itself.  We need a repeatable hash that solves
        # several problems:
        #   1) `pip install --target <dir>` causes that <dir> name to end up in the `.pyc` files
        #   2) `pip install --target <dir>` causes a unix timestamp encoded in `.pyc` header to be the current time
        #   3) `.zip` files themselves contain timestamps which would be the current build time
        #   4) want to add a file `lambda_zip_metadata.yml` later to include more build metadata
        hasher = hashlib.sha256()
        for zipped_filename in sorted(self.zip_namelist):
            if zipped_filename.endswith('.pyc') or zipped_filename == 'lambda_zip_metadata.yml':
                continue
            hasher.update(bytes(zipped_filename, 'utf-8')) # include the filename itself in hashed content
            with zf.open(zipped_filename) as zf_bin:
                while True:
                    buffer = zf_bin.read(1048576)
                    if not buffer:
                        break
                    hasher.update(buffer)
        self.sha256_b64digest = base64.b64encode(hasher.digest()).decode('utf-8')
        self.sha256_digest = hasher.digest()
        self.sha256_hexdigest = hasher.hexdigest()

        zf.close()

        # get metadata which may be used later for S3 attributes & layer description
        self.update_metadata()

    def get_boto3_s3_client(self):
        if self.boto3_s3_client == None:
            self.boto3_s3_client = boto3.client('s3')
        return self.boto3_s3_client

    def get_boto3_lambda_client(self):
        if self.boto3_lambda_client == None:
            self.boto3_lambda_client = boto3.client('lambda')
        return self.boto3_lambda_client

    def encode_metadata_for_description(self):
        '''
        We put metadata into the layer description so we can query it efficiently from the AWS API.  This
        is how we de-duplicate; avoiding publishing useless, repeated copies of a layer over and over in
        CI/CD pipeline if there have been no changes.
        '''
        if getattr(self, 'metadata', None) == None:
            self.update_metadata()
        retstr = json.dumps(self.metadata, indent=None, separators=(',', ':'), sort_keys=True)
        return retstr

    def publish(self):
        '''
        Wrapper around boto3 publish_layer_version.  Encodes metadata in description.
        '''
        encoded_metadata = self.encode_metadata_for_description()
        client = self.get_boto3_lambda_client()
        pub_response = client.publish_layer_version(
            LayerName = self.name,
            Description = encoded_metadata,
            Content = {
                'S3Bucket': self.s3_bucket,
                'S3Key': self.s3_key,
                # TODO: Add 'S3ObjectVersion' here
            },
            # CompatibleRuntimes omitted
            # CompatibleArchitectures omitted
        )
        self.layer_version_obj = pub_response
        self.version = pub_response['Version']
        self.version_arn = pub_response['LayerVersionArn']
        logger.info(f"published new layer version {self.version} SHA-256 {self.metadata['sha256b64']}")
        return self.layer_version_obj

    def s3_url_set(self, s3_url):
        if s3_url == None:
            return
        if not isinstance(s3_url, urllib.parse.ParseResult):
            raise TypeError(f"s3_url must be an urllib.parse.ParseResult; instead it's a: {type(s3_url)}")
        if s3_url.scheme != 's3':
            raise ValueError(f"s3_url.scheme must be 's3', e.g. URL starts with s3://.  Instead, got: {s3_url}")
        if s3_url.geturl().endswith('/'):
            # If the given s3_url ends in '/' add self.name + '.zip' onto the end of the URL.
            self.s3_url = urllib.parse.urlparse(s3_url.geturl() + self.name + '.zip')
        else:
            self.s3_url = s3_url
        self.s3_bucket = self.s3_url.netloc
        self.s3_key = self.s3_url.path

    def update_metadata(self):
        self.metadata = dict()
        try:
            self.metadata.update(git_get_metadata(src_dir = self.src_dir))
        except:
            logger.error(f'Cannot get git metadata from {self.src_dir}')
        self.metadata.update(get_builder_metadata())
        self.metadata['sha256b64'] = self.sha256_b64digest

    def upload_to_s3(
        self,
    ):
        if self.s3_url == None:
            raise KeyError(f's3_url is missing from this object.  Cannot upload.')

        metadata_stringified = {}
        for k, v in self.metadata.items():
            metadata_stringified[k] = str(v)
        logger.info(f'S3 uploading {str(self.zip_filename)} to s3://{self.s3_bucket}/{self.s3_key}')
        # TODO change to using put_object() so we get a response object with then new S3 object version.
        # https://boto3.amazonaws.com/v1/documentation/api/1.9.42/reference/services/s3.html#S3.Bucket.put_object
        result = self.get_boto3_s3_client().upload_file(
            Filename = str(self.zip_filename),
            Bucket = self.s3_bucket,
            Key = self.s3_key,
            ExtraArgs = {'Metadata': metadata_stringified},
        )
        return result

class NewAwsLambdaZip:
    '''
    Use this class to create a new lambda ZIP file.
    '''
    deps_builtin_to_runtime = set([
        'boto3',
        'botocore',
        'dateutil',
        'pip',
        'python_dateutil',
        'jmespath',
        's3transfer',
        'setuptools',
        'six',
        'urllib3',
    ])

    def __init__(
        self,
        name:str,
        src_dir:Path,
        tmp_dir_for_lambda:Path,
        install_dependencies:bool = True,
        omit_path_patterns:set = None,
        omit_projects:set = None,
        zip_filename:Path = None,
    ):
        # copy arguments
        self.name = name
        self.src_dir = src_dir
        self.tmp_dir_for_lambda = tmp_dir_for_lambda
        # args with defaults
        self.install_dependencies = install_dependencies
        self.omit_path_patterns = set() if omit_path_patterns == None else omit_path_patterns
        self.omit_projects = set() if omit_projects == None else omit_projects
        if zip_filename == None:
            self.zip_filename = Path(self.src_dir.parent, self.src_dir.name + '.zip')
        else:
            self.zip_filename = zip_filename

        install_to_dir(
            dst_dir = self.tmp_dir_for_lambda,
            install_dependencies = self.install_dependencies,
            local_dep_dir = self.src_dir
        )

        # organize file path/name patterns which will be omitted from the ZIP file
        self.omit_project_patterns = set()
        for project_name in self.omit_projects:
            project_pattern = '^' + re.sub(r'[-_]+', '[-_]+', project_name)
            self.omit_project_patterns.add(project_pattern)
        self.omit_patterns = self.omit_project_patterns | self.omit_path_patterns
        for builtin_dep in self.deps_builtin_to_runtime:
            self.omit_patterns.add('^' + builtin_dep)

        zf = create_zip_file(
            tmp_dir = self.tmp_dir_for_lambda,
            zip_filename = self.zip_filename,
            zip_omit_patterns = self.omit_patterns,
        )
        self.zip_namelist = zf.namelist()

def aws_lambda_update(
    function_name:str,
    s3_url:str,
    layer_arn:str=None,
):
    '''
    Wrapper around boto3.client('lambda').update_function_code()
    See https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/lambda.html#Lambda.Client.update_function_code

    If layer_arn != None, boto3.client('lambda').update_function_configuration() will be invoked.
    '''
    logger.info(F'Updating lambda function {function_name}')
    s3_url = urllib.parse.urlparse(s3_url)
    s3_bucket = s3_url.hostname
    s3_filename = s3_url.path.lstrip('/')
    lam = boto3.client('lambda')
    upd_func_response = lam.update_function_code(
        FunctionName=function_name,
        S3Bucket=s3_bucket,
        S3Key=s3_filename,
    )
    if layer_arn != None:
        upd_config_response = lam.update_function_configuration(
            Function_name=function_name,
            Layers = [
                layer_arn,
            ],
        )

def create_zip_file(
    tmp_dir:Path,
    zip_filename:Path,
    zip_omit_exact_names:set = None,
    zip_omit_patterns:set = None,
):
    '''
    Create the lambda .zip file using tmp_dir as the source, and excluding any file pathnames
    matching the zip_omit_patterns.

    Path names in the output zip file will be like e.g.: acme_dep_name/__init__.py

    NOTE: We chdir(tmp_dir) because the Python ZipFile module doesn't allow us to specify the
    path of files added to the archive.  If we didn't, the zip file would contain garbage paths
    like /var/tmp/hlaghlag/acme_dep_name/__init__.py
    '''
    logger.info(F'Creating ZIP file {zip_filename} from tmp_dir {str(tmp_dir)}')
    os.chdir(tmp_dir)
    omitted_file_count = 0
    zipped_file_count = 0

    zip_omit_exact_names = set() if zip_omit_exact_names == None else zip_omit_exact_names
    zip_omit_patterns = set() if zip_omit_patterns == None else zip_omit_patterns

    zip_omit_compiled_regexes = set()
    for pattern in zip_omit_patterns:
        compiled = re.compile(pattern)
        zip_omit_compiled_regexes.add(compiled)
    
    zf = ZipFile(zip_filename, 'w')
    for relative_path, subdirs, files in os.walk(Path()):
        for file_name in files:
            file_relative_path = Path(relative_path, file_name)
            omitted = 0
            for exact_name in zip_omit_exact_names:
                if exact_name == str(file_relative_path):
                    logger.debug(f'Omitting {file_relative_path} matching omit-exact-name')
                    omitted_file_count += 1
                    omitted = 1
                    break
            if omitted:
                continue
            for regex in zip_omit_compiled_regexes:
                if regex.search(str(file_relative_path)):
                    logger.debug(F'Omitting {file_relative_path} matching omit-regex {{regex}}')
                    omitted_file_count += 1
                    break
            else:
                # if no regex match happened during the for loop, add file to the zipfile
                zf.write(str(file_relative_path))
                zipped_file_count += 1
    logger.info(F'Created ZIP containing {zipped_file_count} files.  Omitted {omitted_file_count} regex matches.')
    return zf

def emit_metadata_yaml(dst_yaml_path:Path, metadata:dict):
    'Write given metadata dict to dst_yaml_file'
    logger.debug(F'Writing metadata to YAML file {str(dst_yaml_path)}')
    with open(dst_yaml_path, 'w') as yaml_file:
        yaml.safe_dump(metadata, yaml_file, indent=4)

def get_builder_metadata():
    retdict = {}
    retdict['host'] = socket.gethostname()
    retdict['timestamp'] = int(time.time())
    retdict['user'] = getpass.getuser()
    return retdict

def get_pip_version(pip_command:str='pip'):
    args = pip_command + ' --version'
    logger.debug(F'Invoking pip --version command: {args}')
    subp_result = subprocess.run(
        args = args,
        capture_output = True,
        check = True,
        shell = True,
        stdin = subprocess.DEVNULL,
    )
    subp_stdout = subp_result.stdout.decode('utf-8')
    if rem := re.match(r'^pip (?P<version>\S+) from', subp_stdout):
        retstr = rem.group('version')
        logger.debug(f'Detected pip version {retstr}')
        return retstr
    raise ValueError(f'Unable to match pip version in output from {args}: {subp_stdout}')

def git_get_metadata(src_dir:Path):
    '''
    Retrieve a selection of metadata from git repo at src_dir.
    '''
    retdict = {}
    repo = git.Repo(src_dir, search_parent_directories=True)
    try:
        retdict['branch'] = repo.active_branch.name
    except:
        pass
    retdict['commit'] = repo.head.commit.hexsha
    try:
        retdict['describe'] = repo.git.describe(always=True, dirty=True)
    except:
        pass
    retdict['dirty'] = repo.is_dirty()
    retdict['untracked'] = len(repo.untracked_files)
    return retdict

def install_to_dir(
    dst_dir:Path,
    local_dep_dir:Path,
    install_dependencies:bool = True,
):
    '''
    Call this function on the python source directory of your lambda; the directory containing
    pyproject.toml.
    
    This function is used RECURSIVELY to resolve dependencies.  As those
    are installed, local_deps_already_installed and pip_deps_already_installed
    are populated, indicating which deps have already been satisfied.
    '''
    global local_deps_already_installed
    global zip_omit
    logger.info(F'Installing local_dep_dir {local_dep_dir} to {dst_dir}')
    toml_path = Path(local_dep_dir, 'pyproject.toml')
    try:
        toml_file = open(toml_path)
        toml_blob = toml_file.read()
        dep_data = toml.loads(toml_blob)
    except Exception as e:
        raise ValueError(F'Cannot open pyproject.toml in local_dependency directory {local_dep_dir}: {e}')
    if 'lambda_zip' in dep_data:
        for omit_regex in dep_data['lambda_zip'].get('zip_omit', []):
            zip_omit.add(omit_regex)
        if install_dependencies:
            sub_deps = set()
            for sub_dep in dep_data['lambda_zip'].get('local_dependency', []):
                sub_dep_path = Path(local_dep_dir, sub_dep).absolute()
                sub_deps.add(sub_dep_path)
            sub_deps_unresolved = sub_deps - local_deps_already_installed
            for sub_dep in sub_deps_unresolved:
                # RECURSION HERE
                install_to_dir(dst_dir=dst_dir, local_dep_dir=sub_dep)
                local_deps_already_installed.add(str(sub_dep))
    # install local_dep_dir
    invoke_pip_install(
        target_dir=dst_dir,
        packages=[str(local_dep_dir)],
        install_dependencies=install_dependencies,
    )
    local_deps_already_installed.add(str(local_dep_dir))

def invoke_pip_install(
    target_dir:Path,
    packages:list,
    install_dependencies:bool,
    dry_run:bool=False,
    pip_command:str='pip',
    report:bool=False,
) -> dict:
    '''
    Wrapper around `pip install --target <target_dir> <packages>`
    '''
    retdict = {}
    dry_run_option = ['--dry-run'] if dry_run else []
    no_deps_option = [] if install_dependencies else ['--no-deps']
    packages_str = ' '.join(packages)
    if report:
        report_path = Path(target_dir, 'lambda_zip_pip_report.json')
        report_option = ['--report', str(report_path)]
    else:
        report_option = []
    args = ' '.join([
        pip_command,
        'install',
        *dry_run_option,
        *no_deps_option,
        *report_option,
        '--target', str(target_dir),
        packages_str,
    ])
    logger.info(F'Invoking pip command: {args}')
    subp_result = subprocess.run(
        args = args,
        capture_output = True,
        check = True,
        shell = True,
        stdin = subprocess.DEVNULL,
    )
    retdict['subprocess_result'] = subp_result

    if report:
        with open(report_path) as report_fh:
            report_data = json.load(report_fh)
        report_path.unlink()
        retdict['pip_report_data'] = report_data

    return retdict

def s3_upload(
    s3_url:str,
    zip_filename:Path,
    metadata:dict=None,
):
    logger.info(f'S3 uploading {str(zip_filename)} to {s3_url}')
    s3_url = urllib.parse.urlparse(s3_url)
    s3_bucket = s3_url.hostname
    s3_filename = s3_url.path.lstrip('/')
    if metadata is None:
        metadata = {}
    else:
        # stringify metadata for AWS
        metadata = metadata.copy()
        for k, v in metadata.items():
            metadata[k] = str(v)
    s3 = boto3.client('s3')
    s3.upload_file(
        Filename=str(zip_filename),
        Bucket=s3_bucket,
        Key=s3_filename,
        ExtraArgs={'Metadata': metadata}
    )

def cli_entry_point():
    ap = argparse.ArgumentParser(argument_default=argparse.SUPPRESS)
    ap.add_argument('--aws-lambda-update', type=str, help='Specifies the AWS Lambda function name to update.  Requires --upload-s3-url.')
    #TODO: implement --extra-dir and --extra-file
    #ap.add_argument('--extra-dir', action='append', help='Extra directory(s) added to the root of your ZIP')
    #ap.add_argument('--extra-file', action='append', help='Extra file(s) added to the root of your ZIP')
    ap.add_argument('--git', default=True, dest='git', action='store_true', help='Include git metadata in ZIP and S3 object')
    ap.add_argument('--no-git', dest='git', action='store_false')
    ap.add_argument('--keep', default=False, action='store_true', help='Keep temporary directory for troubleshooting')
    ap.add_argument('--layer-name', type=str, help='Sets the layer name which will contain dependencies')
    ap.add_argument('--layer-s3-url', help='Upload layer to S3 URL, e.g. s3://jsw-lambda/ or s3://jsw-lambda/layername.zip')
    ap.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], help='Sets the logging level.  Must be one of CRITICAL, ERROR, WARNING, INFO, or DEBUG.  Default is INFO.')
    ap.add_argument('--omit', default=[], action='append', help='Regexes used to omit matching path/filenames from the ZIP file, e.g. --omit ^boto3')
    ap.add_argument('--src-dir', type=Path, default=Path('.'), help='Directory containing the lambda package source, e.g. python/example_lambda.  Default to current directory.')
    ap.add_argument('--tmp-dir', type=Path, help='Temporary directory used to install dependencies for zipping')
    ap.add_argument('--upload-s3-url', help='Upload to S3 URL, e.g. s3://jsw-lambda/example.zip')
    ap.add_argument('--zip', type=Path, default=None, help='Output ZIP filename')
    ap.add_argument('--debug', action='store_true', help='Break into pdb debugger right away.')
    args = vars(ap.parse_args())
    if 'debug' in args and args['debug']==True:
        pdb.set_trace()
    logging.basicConfig(
        level=args.get('log_level', 'INFO'),
        datefmt='%Y-%m-%dT%H:%M:%S',
        format='%(asctime)s.%(msecs)03d %(levelname)s %(filename)s %(lineno)d %(funcName)s %(message)s',
    )
    if 'log_level' in args:
        logger.setLevel(args['log_level'])

    args['src_dir'] = args['src_dir'].absolute()

    metadata = {}
    if args.get('git', False):
        metadata = git_get_metadata(src_dir=args['src_dir'])
    metadata.update(get_builder_metadata())

    if 'layer_name' in args or 'layer_s3_url' in args:
        pip_version = get_pip_version()
        pip_symver = packaging.version.parse(pip_version)
        required_symver = packaging.version.parse('22.2')
        if pip_symver < required_symver:
            raise ValueError('pip version >= 22.2 is required for --layer-name / --layer-s3-url operation.')

    if 'aws_lambda_update' in args:
        if not 'upload_s3_url' in args:
            raise KeyError('You specified --aws-lambda-update which requires you use --upload-s3-url but no S3 URL was given.')

    for omit_pattern in args['omit']:
        zip_omit.add(omit_pattern)

    if 'tmp_dir' in args:
        try:
            os.mkdir(args['tmp_dir'])
            logger.info(F'Created specified tmp directory {args["tmp_dir"]}')
        except FileExistsError:
            logger.info(F'Using existing, specified tmp directory {args["tmp_dir"]}')
    else:
        tdir = TemporaryDirectory()
        args['tmp_dir'] = Path(tdir.name)
        logger.info(F'Created tmp directory {tdir}')

    lambda_tmp_dir = Path(args['tmp_dir'], 'lambda')
    lambda_zip = NewAwsLambdaZip(
        name = args['aws_lambda_update'],
        src_dir = args['src_dir'],
        tmp_dir_for_lambda = lambda_tmp_dir,
        install_dependencies = False if 'layer_name' in args else True,
        omit_path_patterns = zip_omit,
        zip_filename = args['zip'],
    )

    if 'layer_name' in args:
        layer_tmp_dir = Path(args['tmp_dir'], 'layer')
        layer_zip = NewAwsLambdaLayerZip(
            name = args['layer_name'],
            src_dir = args['src_dir'],
            omit_pathnames = lambda_zip.zip_namelist,
            s3_url = urllib.parse.urlparse(args['layer_s3_url']) if args['layer_s3_url'] else None,
            tmp_dir_for_layer = layer_tmp_dir,
        )
        # get existing layer version(s) and compare their SHA-256 to newly-created .ZIP
        layer = AwsLambdaLayer.get_lambda_layer(name=args['layer_name'])
        if duplicate := layer.get_highest_version_matching_sha256b64(layer_zip.sha256_b64digest):
            logger.info(f'DUPLICATE new layer .zip has same SHA-256 as already-existing version {duplicate.Version}')
            use_layer_version = duplicate
        else:
            layer_zip.upload_to_s3()
            use_layer_version = layer_zip.publish()

    if 'upload_s3_url' in args:
        s3_upload(
            metadata=metadata,
            s3_url=args['upload_s3_url'],
            zip_filename = lambda_zip.zip_filename,
        )

    if 'aws_lambda_update' in args:
        if 'layer_name' in args:
            aws_lambda_update(
                function_name=args['aws_lambda_update'],
                s3_url=args['upload_s3_url'],
                layer_arn=use_layer_version.LayerArn,
            )
        else:
            aws_lambda_update(
                function_name=args['aws_lambda_update'],
                s3_url=args['upload_s3_url'],
            )
