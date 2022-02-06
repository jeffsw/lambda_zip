from setuptools import setup, find_packages

setup(
    version='1.220601',
    name = 'lambda_zip',
    author = 'Jeff Wheeler',
    author_email = 'jeffsw6@gmail.com',
    url = 'https://github.com/jeffsw/lambda_zip/',
    description = 'Prepare ZIP file for deploying to AWS Lambda',
    keywords = ['AWS'],
    packages = find_packages(),
    install_requires = ['boto3', 'GitPython', 'toml'],
    entry_points = {
        'console_scripts': [
            'lambda-zip = lambda_zip:cli_entry_point',
        ]
    }
)
