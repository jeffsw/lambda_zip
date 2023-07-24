
class LambdaZipMetadata:
    layer_publish_fields = {
        'branch',
        'commit',
        'describe',
        'dirty',
        'sha256',
        'untracked',
    }
    layer_truncate_fields_to_length = {
        'branch': 40,
        'describe': 20,
    }

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
