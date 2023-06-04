import boto3

class AwsLambdaFunction:
    '''
    Class wrapping AWS lambda function parameters, and some methods, for convenience.

    See https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/lambda/client/get_function.html
    '''
    def __init__():
        pass

    @classmethod
    def get_function(
        cls,
        name:str,
        boto3_client=None,
        qualifier:str=None,
    ):
        '''
        Get a given function from the AWS API and return an AwsLambdaFunction object.
        Wraps boto3 Lambda.Client.client-get_function()
        '''
        if boto3_client == None:
            boto3_client = boto3.client('lambda')
        get_func_args = {
            'FunctionName': name,
        }
        if qualifier != None:
            get_func_args['Qualifier'] = qualifier
        response = boto3_client.get_function(**get_func_args)
        retobj = cls()
        for k in ['Configuration', 'Tags']:
            setattr(retobj, k, response[k])
        return retobj
