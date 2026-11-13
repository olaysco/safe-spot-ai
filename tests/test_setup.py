from fastapi.testclient import TestClient
from app.main import create_app
from app.security import hash_password, verify_password
from app.database import User, connect
from app.manage import configure_demo_accounts
from app.worker import staff_recipients


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


def test_short_demo_logins_keep_notification_addresses(tmp_path):
    app = create_app(f'sqlite:///{tmp_path}/logins.db', worker=False)
    with app.state.db() as db:
        accounts = configure_demo_accounts(db)
        db.commit()
        account_ids = {role: account.id for role, account in accounts.items()}
    with TestClient(app, headers={'x-safe-spot': '1'}) as client:
        for role, alias in [('officer', 'field'), ('handler', 'case'), ('manager', 'manager')]:
            email = f'{alias}@gmail.com'
            failed = client.post('/api/auth/login', json={'email': email, 'password': 'wrong'})
            assert failed.status_code == 401
            response = client.post('/api/auth/login', json={'email': email.upper(), 'password': 'password'})
            assert response.status_code == 200
            assert response.json()['id'] == account_ids[role]
            assert response.json()['role'] == role
            with app.state.db() as db:
                assert staff_recipients(db, role, account_ids[role]) == [f'functionzy+{alias}@gmail.com']
            assert client.post('/api/auth/logout').status_code == 200
