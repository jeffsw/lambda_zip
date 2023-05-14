import boto3

class AwsLambdaLayerVersion:
    '''
    Class representing one version of an AWS Lambda Layer.

    See https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/lambda/client/get_layer_version.html
    '''
    def __init__(
        self,
        Content:dict=None,
        LayerArn:str=None,
        LayerVersionArn:str=None,
        Description:str=None,
        CreatedDate:str=None,
        Version:int=None,
        CompatibleRuntimes:set=None,
        LicenseInfo:str=None,
        CompatibleArchitectures:set=None,
    ):
        if Content != None:
            self.Content = Content
        if LayerArn != None:
            self.LayerArn = LayerArn
        if LayerVersionArn != None:
            self.LayerVersionArn = LayerVersionArn
        if Description != None:
            self.Description = Description
        if CreatedDate != None:
            self.CreatedDate = CreatedDate
        if Version != None:
            self.Version = Version
        if CompatibleRuntimes != None:
            self.CompatibleRuntimes = CompatibleRuntimes
        if LicenseInfo != None:
            self.LicenseInfo = LicenseInfo
        if CompatibleArchitectures != None:
            self.CompatibleArchitectures = CompatibleArchitectures
    
    @classmethod
    def get_lambda_layer_version(
        cls,
        name:str,
        version:int,
        boto3_lambda_client:boto3.Lambda.Client=None,
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
