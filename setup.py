from setuptools import setup, find_packages

setup(
    version='1.0',
    name = 'lambda_zipper',
    author = 'Jeff Wheeler',
    author_email = 'jeffsw6@gmail.com',
    url = 'https://github.com/jeffsw/lambda_zipper/',
    description = 'Prepare ZIP file for deploying to AWS Lambda',
    keywords = ['AWS'],
    packages = find_packages(),
    install_requires = ['boto3', 'GitPython'],
    entry_points = {
        'console_scripts': [
            'lambda-zipper = lambda_zipper:cli_entry_point',
        ]
    }
)
