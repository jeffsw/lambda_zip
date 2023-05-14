import boto3

from lambda_zip.aws_lambda_layer_version import AwsLambdaLayerVersion

class AwsLambdaLayer:
    '''
    Class wrapping AWS lambda layer functions for convenience.

    See https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/lambda/paginator/ListLayerVersions.html
    '''
    copy_fields_from_highest_version = [
        'Version',
        'Description',
        'CreatedDate',
        'CompatibleRuntimes',
        'LicenseInfo',
        'CompatibleArchitectures',
    ]

    def __init__(self, name:str):
        self.name = name
        self.available_versions = dict()
        self.version_details = dict()

    @classmethod
    def get_lambda_layer(
        cls,
        name:str,
        boto3_lambda_client=None,
    ):
        '''
        Get a given layer (and data on all its available versions) from the AWS API.
        Return an AwsLambdaLayer object.
        '''
        if boto3_lambda_client == None:
            boto3_lambda_client = boto3.client('lambda')

        retobj = cls(name=name)

        response_iterator = boto3_lambda_client.get_paginator('list_layer_versions').paginate(
            LayerName=name
        )
        for response_page in response_iterator:
            for layer_version in response_page.get('LayerVersions', []):
                retobj.available_versions[layer_version['Version']] = layer_version
                highest_version = layer_version
        # copy some attributes from the highest version to the overall AwsLambdaLayer
        for field_name in cls.copy_fields_from_highest_version:
            if field_name in highest_version:
                setattr(retobj, field_name, highest_version[field_name])
        
        return retobj
    
    def get_highest_version_details(
        self,
        boto3_lambda_client:boto3.Lambda.Client=None,
    ):
        keys_reverse_order = reversed(self.available_versions)
        highest_version = next(keys_reverse_order)
        retobj = self.get_version_details(version=highest_version, boto3_lambda_client=boto3_lambda_client)
        return retobj

    def get_version_details(
        self,
        version:int,
        boto3_lambda_client:boto3.Lambda.Client=None
    ):
        '''
        Return an AwsLambdaLayerVersion object, querying the boto3 API if needed.
        '''
        retobj = AwsLambdaLayerVersion.get_lambda_layer_version(
            name = self.get_name(),
            version = version,
            boto3_lambda_client = boto3_lambda_client,
        )
        self.version_details[version] = retobj
        return retobj
