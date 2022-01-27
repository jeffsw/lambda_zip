#!/usr/bin/env python
'''
Zip the contents of a Python package for deploy to AWS Lambda.

Optionally, upload the zip to S3.

Optionally, invoke AWS Lambda API to update a specified function.
'''
import argparse
import boto3
import getpass
import git
import logging
import os
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

def aws_lambda_update(
    function_name:str,
    s3_url:str,
):
    '''
    Wrapper around boto3.client('lambda').update_function_code()
    See https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/lambda.html#Lambda.Client.update_function_code
    '''
    logger.info(F'Updating lambda function {function_name}')
    s3_url = urllib.parse.urlparse(s3_url)
    s3_bucket = s3_url.hostname
    s3_filename = s3_url.path.lstrip('/')
    lam = boto3.client('lambda')
    lam.update_function_code(
        FunctionName=function_name,
        S3Bucket=s3_bucket,
        S3Key=s3_filename,
    )

def create_zip_file(
    tmp_dir:Path,
    zip_filename:Path,
    zip_omit_patterns:set,
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
    
    zip_omit_compiled_regexes = set()
    for pattern in zip_omit_patterns:
        compiled = re.compile(pattern)
        zip_omit_compiled_regexes.add(compiled)
    
    zf = ZipFile(zip_filename, 'w')
    for relative_path, subdirs, files in os.walk(Path()):
        for file_name in files:
            file_relative_path = Path(relative_path, file_name)
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

def emit_metadata_yaml(dst_yaml_path:Path, metadata:dict):
    'Write given metadata dict to dst_yaml_file'
    logger.debug(F'Writing metadata to YAML file {str(dst_yaml_path)}')
    with open(dst_yaml_path, 'w') as yaml_file:
        yaml.safe_dump(metadata, yaml_file, indent=4)

def git_get_metadata(src_dir:Path, dst_yaml_path:Path=None):
    '''
    Retrieve a selection of metadata from git repo at src_dir.

    If dst_yaml_path is specified, the metadata will also be written to the given YAML file.
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
    retdict['detached'] = repo.head.is_detached
    retdict['dirty'] = repo.is_dirty()
    retdict['untracked'] = len(repo.untracked_files)
    return retdict

def install_to_dir(
    dst_dir:Path,
    local_dep_dir:Path,
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
    invoke_pip_install(target_dir=dst_dir, packages=[str(local_dep_dir)])
    local_deps_already_installed.add(str(local_dep_dir))

def invoke_pip_install(
    target_dir:Path,
    packages:list,
):
    '''
    Wrapper around `pip install --target <target_dir> <packages>`
    '''
    packages_str = ' '.join(packages)
    args = ' '.join(['pip', 'install', '--target', str(target_dir), packages_str])
    logger.info(F'Invoking pip command: {args}')
    result = subprocess.run(
        args = args,
        check = True,
        shell = True,
        stdin = subprocess.DEVNULL,
    )
    return result

def s3_upload(
    s3_url:str,
    zip_filename:Path,
    metadata:dict=None,
):
    logger.info(F'S3 uploading F{str(zip_filename)} to {s3_url}')
    s3_url = urllib.parse.urlparse(s3_url)
    s3_bucket = s3_url.hostname
    s3_filename = s3_url.path.lstrip('/')
    if metadata is None:
        metadata = {}
    s3 = boto3.client('s3')
    s3.upload_file(
        Filename=str(zip_filename),
        Bucket=s3_bucket,
        Key=s3_filename,
        ExtraArgs={'Metadata': metadata}
    )

def cli_entry_point():
    logging.basicConfig(level='INFO')
    ap = argparse.ArgumentParser(argument_default=argparse.SUPPRESS)
    ap.add_argument('--aws-lambda-update', type=str, help='Specifies the AWS Lambda function name to update.  Requires --upload-s3-url.')
    #TODO: implement --extra-dir and --extra-file
    #ap.add_argument('--extra-dir', action='append', help='Extra directory(s) added to the root of your ZIP')
    #ap.add_argument('--extra-file', action='append', help='Extra file(s) added to the root of your ZIP')
    ap.add_argument('--git', default=True, dest='git', action='store_true', help='Include git metadata in ZIP and S3 object')
    ap.add_argument('--no-git', dest='git', action='store_false')
    ap.add_argument('--keep', default=False, action='store_true', help='Keep temporary directory for troubleshooting')
    ap.add_argument('--log-level', type=str, help='Sets the logging level.  Try CRITICAL, ERROR, INFO, or DEBUG.  Default is INFO.')
    ap.add_argument('--omit', default=[], action='append', help='Regexes used to omit matching path/filenames from the ZIP file, e.g. --omit ^boto3')
    ap.add_argument('--src-dir', type=Path, default=Path('.'), help='Directory containing the lambda package source, e.g. python/example_lambda.  Default to current directory.')
    ap.add_argument('--tmp-dir', type=Path, help='Temporary directory used to install dependencies for zipping')
    ap.add_argument('--upload-s3-url', help='Upload to S3 URL, e.g. s3://jsw-lambda/example.zip')
    ap.add_argument('--zip', type=Path, help='Output ZIP filename')
    ap.add_argument('--debug', action='store_true', help='Break into pdb debugger right away.')
    args = vars(ap.parse_args())
    if 'debug' in args and args['debug']==True:
        pdb.set_trace()
    if 'log_level' in args:
        logger.setLevel(args['log_level'])
    args['src_dir'] = args['src_dir'].absolute()
    for omit_pattern in args['omit']:
        zip_omit.add(omit_pattern)
    if 'tmp_dir' in 'args':
        try:
            os.mkdir(args['tmp_dir'])
            logger.info(F'Created specified tmp directory {args["tmp_dir"]}')
        except FileExistsError:
            logger.info(F'Using existing, specified tmp directory {args["tmp_dir"]}')
    else:
        tdir = TemporaryDirectory()
        args['tmp_dir'] = Path(tdir.name)
        print(F'Created tmp directory {tdir}')
    metadata = {}
    if args.get('git', False):
        metadata = git_get_metadata(src_dir=args['src_dir'])
    metadata['lambda_zip_host'] = socket.gethostname()
    metadata['lambda_zip_timestamp'] = int(time.time())
    metadata['lambda_zip_user'] = getpass.getuser()
    emit_metadata_yaml(dst_yaml_path=Path(args['tmp_dir'], 'lambda_zip.yml'), metadata=metadata)
    if 'zip' in args:
        args['zip'] = Path(args['zip']).absolute()
    else:
        args['zip'] = Path(args['src_dir'].parent, args['src_dir'].name + '.zip')
    if 'aws_lambda_update' in args:
        if not 'upload_s3_url' in args:
            raise KeyError('You specified --aws-lambda-update which requires you use --upload-s3-url but no S3 URL was given.')

    install_to_dir(args['tmp_dir'], args['src_dir'])
    create_zip_file(tmp_dir=args['tmp_dir'], zip_filename=args['zip'], zip_omit_patterns=zip_omit)
    if 'upload_s3_url' in args:
        s3_upload(
            s3_url=args['upload_s3_url'],
            zip_filename=args['zip'],
        )
    if 'aws_lambda_update' in args:
        aws_lambda_update(
            function_name=args['aws_lambda_update'],
            s3_url=args['upload_s3_url'],
        )
