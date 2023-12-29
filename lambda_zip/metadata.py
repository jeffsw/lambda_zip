from zipfile import ZipFile


class LambdaZipMetadata:
    description_encoded_fields = {
        'branch',
        'commit',
        'describe',
        'dirty',
        'sha256',
        'untracked'
    }
    description_encoded_fields_truncate_to_length = {
        'branch': 40,
        'describe': 20,
    }

    def __init__(
        self,
        branch: str,
        commit: str,
        describe: str,
        dirty: bool,
        untracked: bool,
        sha256: str = None,
    ):
        pass

    @classmethod
    def new_from_zip_file_obj(cls, zf: ZipFile):
        pass

    def encode_metadata_for_lambda_layer_description(self) -> str:
        """
        We put metadata into Lambda Layer descriptions so we can efficiently de-duplicate.  We can't
        easily produce the same output SHA256 `.zip` file on a repeat build.  Therefore, we store a custom
        SHA256 (which excludes ZIP file inner-timestamps, certain builder info, etc.) and other data
        in the description field of layers.
        """
        pass

    def set_sha256(self, sha256:str):
        """
        Invoke this method with a base64-encoded sha256 checksum of the zip contents (except files we
        exclude) before requesting the description-encoded, JSON, or YAML output.
        """
        pass
