import copy
import json

import pytest
from sqlalchemy import select

from app import ai, assistant
from app.database import Group, Notification
from test_workflow import REPORT, assign, login, system


def mutate(client, case, endpoint, **fields):
    return client.post('/api/cases/'+case['id']+'/'+endpoint, json={'version': case['version'], **fields})


def result(reference=None):
    def suggestion(value):
        return {'value': value, 'reason': 'The report describes a wet floor.', 'sources': ['description', 'remains']}
    return {
        'summary': suggestion('Water is on the floor near the entrance.'),
        'category': suggestion('Hazard'), 'priority': suggestion('Urgent'),
        'missing': ['The current control needs confirmation.'],
        'follow_up': 'Is the floor still wet? What action has been taken?',
        'related': [{'reference': reference, 'relationship': 'same_event',
                     'reason': 'The reports describe water at the same entrance.',
                     'uncertainty': 'Staff must check the incident time.'}] if reference else [],
    }


def create_consented(client):
    receipt = client.post('/api/reports', json={**REPORT, 'consent': True}).json()
    return client.get('/api/cases/'+receipt['id']).json()


def connect_model(monkeypatch, reference=None):
    monkeypatch.setattr(ai, 'capabilities', lambda: {'text': True, 'decision': True})
    monkeypatch.setattr(ai, 'generate', lambda *args, **kwargs: json.dumps(result(reference)))


def test_staff_review_saves_evidence_decisions_drafts_and_links(system, monkeypatch):
    app, client = system
    login(client, 'handler')
    other = create_consented(client)
    case = create_consented(client)
    connect_model(monkeypatch, other['reference'])
    case = mutate(client, case, 'assistant/review').json()
    review = case['assistant']['reviews'][-1]
    assert review['source']['description'] == REPORT['description']
    assert 'email' not in review['source'] and 'age_range' not in review['source']
    stale_version = copy.deepcopy(case)
    case = mutate(client, case, 'assistant/decision', review_id=review['id'], field='category', action='accept').json()
    assert case['category'] == '' and case['approvals'] == {}
    assert case['history'][0]['user_id'] == 'handler'
    assert mutate(client, stale_version, 'assistant/decision', review_id=review['id'], field='priority', action='accept').status_code == 409
    case = mutate(client, case, 'assistant/decision', review_id=review['id'], field='summary', action='change', value='Staff reviewed the report of water.').json()
    assert case['assistant']['notes'][0]['original'] == result()['summary']['value']
    case = mutate(client, case, 'assistant/draft', review_id=review['id'], text='Please confirm the current floor condition.').json()
    saved = client.get('/api/cases/'+case['id']).json()
    assert saved['assistant']['draft']['text'] == 'Please confirm the current floor condition.'
    assert saved['assistant']['draft']['user_id'] == 'handler'
    case = mutate(client, case, 'assistant/relationship', review_id=review['id'], reference=other['reference'],
                  action='confirm', relationship='recurring', reason='Staff confirmed different incident dates.').json()
    assert case['status'] == 'Needs review' and case['approvals'] == {} and case['sent'] is None
    with app.state.db() as db:
        group = db.scalar(select(Group))
        assert group.data['relationship'] == 'recurring' and group.data['review_id'] == review['id']
        notes = list(db.scalars(select(Notification)))
        assert len(notes) == 2 and all(note.key.startswith('new-report:') for note in notes)
    assert client.get('/api/cases/'+other['id']).json()['history'][0]['user_id'] == 'handler'


def test_consent_roles_and_changed_evidence_block_ai_decisions(system, monkeypatch):
    _, client = system
    connect_model(monkeypatch)
    login(client, 'handler')
    receipt = client.post('/api/reports', json=REPORT).json()
    declined = client.get('/api/cases/'+receipt['id']).json()
    assert mutate(client, declined, 'assistant/review').status_code == 403
    case = create_consented(client)
    case = mutate(client, case, 'assistant/review').json()
    review = case['assistant']['reviews'][-1]
    case = assign(client, case)
    assert mutate(client, case, 'assistant/decision', review_id=review['id'], field='priority', action='accept').status_code == 409
    assert mutate(client, case, 'assistant/draft', review_id=review['id'], text='Old suggestion text.').status_code == 409
    login(client, 'officer')
    assert mutate(client, case, 'assistant/draft', text='Officer attempt.').status_code == 403
    assert mutate(client, case, 'assistant/review').status_code == 403
    login(client, 'manager')
    saved = mutate(client, case, 'assistant/draft', text='Please provide the inspection record.').json()
    assert saved['status'] == 'Assigned' and saved['approvals'] == case['approvals']
    assert saved['assistant']['draft']['user_id'] == 'manager'


def test_ai_failure_and_unknown_references_do_not_save_review(system, monkeypatch):
    _, client = system
    login(client, 'handler')
    case = create_consented(client)
    connect_model(monkeypatch, 'SS-UNKNOWN')
    assert mutate(client, case, 'assistant/review').status_code == 503
    unchanged = client.get('/api/cases/'+case['id']).json()
    assert unchanged['version'] == case['version'] and 'assistant' not in unchanged
    connect_model(monkeypatch)
    case = mutate(client, case, 'assistant/review').json()
    review = case['assistant']['reviews'][-1]
    assert mutate(client, case, 'assistant/decision', review_id=review['id'], field='priority', action='change', value='Low').status_code == 422
    assert mutate(client, case, 'assistant/relationship', review_id=review['id'], reference='SS-UNKNOWN', action='confirm', relationship='same_event', reason='Unknown report.').status_code == 404
    case = mutate(client, case, 'assistant/decision', review_id=review['id'], field='priority', action='dismiss').json()
    assert mutate(client, case, 'assistant/decision', review_id=review['id'], field='priority', action='accept').status_code == 409


def test_review_schema_rejects_invalid_sources_and_preserves_uncertainty(monkeypatch):
    captured = []
    response = result()
    def generate(task, evidence, schema):
        captured.append((evidence, schema))
        return json.dumps(response)
    monkeypatch.setattr(ai, 'generate', generate)
    valid = assistant.generate_review({'description': 'Water on the floor.'}, [])
    assert valid['missing'] == response['missing']
    assert captured[0][1]['additionalProperties'] is False
    response['category']['sources'] = ['invented_record']
    with pytest.raises(ai.AIUnavailable):
        assistant.generate_review({}, [])
