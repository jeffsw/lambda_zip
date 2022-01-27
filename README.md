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

