import copy
import re
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.database import Case, Group, Notification, User
from app.domain import new_case, riddor_details
from app.main import create_app
from app.security import digest, hash_password
from app.worker import deliver, scan_alerts, tick

HEADERS = {'x-safe-spot': '1'}
REPORT = {'description': 'Water is on the floor beside the east entrance.', 'location': 'East entrance', 'time': 'Today at 09:15', 'harm': 'No injury', 'remains': 'Still wet', 'age_range': 'Under 18', 'consent': False, 'confirmed': True}


@pytest.fixture
def system(tmp_path, monkeypatch):
    monkeypatch.setenv('UPLOAD_DIR', str(tmp_path/'uploads'))
    monkeypatch.setenv('EMAIL_MODE', 'capture')
    app = create_app(f'sqlite:///{tmp_path}/test.db', worker=False)
    with app.state.db() as db:
        for name, role in [('handler', 'handler'), ('officer', 'officer'), ('other', 'officer'), ('manager', 'manager')]:
            db.add(User(id=name, name=name, email=name+'@example.test', role=role, password=hash_password('test-password')))
        db.commit()
    with TestClient(app, headers=HEADERS) as client:
        yield app, client


def login(client, name):
    response = client.post('/api/auth/login', json={'email': name+'@example.test', 'password': 'test-password'})
    assert response.status_code == 200, response.text


def create(client):
    response = client.post('/api/reports', json=REPORT)
    assert response.status_code == 201, response.text
    return response.json()


def mutate(client, case, action, **fields):
    return client.post('/api/cases/'+case['id']+'/'+action, json={'version': case['version'], **fields})


def assign(client, case):
    response = mutate(client, case, 'triage', category='Hazard', priority='Urgent', officer_id='officer', reason='Evidence confirms a wet floor.', approve=True)
    assert response.status_code == 200, response.text
    return response.json()


def test_full_lifecycle_and_approval_invalidation(system):
    app, client = system
    receipt = create(client)
    assert client.get('/api/cases').status_code == 401
    login(client, 'handler')
    case = client.get('/api/cases/'+receipt['id']).json()
    assert mutate(client, case, 'close').status_code == 409
    case = assign(client, case)
    assert mutate(client, case, 'findings', details='Checked floor', evidence='Photo', assistance='None', control='Dry', approve=True).status_code == 403
    login(client, 'other')
    assert client.get('/api/cases/'+case['id']).status_code == 404
    assert client.get('/api/cases').json() == []
    login(client, 'officer')
    case = mutate(client, case, 'findings', details='Checked the floor', evidence='Inspection recorded', assistance='Cleaning team', control='Floor cleaned and dry', approve=True).json()
    login(client, 'handler')
    case = mutate(client, case, 'response', text='We inspected and dried the floor.', approve=True).json()
    case = mutate(client, case, 'send').json()
    case = mutate(client, case, 'close').json()
    assert case['status'] == 'Closed'
    tracked = client.post('/api/tracking', json={'reference': receipt['reference']}).json()
    assert tracked['status'] == 'Closed'
    assert 'report' not in tracked and 'history' not in tracked
    stale = copy.deepcopy(case)
    case = mutate(client, case, 'response', text='A revised outcome needs approval.', approve=False).json()
    assert case['status'] == 'Risk controlled' and case['sent'] is None
    assert mutate(client, case, 'send').status_code == 409
    assert mutate(client, stale, 'close').status_code == 409


def test_staff_email_uses_current_accounts_and_keeps_reporter_recipients(system):
    app, client = system
    receipt = client.post('/api/reports', json={**REPORT, 'email': 'reporter@example.test'}).json()
    login(client, 'handler')
    case = assign(client, client.get('/api/cases/'+receipt['id']).json())
    first_assignment = case['approvals']['triage']['at']
    case = mutate(client, case, 'triage', category='Hazard', priority='Urgent', officer_id='other',
                  reason='Another officer will inspect the entrance.', approve=True).json()
    login(client, 'other')
    case = mutate(client, case, 'findings', details='Inspected the floor', evidence='Inspection recorded',
                  assistance='None', control='Floor cleaned and dry', approve=True).json()
    login(client, 'handler')
    case = mutate(client, case, 'response', text='The officer inspected and dried the floor.', approve=True).json()
    assert mutate(client, case, 'send').status_code == 200
    with app.state.db() as db:
        for user_id, alias in [('handler', 'case'), ('other', 'field'), ('manager', 'manager')]:
            db.get(User, user_id).email = f'functionzy+{alias}@gmail.com'
        scan_alerts(db)
        db.commit()
    deliver(app.state.db)
    with app.state.db() as db:
        notes = list(db.scalars(select(Notification)))
        for note in notes:
            if note.key == f'assignment:{case["id"]}:{first_assignment}':
                assert note.state == 'cancelled'
                continue
            assert note.state == 'captured'
            expected = {'receipt': 'reporter@example.test', 'outcome': 'reporter@example.test',
                        'handler': 'functionzy+case@gmail.com', 'officer': 'functionzy+field@gmail.com',
                        'manager': 'functionzy+manager@gmail.com'}[note.data['kind']]
            assert note.data['recipients'] == [expected]
        assert {note.data['kind'] for note in notes} == {'receipt', 'outcome', 'handler', 'officer', 'manager'}


def test_tracking_and_csrf(system):
    app, client = system
    receipt = create(client)
    assert 'tracking_token' not in receipt
    assert re.fullmatch(r'SS-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{5}-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{5}', receipt['reference'])
    for reference in (receipt['reference'], receipt['reference'].lower(), receipt['reference'].replace('-', ' '), receipt['reference'].replace('-', '')):
        response = client.post('/api/tracking', json={'reference': reference})
        assert response.status_code == 200
        assert response.json()['reference'] == receipt['reference']
        assert 'report' not in response.json() and 'id' not in response.json()
    assert client.post('/api/tracking', json={'reference': 'SS-UNKNOWN'}).status_code == 404
    with app.state.db() as db:
        case = db.get(Case, receipt['id'])
        case.reference = 'SS-AB12CD34'
        case.tracking_hash = digest('former-private-tracking-code')
        db.commit()
    assert client.post('/api/tracking', json={'reference': 'ss-ab12cd34'}).status_code == 200
    assert client.post('/api/reports', json=REPORT, headers={'x-safe-spot': ''}).status_code == 403
    assert client.post('/api/reports', json=REPORT, headers={'origin': 'https://untrusted.test'}).status_code == 403
    assert client.post('/api/reports', json={**REPORT, 'confirmed': False}).status_code == 422
    assert client.post('/api/reports', json={**REPORT, 'age_range': '15'}).status_code == 422


def test_alerts_are_deduplicated_and_skip_controlled_risks(system):
    app, client = system
    ids = [create(client)['id'] for _ in range(3)]
    with app.state.db() as db:
        for i in ids:
            case = db.get(Case, i)
            case.created = time.time()-6*3600
        db.add(Group(data={'case_ids': ids, 'relationship': 'recurring', 'reason': 'Different dates', 'by': 'handler', 'at': time.time()}))
        db.commit()
        scan_alerts(db)
        db.commit()
        first = len(list(db.scalars(select(Notification))))
        scan_alerts(db)
        db.commit()
        assert len(list(db.scalars(select(Notification)))) == first
        assert len(list(db.scalars(select(Notification).where(Notification.key.like('recurrence:%'))))) == 1
    tick(app.state.db)
    with app.state.db() as db:
        assert all(n.state == 'captured' for n in db.scalars(select(Notification)))


def test_ai_failure_preserves_report(system, monkeypatch):
    app, client = system
    monkeypatch.delenv('TEXT_AI_BASE_URL', raising=False)
    r = client.post('/api/reports', json={**REPORT, 'consent': True}).json()
    tick(app.state.db)
    login(client, 'handler')
    case = client.get('/api/cases/'+r['id']).json()
    assert case['ai']['status'] == 'unavailable'
    assert case['status'] == 'Needs review'
    assert case['report']['description'] == REPORT['description']


def test_statutory_dates(system):
    assert riddor_details({'kind': 'fifteen', 'incident_date': '2026-01-28'})['due'] == '2026-02-12'
    assert riddor_details({'kind': 'ten', 'incident_date': '2028-02-25'})['due'] == '2028-03-06'
    assert riddor_details({'kind': 'ten', 'incident_date': '2026-01-01', 'received_date': '2026-01-02'})['status'] == 'Notification evidence needed'


def test_group_creation_requires_human_and_different_reports(system):
    _, client = system
    r = create(client)
    login(client, 'officer')
    assert client.post('/api/groups', json={'case_ids': [r['id'],r['id']], 'relationship': 'recurring', 'reason': 'A test'}).status_code == 403
    login(client, 'handler')
    assert client.post('/api/groups', json={'case_ids': [r['id'],r['id']], 'relationship': 'recurring', 'reason': 'A test'}).status_code == 422


def test_reporter_image_upload_does_not_expose_case(system):
    import io
    from PIL import Image
    _, client = system
    receipt = create(client)
    buffer = io.BytesIO()
    Image.new('RGB', (10, 10), 'blue').save(buffer, format='PNG')
    denied = client.post('/api/cases/'+receipt['id']+'/attachments', headers={'x-report-reference': 'SS-WRONG'}, files={'file': ('evidence.png', buffer.getvalue(), 'image/png')})
    assert denied.status_code == 401
    response = client.post('/api/cases/'+receipt['id']+'/attachments', headers={'x-report-reference': receipt['reference']}, files={'file': ('evidence.png', buffer.getvalue(), 'image/png')})
    assert response.status_code == 201, response.text
    assert set(response.json()) == {'id', 'name'}
    photo_id = response.json()['id']
    assert client.get('/api/attachments/'+photo_id).status_code == 401
    login(client, 'handler')
    assert client.get('/api/attachments/'+photo_id).status_code == 200
    case = client.get('/api/cases/'+receipt['id']).json()
    assign(client, case)
    assert client.post('/api/cases/'+receipt['id']+'/attachments', headers={'x-report-reference': receipt['reference']}, files={'file': ('evidence.png', buffer.getvalue(), 'image/png')}).status_code == 403


def test_report_assistance_needs_consent_and_keeps_human_review(system, monkeypatch):
    from app import ai
    _, client = system
    payload = {'description': 'Water covers the floor near the east entrance.', 'consent': True}
    monkeypatch.setattr(ai, 'generate', lambda *args, **kwargs: '{"location":"east entrance","time":"","harm":"","remains":"Water covers the floor"}')
    response = client.post('/api/report-assistance', json=payload)
    assert response.status_code == 200
    assert response.json()['requires_review'] is True
    assert response.json()['details']['time'] == ''
    assert client.post('/api/report-assistance', json={**payload, 'consent': False}).status_code == 422
    monkeypatch.setattr(ai, 'generate', lambda *args, **kwargs: 'Invalid output')
    assert client.post('/api/report-assistance', json=payload).status_code == 503


def test_ai_triage_keeps_staff_approval_pending(system, monkeypatch):
    from app import ai
    app, client = system
    monkeypatch.setenv('TEXT_AI_MODEL', 'gpt-5-mini')
    monkeypatch.setattr(ai, 'generate', lambda *args, **kwargs: '{"category":"Hazard","priority":"Urgent"}')
    receipt = client.post('/api/reports', json={**REPORT, 'consent': True}).json()
    tick(app.state.db)
    login(client, 'handler')
    case = client.get('/api/cases/'+receipt['id']).json()
    assert case['ai']['suggestions'] == {'category': 'Hazard', 'priority': 'Urgent'}
    assert case['status'] == 'Needs review'
    assert not case['approvals'].get('triage')
    assert case['report']['description'] == REPORT['description']


def test_storage_failure_does_not_add_an_attachment(system, monkeypatch):
    import io
    from PIL import Image
    from app.database import Attachment
    app, client = system
    receipt = create(client)
    content = io.BytesIO()
    Image.new('RGB', (10, 10)).save(content, format='PNG')
    def unavailable(*args):
        raise OSError('Storage offline')
    monkeypatch.setattr(app.state.storage, 'put', unavailable)
    response = client.post('/api/cases/'+receipt['id']+'/attachments', headers={'x-report-reference': receipt['reference']}, files={'file': ('photo.png', content.getvalue(), 'image/png')})
    assert response.status_code == 503
    with app.state.db() as db:
        assert list(db.scalars(select(Attachment))) == []


def test_worker_entry_point_processes_notifications(system, monkeypatch):
    from app import database as database_module
    from app.worker import run_once
    app, client = system
    create(client)
    factory = app.state.db
    engine = factory.kw['bind']
    monkeypatch.setattr(database_module, 'connect', lambda: (engine, factory))
    run_once()
    with factory() as db:
        assert all(n.state == 'captured' for n in db.scalars(select(Notification)))
