from fastapi.testclient import TestClient
from app.main import create_app
from app.security import hash_password, verify_password


def test_health(tmp_path):
    with TestClient(create_app(f'sqlite:///{tmp_path}/test.db', worker=False)) as client:
        assert client.get('/api/health').json()['status'] == 'ok'


def test_password_hash():
    stored = hash_password('test-password')
    assert verify_password('test-password', stored)
    assert not verify_password('wrong-password', stored)
    assert stored != hash_password('test-password')
