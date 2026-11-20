import json
import time

import pytest

from app import ai
from app.database import Case
from test_workflow import REPORT, login, system


def sample(reference):
    return {'findings': [{'kind': 'attention', 'title': 'Review the wet floor',
                         'finding': 'A report describes water at the east entrance.',
                         'action': 'Check the current condition with the assigned officer.',
                         'uncertainty': 'The current condition needs staff confirmation.',
                         'references': [reference]}]}


def test_overview_limits_evidence_and_maps_references(system, monkeypatch):
    app, client = system
    login(client, 'manager')
    included = client.post('/api/reports', json={**REPORT, 'consent': True, 'name': 'Private name', 'email': 'private@example.test'}).json()
    client.post('/api/reports', json={**REPORT, 'description': 'Private report without AI consent.'})
    old = client.post('/api/reports', json={**REPORT, 'consent': True}).json()
    with app.state.db() as db:
        db.get(Case, old['id']).created = time.time()-40*86400
        db.commit()
    captured = {}

    def model(task, evidence, **kwargs):
        captured.update(evidence)
        return json.dumps(sample(included['reference']))

    monkeypatch.setattr(ai, 'generate', model)
    response = client.post('/api/manager/overview', json={'days': 30})
    assert response.status_code == 200
    data = response.json()
    assert data['total'] == 2 and data['included'] == 1 and data['excluded'] == 1
    assert data['findings'][0]['cases'] == [{'id': included['id'], 'reference': included['reference']}]
    evidence = json.dumps(captured)
    assert 'Private name' not in evidence and 'private@example.test' not in evidence
    assert 'Private report' not in evidence and old['reference'] not in evidence
    assert captured['reports'][0]['assignment_approved'] is False
    case = client.get('/api/cases/'+included['id']).json()
    assert case['approvals'] == {} and case['status'] == 'Needs review'


def test_overview_permissions_period_and_empty_state(system, monkeypatch):
    _, client = system
    monkeypatch.setattr(ai, 'generate', lambda *args, **kwargs: pytest.fail('No model call is expected.'))
    assert client.post('/api/manager/overview', json={'days': 30}).status_code == 401
    for user in ['handler', 'officer']:
        login(client, user)
        assert client.post('/api/manager/overview', json={'days': 30}).status_code == 403
    login(client, 'manager')
    assert client.post('/api/manager/overview', json={'days': 365}).status_code == 422
    assert client.post('/api/manager/overview', json={'days': 7}).json()['total'] == 0
    client.post('/api/reports', json=REPORT)
    data = client.post('/api/manager/overview', json={'days': 7}).json()
    assert data['findings'] == [] and data['excluded'] == 1


@pytest.mark.parametrize('output', [json.dumps(sample('UNKNOWN')), '{}', 'not JSON', json.dumps({'findings': [sample('UNKNOWN')['findings'][0]]*4})])
def test_overview_rejects_invalid_model_output(system, monkeypatch, output):
    _, client = system
    login(client, 'manager')
    client.post('/api/reports', json={**REPORT, 'consent': True})
    monkeypatch.setattr(ai, 'generate', lambda *args, **kwargs: output)
    response = client.post('/api/manager/overview', json={'days': 30})
    assert response.status_code == 503
    assert 'findings' not in response.json()
