from fastapi.testclient import TestClient
from app.main import create_app
from app.security import hash_password, verify_password
from app.database import User, connect
from app.manage import configure_demo_accounts


def test_health(tmp_path):
    with TestClient(create_app(f'sqlite:///{tmp_path}/test.db', worker=False)) as client:
        assert client.get('/api/health').json()['status'] == 'ok'


def test_password_hash():
    stored = hash_password('test-password')
    assert verify_password('test-password', stored)
    assert not verify_password('wrong-password', stored)
    assert stored != hash_password('test-password')


def test_demo_accounts_keep_existing_staff_ids(tmp_path):
    engine, factory = connect(f'sqlite:///{tmp_path}/accounts.db')
    with factory() as db:
        db.add(User(id='assigned-officer', name='Sam Taylor', role='officer',
                    email='officer@safespot.test', password=hash_password('former-password')))
        db.commit()
        accounts = configure_demo_accounts(db)
        db.commit()
        assert accounts['officer'].id == 'assigned-officer'
        assert accounts['officer'].email == 'functionzy+field@gmail.com'
        assert accounts['handler'].email == 'functionzy+case@gmail.com'
        assert accounts['manager'].email == 'functionzy+manager@gmail.com'
        assert all(verify_password('password', account.password) for account in accounts.values())
        configure_demo_accounts(db)
        db.commit()
        assert db.query(User).count() == 3
    engine.dispose()
