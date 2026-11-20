import copy
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import ai, assignment
from app.database import CapacityChange, Case, OfficerProfile, User, connect
from app.domain import new_case
from app.manage import configure_demo_accounts, configure_demo_officers
from app.main import create_app
from app.security import hash_password


REPORT = {'description': 'Water is on the entrance floor.', 'location': 'East entrance',
          'harm': 'No injury reported', 'remains': 'Still wet', 'consent': False}


@pytest.fixture
def database(tmp_path):
    engine, factory = connect(f'sqlite:///{tmp_path}/assignment.db')
    with factory() as db:
        for name, department, available, capacity in [
            ('a', 'Facilities', True, 2), ('b', 'Facilities', True, 4),
            ('c', 'Security', True, 4), ('d', 'Facilities', False, 4),
            ('e', 'Facilities', True, 0),
        ]:
            db.add(User(id=name, name=name, email=name+'@example.test', role='officer', password='unused'))
            db.add(OfficerProfile(user_id=name, department=department, available=available, capacity=capacity, demo=True))
        db.add(User(id='legacy', name='Legacy', email='legacy@example.test', role='officer', password='unused'))
        db.add(Case(id='new', reference='NEW', tracking_hash='unused', data=new_case(REPORT)))
        db.commit()
    yield factory
    engine.dispose()


def assigned(db, case_id, officer='a', controlled=False, closed=False):
    data = new_case(REPORT)
    data['officer_id'] = officer
    data['approvals']['triage'] = {'at': 1}
    if controlled:
        data['approvals']['field'] = {'at': 2}
    data['closed'] = closed
    db.add(Case(id=case_id, reference=case_id, tracking_hash='unused', data=data))


def test_recommendation_excludes_wrong_department_unavailable_and_full(database):
    with database() as db:
        assigned(db, 'active')
        db.commit()
        result = assignment.recommend(db, db.get(Case, 'new'), 'Facilities')
        assert result['recommended_officer_id'] == 'b'
        assert result['source'] == 'manual'
        rows = {r['id']: r for r in result['candidates']}
        assert rows['a']['active_cases'] == 1
        assert {key for key, row in rows.items() if row['eligible']} == {'a', 'b'}
        assert all(not rows[key]['eligible'] for key in ('c', 'd', 'e', 'legacy'))


def test_capacity_excludes_risk_controlled_closed_and_current_case(database):
    with database() as db:
        assigned(db, 'active')
        assigned(db, 'controlled', controlled=True)
        assigned(db, 'closed', closed=True)
        db.commit()
        assert assignment.active_counts(db) == {'a': 1}
        assert assignment.active_counts(db, 'active') == {}
        snapshot = assignment.validate_assignment(db, db.get(Case, 'active'), 'a', 'Facilities')
        assert snapshot['active_cases'] == 0


def test_approval_rechecks_capacity_and_availability(database):
    with database() as db:
        case = db.get(Case, 'new')
        recommendation = assignment.recommend(db, case, 'Facilities')
        officer_id = recommendation['recommended_officer_id']
        db.get(OfficerProfile, officer_id).available = False
        db.commit()
        with pytest.raises(HTTPException, match='unavailable'):
            assignment.validate_assignment(db, case, officer_id, 'Facilities')
        with pytest.raises(HTTPException, match='capacity'):
            assignment.validate_assignment(db, case, 'e', 'Facilities')
        with pytest.raises(HTTPException, match='department'):
            assignment.validate_assignment(db, case, 'c', 'Facilities')


def test_no_capacity_requests_manager_and_no_consent_skips_ai(database, monkeypatch):
    monkeypatch.setattr(ai, 'generate', lambda *args, **kwargs: pytest.fail('AI must not receive a report without consent.'))
    with database() as db:
        case = db.get(Case, 'new')
        assert assignment.recommend(db, case)['source'] == 'manual_required'
        for profile in db.query(OfficerProfile):
            profile.available = False
        db.commit()
        result = assignment.recommend(db, case, 'Facilities')
        assert result['needs_manager'] is True
        assert result['recommended_officer_id'] == ''


def test_ai_department_validation_and_failure_preserve_manual_route(database, monkeypatch):
    monkeypatch.setattr(ai, 'capabilities', lambda: {'text': True})
    monkeypatch.setattr(ai, 'generate', lambda *args, **kwargs: json.dumps({'department': 'Facilities', 'reason': 'The report describes a water leak.'}))
    with database() as db:
        case = db.get(Case, 'new')
        case.data = new_case({**REPORT, 'consent': True})
        assert assignment.recommend(db, case)['department'] == 'Facilities'
        monkeypatch.setattr(ai, 'generate', lambda *args, **kwargs: json.dumps({'department': 'Invented', 'reason': 'Unverified'}))
        result = assignment.recommend(db, case)
        assert result['source'] == 'manual_required'
        assert result['department'] == ''
        assert result['recommended_officer_id'] == ''


def test_legacy_manual_assignment_and_invalid_department(database):
    with database() as db:
        case = db.get(Case, 'new')
        assert assignment.validate_assignment(db, case, 'legacy')['department'] == ''
        with pytest.raises(HTTPException):
            assignment.validate_assignment(db, case, 'legacy', 'Facilities')
        with pytest.raises(HTTPException):
            assignment.recommend(db, case, 'Unknown')


def test_simultaneous_approvals_cannot_exceed_capacity(database):
    with database() as db:
        db.get(OfficerProfile, 'a').capacity = 1
        db.add(Case(id='second', reference='SECOND', tracking_hash='unused', data=new_case(REPORT)))
        db.commit()

    ready = Barrier(2)

    def approve(case_id):
        with database() as db:
            case = db.get(Case, case_id)
            ready.wait(timeout=5)
            try:
                assignment.validate_assignment(db, case, 'a', 'Facilities')
            except HTTPException:
                return False
            data = copy.deepcopy(case.data)
            data['officer_id'] = 'a'
            data['approvals']['triage'] = {'at': 1}
            case.data = data
            db.commit()
            return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(approve, ['new', 'second']))
    assert sorted(results) == [False, True]


def test_demo_profiles_are_additive_and_repeatable(database):
    with database() as db:
        accounts = configure_demo_accounts(db)
        configure_demo_officers(db, accounts['officer'])
        db.commit()
        count = db.query(OfficerProfile).count()
        primary = db.get(OfficerProfile, accounts['officer'].id)
        primary.available = False
        db.commit()
        configure_demo_officers(db, accounts['officer'])
        db.commit()
        assert db.query(OfficerProfile).count() == count
        assert not primary.available
        assert primary.demo


@pytest.fixture
def api_system(tmp_path, monkeypatch):
    monkeypatch.setenv('EMAIL_MODE', 'capture')
    monkeypatch.setenv('UPLOAD_DIR', str(tmp_path/'uploads'))
    app = create_app(f'sqlite:///{tmp_path}/api.db', worker=False)
    with app.state.db() as db:
        for name, role in [('handler', 'handler'), ('manager', 'manager'), ('officer', 'officer')]:
            db.add(User(id=name, name=name, role=role, email=name+'@example.test', password=hash_password('test-password')))
        db.add(OfficerProfile(user_id='officer', department='Facilities', available=True, capacity=2))
        db.add(Case(id='case', reference='CASE', tracking_hash='unused', data=new_case(REPORT)))
        db.commit()
    with TestClient(app, headers={'x-safe-spot': '1'}) as client:
        yield app, client


def sign_in(client, name):
    response = client.post('/api/auth/login', json={'email': name+'@example.test', 'password': 'test-password'})
    assert response.status_code == 200


def test_recommendation_api_enforces_role_version_and_records_snapshot(api_system):
    app, client = api_system
    url = '/api/cases/case/assignment-recommendation'
    payload = {'version': 1, 'department': 'Facilities'}
    assert client.post(url, json=payload).status_code == 401
    sign_in(client, 'officer')
    assert client.post(url, json=payload).status_code == 403
    sign_in(client, 'handler')
    assert client.post(url, json={**payload, 'version': 99}).status_code == 409
    response = client.post(url, json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['recommendation']['recommended_officer_id'] == 'officer'
    assert result['case']['assignment_recommendation'] == result['recommendation']
    assert result['case']['history'][0]['action'] == 'Assignment recommendation prepared'
    assert result['case']['history'][0]['user_id'] == 'handler'
    sign_in(client, 'manager')
    assert client.post(url, json={**payload, 'version': result['case']['version']}).status_code == 200


def test_approved_assignment_records_capacity_reason_and_recommendation(api_system):
    app, client = api_system
    sign_in(client, 'handler')
    prepared = client.post('/api/cases/case/assignment-recommendation',
                           json={'version': 1, 'department': 'Facilities'}).json()
    response = client.post('/api/cases/case/triage', json={
        'version': prepared['case']['version'], 'department': 'Facilities', 'officer_id': 'officer',
        'category': 'Hazard', 'priority': 'Urgent', 'reason': 'The officer has available capacity.', 'approve': True})
    assert response.status_code == 200, response.text
    case = response.json()
    snapshot = case['approvals']['triage']['snapshot']
    assert snapshot['capacity_check']['capacity'] == 2
    assert snapshot['capacity_check']['active_cases'] == 0
    assert snapshot['reason'] == 'The officer has available capacity.'
    assert snapshot['recommendation'] == prepared['recommendation']
    assert case['history'][0]['detail'] == snapshot['reason']


@pytest.mark.parametrize(('field', 'value', 'department', 'message'), [
    ('available', False, 'Facilities', 'unavailable'),
    ('capacity', 0, 'Facilities', 'capacity'),
    ('available', True, 'Security', 'department'),
])
def test_assignment_api_rejects_invalid_officer_without_approval(api_system, field, value, department, message):
    app, client = api_system
    sign_in(client, 'handler')
    with app.state.db() as db:
        setattr(db.get(OfficerProfile, 'officer'), field, value)
        db.commit()
    response = client.post('/api/cases/case/triage', json={
        'version': 1, 'department': department, 'officer_id': 'officer', 'category': 'Hazard',
        'priority': 'Urgent', 'reason': 'The officer will inspect the report.', 'approve': True})
    assert response.status_code == 409, response.text
    assert message in response.json()['detail']
    with app.state.db() as db:
        assert not db.get(Case, 'case').data['approvals']


def test_capacity_routes_require_manager(api_system):
    app, client = api_system
    url = '/api/manager/capacity'
    payload = {'version': 1, 'department': 'Facilities', 'available': False, 'capacity': 4}
    assert client.get(url).status_code == 401
    assert client.post(url+'/officer', json=payload).status_code == 401
    for role in ('handler', 'officer'):
        sign_in(client, role)
        assert client.get(url).status_code == 403
        assert client.post(url+'/officer', json=payload).status_code == 403


def test_manager_changes_capacity_with_history_and_stale_version_check(api_system):
    app, client = api_system
    sign_in(client, 'manager')
    row = client.get('/api/manager/capacity').json()['officers'][0]
    assert row['version'] == 1
    payload = {'version': row['version'], 'department': 'Security', 'available': False, 'capacity': 5}
    response = client.post('/api/manager/capacity/officer', json=payload)
    assert response.status_code == 200, response.text
    changed = response.json()['officers'][0]
    assert changed['department'] == 'Security'
    assert changed['available'] is False
    assert changed['capacity'] == 5
    assert changed['version'] == 2
    assert changed['modified_by'] == 'manager'
    assert changed['modified_at'] > 0
    assert client.post('/api/manager/capacity/officer', json=payload).status_code == 409
    with app.state.db() as db:
        history = db.query(CapacityChange).all()
        assert len(history) == 1
        assert history[0].data['before']['department'] == 'Facilities'
        assert history[0].data['after']['department'] == 'Security'


def test_manager_can_configure_missing_profile_and_zero_capacity(api_system):
    app, client = api_system
    with app.state.db() as db:
        db.delete(db.get(OfficerProfile, 'officer'))
        db.commit()
    sign_in(client, 'manager')
    row = client.get('/api/manager/capacity').json()['officers'][0]
    assert row['version'] == 0
    assert row['department'] == ''
    payload = {'version': 0, 'department': 'Facilities', 'available': True, 'capacity': 0}
    response = client.post('/api/manager/capacity/officer', json=payload)
    assert response.status_code == 200, response.text
    assert response.json()['officers'][0]['capacity'] == 0
    assert response.json()['officers'][0]['version'] == 1
    assert client.post('/api/manager/capacity/handler', json=payload).status_code == 404


@pytest.mark.parametrize('invalid', [{'capacity': -1}, {'capacity': 51}, {'capacity': True},
                                    {'capacity': 1.5}, {'available': 'yes'}, {'department': 'Unknown'}])
def test_capacity_input_rejects_invalid_values(api_system, invalid):
    app, client = api_system
    sign_in(client, 'manager')
    payload = {'version': 1, 'department': 'Facilities', 'available': True, 'capacity': 5, **invalid}
    assert client.post('/api/manager/capacity/officer', json=payload).status_code == 422


def test_capacity_change_invalidates_assignment_approval_version(database):
    with database() as db:
        db.add(User(id='manager', name='Manager', email='manager@example.test', role='manager', password='unused'))
        db.commit()
    with database() as first, database() as second:
        old = first.get(OfficerProfile, 'a')
        assignment.validate_assignment(second, second.get(Case, 'new'), 'a', 'Facilities')
        second.commit()
        from sqlalchemy.orm.exc import StaleDataError
        with pytest.raises(StaleDataError):
            assignment.update_profile(first, 'a', 'Facilities', False, 2, old.version, actor=first.get(User, 'manager'))
