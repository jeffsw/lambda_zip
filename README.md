`lambda-zip` helps you package, upload, and deploy Python code to [AWS Lambda](https://aws.amazon.com/lambda/).  Why is this so complex it needs a tool?  Dependencies!  If your code depends on any packages not already found in the lambda environment (or a layer) you'll save time by using a tool to gather the deps and zip everything up.

## What this doesn't do

This doesn't instantiate a lambda function in the AWS API.  It can update a named lambda which already exists, but I think other tools like Terraform are already good at creating & configuring a lambda, along with its IAM setup, triggers, etc.

If you want a Python tool which can both create and deploy a lambda, try [lambda-tools](https://github.com/jammycakes/lambda-tools), which has different design goals.

# Example invocation

From your lambda's package directory (containing `pyproject.toml`) invoke `lambda-zip` with any optional arguments, for example, `--upload-s3-url` to upload the zipped lambda to S3 and `--aws-lambda-update` to update the named function after upload:

```
jsw@boomer rpkilog/python/rpkilog main * % lambda-zip --upload-s3-url s3://rpkilog-artifact/lambda_vrp_cache_diff.zip --aws-lambda-update vrp_cache_diff

# ... lots of pip output from gathering your dependencies

INFO:lambda_zip:Creating ZIP file /Users/jsw/src/rpkilog/python/rpkilog.zip from tmp_dir /var/folders/xl/d25krdzx4yj0spxpwrb_6s3h0000gn/T/tmpsaxcafkn
INFO:lambda_zip:Created ZIP containing 460 files.  Omitted 1324 regex matches.
INFO:lambda_zip:S3 uploading F/Users/jsw/src/rpkilog/python/rpkilog.zip to s3://rpkilog-artifact/lambda_vrp_cache_diff.zip
INFO:botocore.credentials:Found credentials in shared credentials file: ~/.aws/credentials
INFO:lambda_zip:Updating lambda function vrp_cache_diff
```



# Required `[lambda_zip]` section in pyproject.toml

Your Python package's `pyproject.toml` should contain a `[lambda_zip]` section.  A working example:

```toml
[build-system]
requires = ['setuptools', 'wheel']
build-backend = 'setuptools.build_meta'

[lambda_zip]
local_dependency = [
]
zip_omit = [
    "^botocore",
    "^boto3",
]
```



## local_dependency

If your project depends on code in another directory (Python package) present on your filesystem, but not found in a pip repo, you can give the path to that local dependency.  For example:

```toml
[lambda_zip]
local_dependency = [
    '../other_python_package',
    '../second_one'
]
```

## zip_omit

You may give a list of regular expressions used to filter files out of the final ZIP archive.  For example, if your code depends on `boto3` and pip will install that into the temp directory during the packaging process, but you know boto3 is already present in the AWS Lambda execution environment, you can significantly reduce the size of your ZIP, improving start-up time.

```toml
[lambda_zip]
zip_omit = [
    '^botocore',
    '^boto3'
]
```



# --help

```
usage: lambda-zip [-h] [--aws-lambda-update AWS_LAMBDA_UPDATE] [--git] [--no-git] [--keep] [--log-level LOG_LEVEL]
                     [--omit OMIT] [--src-dir SRC_DIR] [--tmp-dir TMP_DIR] [--upload-s3-url UPLOAD_S3_URL] [--zip ZIP]
                     [--debug]

optional arguments:
  -h, --help            show this help message and exit
  --aws-lambda-update AWS_LAMBDA_UPDATE
                        Specifies the AWS Lambda function name to update. Requires --upload-s3-url.
  --git                 Include git metadata in ZIP and S3 object
  --no-git
  --keep                Keep temporary directory for troubleshooting
  --log-level LOG_LEVEL
                        Sets the logging level. Try CRITICAL, ERROR, INFO, or DEBUG. Default is INFO.
  --omit OMIT           Regexes used to omit matching path/filenames from the ZIP file, e.g. --omit ^boto3
  --src-dir SRC_DIR     Directory containing the lambda package source, e.g. python/example_lambda. Default to current
                        directory.
  --tmp-dir TMP_DIR     Temporary directory used to install dependencies for zipping
  --upload-s3-url UPLOAD_S3_URL
                        Upload to S3 URL, e.g. s3://jsw-lambda/example.zip
  --zip ZIP             Output ZIP filename
  --debug               Break into pdb debugger right away.
```

# Layer Support

| :exclamation: The layer feature requires pip >= 22.2         |
| ------------------------------------------------------------ |
| The `--report` and `--dry-run` options are needed for metadata |

Lambda Layers may be used to store dependencies.  This could be helpful if you'd like to see your code
in the AWS Lambda console editor, which has a 3 MiB code size limit.  The Lambda [deployment package size limit](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html#function-configuration-deployment-and-execution) still applies to the combined size of your lambda function ZIP plus all layer ZIPs.  As of this writing, that limit is 50 MiB zipped and 250 MiB unzipped.  Layers aren't a workaround for these limits.

When you pass the `--layer-name` and `--layer-s3-url` arguments, and include the required configuration within your `pyproject.toml` (see below), a layer will be created with all dependencies.  It will omit the project directories or matching paths you've specified in the configuration.  For example:

```toml
[lambda_zipper]
# you must include layer_omit_projects AND/OR layer_omit_paths to use lambda-zip's layer mode
layer_omit_projects = ['my-proj']
layer_omit_paths = ['^python/my_config.yml']
```

When using the layer mode, your python function deployment ZIP will not include any dependencies.  All those dependencies will be stored in the layer.

## Metadata saved in layer description

### Layer Description

Build metadata will be saved into the layer description within the AWS API.  This 256-byte field will look like the below example, except that it may be truncated as needed to <= 256 bytes.

```yaml
branch: GH-10-pagination-support
commit: f23306e47e3c93e28535581f561f7ed1e400f7fe
describe: f23306e
dirty: false
host: boomer
path: /Users/jsw/src/rpkilog/python/rpkilog
timestamp: 1676932215
untracked: 0
user: jsw
```

## Update Reduction

The AWS API provides the SHA-256 hash of existing versions of your layer.  When you invoke `lambda-zip` with layer mode, the hash of the resulting layer deployment ZIP will be compared to the available versions already in AWS.

If an SHA-256 match is found, a new version doesn't need to be created.  Your new lambda (assuming `--aws-lambda-update` was given) will be configured to use the matching layer version.

### Projects With `console_scripts` and Similar

If your lambda's main project (its not dependencies) contains CLI entrypoints, e.g. `rpkilog-hapi` you should include those in `layer_omit_paths` or it may result in spurious updates of your layer, if that layer is used by multiple projects.  For example, if you use a common layer for `acme-httpapi` and `acme-nightly-job` lambdas, but `acme-httpapi` installs something into `bin/`, your layer will often be replaced by a new version due to the presence of `bin/acme-httpapi` when the layer is built from that project, but absence of that file when built from your other project.

The reason for this caveat is there's no `pip uninstall --target <tmpdir> your_main_project` functionality in pip.  It's not that easy to correctly omit your project files from the layer.
