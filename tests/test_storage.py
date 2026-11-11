from unittest.mock import Mock
import pytest
from azure.core.exceptions import ResourceNotFoundError
from app.storage import AzureStorage, LocalStorage, create_storage

KEY = 'a' * 32


def test_local_storage_round_trip_and_key_validation(tmp_path):
    storage = LocalStorage(tmp_path)
    storage.put(KEY, b'image')
    assert storage.get(KEY) == b'image'
    storage.delete(KEY)
    storage.delete(KEY)
    with pytest.raises(FileNotFoundError):
        storage.get(KEY)
    with pytest.raises(ValueError):
        storage.put('../outside', b'image')


def test_azure_storage_uses_identity_and_private_objects(monkeypatch):
    import azure.identity
    import azure.storage.blob
    credential = Mock()
    service = Mock()
    monkeypatch.setenv('AZURE_STORAGE_ACCOUNT_URL', 'https://example.blob.core.windows.net')
    monkeypatch.setenv('AZURE_CLIENT_ID', 'identity-id')
    credential_class = Mock(return_value=credential)
    service_class = Mock(return_value=service)
    monkeypatch.setattr(azure.identity, 'DefaultAzureCredential', credential_class)
    monkeypatch.setattr(azure.storage.blob, 'BlobServiceClient', service_class)
    storage = AzureStorage()
    credential_class.assert_called_once_with(managed_identity_client_id='identity-id')
    service.get_container_client.assert_called_once_with('evidence')
    container = service.get_container_client.return_value
    storage.put(KEY, b'image')
    assert container.upload_blob.call_args.kwargs['overwrite'] is False
    assert container.upload_blob.call_args.kwargs['content_settings'].content_type == 'image/jpeg'
    container.download_blob.return_value.readall.return_value = b'image'
    assert storage.get(KEY) == b'image'
    container.download_blob.side_effect = ResourceNotFoundError('Missing')
    with pytest.raises(FileNotFoundError):
        storage.get(KEY)
    container.delete_blob.side_effect = ResourceNotFoundError('Missing')
    storage.delete(KEY)
    storage.close()
    credential.close.assert_called_once()
    service.close.assert_called_once()


def test_unknown_backend_fails_instead_of_using_local_disk(monkeypatch):
    monkeypatch.setenv('STORAGE_BACKEND', 'invalid')
    with pytest.raises(ValueError):
        create_storage()
