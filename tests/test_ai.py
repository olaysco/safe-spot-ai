import json
from types import SimpleNamespace

import httpx
import pytest

from app import ai


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setenv('TEXT_AI_BASE_URL', 'https://safe-spot.services.ai.azure.com/openai/v1')
    monkeypatch.setenv('TEXT_AI_MODEL', 'gpt-5.4-mini')
    monkeypatch.setenv('TEXT_AI_AUTH_MODE', 'api_key')
    monkeypatch.setenv('TEXT_AI_API_KEY', 'test-key')
    requests = []
    reply = {'choices': [{'finish_reason': 'stop', 'message': {'content': 'A draft for staff review.'}}]}

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=reply)

    client = httpx.Client
    monkeypatch.setattr(ai.httpx, 'Client', lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs))
    return requests, reply


def test_extract_details_uses_azure_identity_and_strict_schema(model, monkeypatch):
    requests, reply = model
    monkeypatch.setenv('TEXT_AI_AUTH_MODE', 'entra')
    scopes = []

    def get_token(scope):
        scopes.append(scope)
        return SimpleNamespace(token='identity-token')

    monkeypatch.setattr(ai, 'azure_credential', lambda: SimpleNamespace(get_token=get_token))
    details = {'location': 'East entrance', 'time': '', 'harm': '', 'remains': ''}
    reply['choices'][0]['message']['content'] = json.dumps(details)
    assert ai.extract_details('There is water at the east entrance.') == details
    request = requests[0]
    body = json.loads(request.content)
    assert str(request.url) == 'https://safe-spot.services.ai.azure.com/openai/v1/chat/completions'
    assert request.headers['Authorization'] == 'Bearer identity-token'
    assert scopes == ['https://cognitiveservices.azure.com/.default']
    assert body['model'] == 'gpt-5.4-mini'
    assert body['max_completion_tokens'] == 2048 and body['reasoning_effort'] == 'none'
    assert 'temperature' not in body and 'max_tokens' not in body
    schema = body['response_format']['json_schema']
    assert schema['strict'] is True
    assert set(schema['schema']['required']) == set(details)
    assert schema['schema']['additionalProperties'] is False


def test_triage_omits_contact_and_age_and_validates_choices(model):
    requests, reply = model
    report = {'description': 'The floor is wet.', 'location': 'East entrance', 'time': '09:15',
              'harm': 'No injury', 'remains': 'Still wet', 'age_range': 'Under 18',
              'name': 'Test reporter', 'email': 'reporter@example.test'}
    reply['choices'][0]['message']['content'] = '{"category":"Hazard","priority":"Urgent"}'
    result = ai.classify(report)
    assert result['suggestions'] == {'category': 'Hazard', 'priority': 'Urgent'}
    assert result['model'] == 'gpt-5.4-mini'
    request = requests[0]
    assert request.headers['api-key'] == 'test-key'
    evidence = json.loads(json.loads(request.content)['messages'][1]['content'].split('\nEvidence: ')[1])
    assert set(evidence['report']) == {'description', 'location', 'time', 'harm', 'remains'}
    reply['choices'][0]['message']['content'] = '{"category":"Hazard","priority":"Low"}'
    with pytest.raises(ai.AIUnavailable):
        ai.classify(report)


@pytest.mark.parametrize('change', ['length', 'refusal', 'empty'])
def test_incomplete_or_refused_responses_are_rejected(model, change):
    _, reply = model
    if change == 'length':
        reply['choices'][0]['finish_reason'] = 'length'
    elif change == 'refusal':
        reply['choices'][0]['message']['refusal'] = 'Request refused.'
    else:
        reply['choices'] = []
    with pytest.raises(ai.AIUnavailable):
        ai.generate('Draft a summary.', {'open_cases': 2})


def test_missing_credentials_disable_ai(model, monkeypatch):
    requests, _ = model
    monkeypatch.delenv('TEXT_AI_API_KEY')
    assert ai.capabilities() == {'text': False, 'decision': False, 'speech': False}
    with pytest.raises(ai.AIUnavailable):
        ai.extract_details('Water covers the floor.')
    assert requests == []
