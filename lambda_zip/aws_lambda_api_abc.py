from abc import ABC, abstractmethod


class AWSLambdaApiAbc(ABC):
    """
    Abstract Base Class providing guidance on required methods for wrapping or mocking the Lambda API.

    This isn't meant for exposing all of Lambda's functionality.  Rather, it's documenting which functionality
    lambda-zip uses and therefore needs to mock for testing.
    """

    @abstractmethod
    def function_get(
        self,
        name: str,
        version: int = None,
    ):
        pass

    @abstractmethod
    def function_update(
        self,
        name: str,
        s3_url: str,
        layer_arn: str = None,
        retry_interval: float = 15,
        timeout: float = 90,
    ):
        pass

    @abstractmethod
    def layer_get(
        self,
        name: str,
    ):
        pass

    @abstractmethod
    def layer_version_details_get(
        self,
        name: str,
        version: int,
    ):
        pass

    @abstractmethod
    def layer_version_publish(
        self,
        name: str,
        s3_bucket: str,
        s3_key: str,
        description: str = None,
        s3_object_version: int = None,
    ):
        pass
