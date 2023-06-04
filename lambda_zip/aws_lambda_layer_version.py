import json
import logging

import boto3

logger = logging.getLogger(__name__)

class AwsLambdaLayerVersion:
    '''
    Class representing one version of an AWS Lambda Layer.

    See https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/lambda/client/get_layer_version.html
    '''
    # If any of the metadata_required_fields are missing, metadata will not be loaded from description.
    metadata_required_fields = [
        'branch',
        'commit',
        'describe',
        'dirty',
        'sha256b64',
        'untracked',
    ]

    def __init__(
        self,
        CompatibleArchitectures:set=None,
        CompatibleRuntimes:set=None,
        Content:dict=None,
        CreatedDate:str=None,
        Description:str=None,
        LayerArn:str=None,
        LayerVersionArn:str=None,
        LicenseInfo:str=None,
        Version:int=None,
    ):
        self.metadata = None
        self.CompatibleArchitectures = CompatibleArchitectures
        self.CompatibleRuntimes = CompatibleRuntimes
        self.Content = Content
        self.CreatedDate = CreatedDate
        self.Description = Description
        self.LayerArn = LayerArn
        self.LayerVersionArn = LayerVersionArn
        self.LicenseInfo = LicenseInfo
        self.Version = Version
    
    @classmethod
    def get_lambda_layer_version(
        cls,
        name:str,
        version:int,
        boto3_lambda_client=None,
    ):
        if boto3_lambda_client == None:
            boto3_lambda_client = boto3.client('lambda')
        response = boto3_lambda_client.get_layer_version(
            LayerName=name,
            VersionNumber=version,
        )
        retobj = cls(**response)
        return retobj

    def get_code_sha256(self):
        return self.Content['CodeSha256']

    def get_description(self):
        return self.Description

    def get_description_encoded_metadata(self):
        '''
        Layer Versions created by this package will have metadata encoded in the description, including the
        SHA-256 of the ZIP.  This reduces the number of AWS API calls required for de-duplication.

        If there is no description-encoded metadata, we just return None.
        '''
        if self.metadata != None:
            return self.metadata
        try:
            candidate_metadata = json.loads(self.Description)
        except:
            logger.warning(f"Layer version {self.Version} doesn't have valid description-encoded metadata: "+
                           f"{getattr(self, 'Description', 'MISSING ATTRIBUTE')}")
            return None

        for field_name in self.metadata_required_fields:
            if field_name not in candidate_metadata:
                logger.error(f"Layer version {self.Version} missing description-encoded field {field_name}")
        self.metadata = candidate_metadata
        return self.metadata

    def get_metadata_sha256b64(self):
        metadata = self.get_description_encoded_metadata()
        if metadata == None:
            return None
        retstr = metadata['sha256b64']
        return retstr

    def get_metadata_sha256b64_or_empty_string(self):
        '''
        This is a convenience method.  When figuring out whether we need to create a new Layer Version,
        lambda-zip will compare a newly-built layer.ZIP SHA-256 to the description-encoded SHA-256 of
        each existing version (except ones without description-encoded metadata).

        The "or empty string" can simplify the calling code.
        '''
        try:
            self.get_metadata_sha256b64()
        except:
            return ''
