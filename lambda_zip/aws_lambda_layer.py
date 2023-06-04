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
        self.highest_version = None
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
                # create an AwsLambdaLayerVersion object wrapping the response and add it to available_versions
                lvobj = AwsLambdaLayerVersion(**layer_version)
                retobj.available_versions[layer_version['Version']] = lvobj
                if retobj.highest_version == None or retobj.highest_version.Version < lvobj.Version:
                    retobj.highest_version = lvobj
        # copy some attributes from the highest version to the overall AwsLambdaLayer
        for field_name in cls.copy_fields_from_highest_version:
            field_value = getattr(retobj.highest_version, field_name)
            setattr(retobj, field_name, field_value)
        
        return retobj
    
    def get_highest_version_details(
        self,
        boto3_lambda_client=None,
    ):
        keys_reverse_order = reversed(self.available_versions)
        highest_version = next(keys_reverse_order)
        retobj = self.get_version_details(version=highest_version, boto3_lambda_client=boto3_lambda_client)
        return retobj

    def get_highest_version_matching_sha256b64(self, search_val):
        '''
        Search the available_versions for the highest version with a matching SHA-256.  Returns either
        an AwsLambdaLayerVersion object or None if there is no apparent match.

        This is used for de-duplication.
        '''
        candidate_match = None
        for ver, ver_obj in self.available_versions.items():
            if search_val == ver_obj.get_metadata_sha256b64():
                candidate_match = ver_obj
        return candidate_match

    def get_version_details(
        self,
        version:int,
        boto3_lambda_client=None
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
