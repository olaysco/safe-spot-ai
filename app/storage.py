"""Store evidence images on local disk or in a private Azure container."""
import os
import re
from pathlib import Path


def check_key(key):
    if not re.fullmatch(r'[a-f0-9]{32}', key):
        raise ValueError('Invalid evidence image key.')
    return key


class LocalStorage:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def put(self, key, content):
        (self.directory / check_key(key)).write_bytes(content)

    def get(self, key):
        return (self.directory / check_key(key)).read_bytes()

    def delete(self, key):
        (self.directory / check_key(key)).unlink(missing_ok=True)

    def close(self):
        pass


class AzureStorage:
    def __init__(self):
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient
        self.credential = DefaultAzureCredential(managed_identity_client_id=os.getenv('AZURE_CLIENT_ID'))
        self.service = BlobServiceClient(os.environ['AZURE_STORAGE_ACCOUNT_URL'], credential=self.credential,
                                         connection_timeout=10, read_timeout=30, retry_total=2)
        self.container = self.service.get_container_client(os.getenv('AZURE_STORAGE_CONTAINER', 'evidence'))

    def put(self, key, content):
        from azure.storage.blob import ContentSettings
        self.container.upload_blob(check_key(key), content, overwrite=False,
                                   content_settings=ContentSettings(content_type='image/jpeg'))

    def get(self, key):
        from azure.core.exceptions import ResourceNotFoundError
        try:
            return self.container.download_blob(check_key(key)).readall()
        except ResourceNotFoundError as error:
            raise FileNotFoundError(key) from error

    def delete(self, key):
        from azure.core.exceptions import ResourceNotFoundError
        try:
            self.container.delete_blob(check_key(key))
        except ResourceNotFoundError:
            pass

    def close(self):
        self.service.close()
        self.credential.close()


def create_storage():
    backend = os.getenv('STORAGE_BACKEND', 'local')
    if backend == 'azure':
        return AzureStorage()
    if backend == 'local':
        return LocalStorage(os.getenv('UPLOAD_DIR', '.local/uploads'))
    raise ValueError('Unsupported evidence storage backend.')
