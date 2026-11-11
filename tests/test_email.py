import json
import time
import uuid
from types import SimpleNamespace

import pytest
import httpx

from app import mail
from app.database import Case, Limit, Notification, connect
from app.worker import deliver


@pytest.fixture
def email_system(tmp_path, monkeypatch):
    engine, factory = connect(f'sqlite:///{tmp_path}/email.db')
    monkeypatch.setenv('EMAIL_MODE', 'zeptomail')
    sent = []
    def send(note):
        sent.append(note.id)
        return 'provider-request-id'

    monkeypatch.setattr(mail, 'send_zeptomail', send)
    yield factory, sent
    engine.dispose()


def add_message(factory, **values):
    with factory() as db:
        note = Notification(key=uuid.uuid4().hex, data={
            'subject': 'Safe Spot test', 'body': 'A test message.',
            'recipient': 'recipient@example.test', 'case_ids': [], 'kind': 'receipt',
        }, **values)
        db.add(note)
        db.commit()
        return note.id


def test_zeptomail_acceptance_does_not_repeat_delivery(email_system):
    factory, sent = email_system
    note_id = add_message(factory)
    deliver(factory)
    with factory() as db:
        assert db.get(Notification, note_id).state == 'sent'
        assert db.get(Notification, note_id).data['provider_request_id'] == 'provider-request-id'
    deliver(factory)
    deliver(factory)
    with factory() as db:
        assert db.get(Notification, note_id).state == 'sent'
    assert sent == [note_id]


def test_delivery_keeps_captured_mail_and_cancels_unapproved_outcomes(email_system):
    factory, sent = email_system
    captured = add_message(factory, state='captured')
    with factory() as db:
        case = Case(reference='TEST', tracking_hash='test', data={'approvals': {}})
        db.add(case)
        db.flush()
        note = Notification(key=f'outcome:{case.id}:1', data={
            'subject': 'Outcome', 'body': 'An old draft.', 'recipient': 'recipient@example.test',
            'case_ids': [case.id], 'kind': 'outcome',
        })
        db.add(note)
        db.commit()
        cancelled = note.id
    deliver(factory)
    with factory() as db:
        assert db.get(Notification, captured).state == 'captured'
        assert db.get(Notification, cancelled).state == 'cancelled'
    assert sent == []


def test_provider_throttle_pauses_the_queue(email_system, monkeypatch):
    factory, sent = email_system
    note_id = add_message(factory)
    next_id = add_message(factory)

    def throttled(note):
        sent.append(note.id)
        response = httpx.Response(429, headers={'Retry-After': '600'},
                                  request=httpx.Request('POST', 'https://api.zeptomail.com/v1.1/email'))
        response.raise_for_status()

    monkeypatch.setattr(mail, 'send_zeptomail', throttled)
    deliver(factory)
    deliver(factory)
    with factory() as db:
        note = db.get(Notification, note_id)
        assert note.state == 'recorded'
        assert note.data['next_attempt'] > time.time() + 590
        assert db.get(Notification, next_id).state == 'recorded'
        db.get(Limit, 'email:zeptomail:retry').expires = 0
        note.data = {**note.data, 'next_attempt': 0}
        db.commit()
    assert sent == [note_id]
    monkeypatch.setattr(mail, 'send_zeptomail', lambda note: 'accepted')
    deliver(factory)
    with factory() as db:
        assert db.get(Notification, note_id).state == 'sent'
        assert db.get(Notification, next_id).state == 'sent'


@pytest.mark.parametrize('status,expected', [(None, 'delivery_unknown'), (401, 'failed'), (500, 'delivery_unknown')])
def test_failed_or_uncertain_send_is_not_repeated(email_system, monkeypatch, status, expected):
    factory, sent = email_system
    note_id = add_message(factory)

    def failed(note):
        sent.append(note.id)
        if status is None:
            raise httpx.ReadTimeout('The connection timed out.')
        httpx.Response(status, request=httpx.Request('POST', 'https://api.zeptomail.com/v1.1/email')).raise_for_status()

    monkeypatch.setattr(mail, 'send_zeptomail', failed)
    deliver(factory)
    deliver(factory)
    with factory() as db:
        assert db.get(Notification, note_id).state == expected
    assert sent == [note_id]


def test_zeptomail_request_uses_the_configured_sender_and_token(monkeypatch):
    monkeypatch.setenv('ZEPTOMAIL_API_URL', 'https://api.zeptomail.eu/v1.1/email')
    monkeypatch.setenv('ZEPTOMAIL_FROM', 'notifications@example.test')
    monkeypatch.setenv('ZEPTOMAIL_API_KEY', 'test-token')
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'message': 'OK', 'request_id': 'request-123'})

    client_class = httpx.Client
    monkeypatch.setattr(mail.httpx, 'Client', lambda **kwargs: client_class(
        transport=httpx.MockTransport(respond), **kwargs))
    note = SimpleNamespace(id=uuid.uuid4().hex, data={
        'recipient': 'recipient@example.test', 'subject': 'A test', 'body': 'A test message.',
    })
    assert mail.send_zeptomail(note) == 'request-123'
    request = requests[0]
    payload = json.loads(request.content)
    assert str(request.url) == 'https://api.zeptomail.eu/v1.1/email'
    assert request.headers['Authorization'] == 'Zoho-enczapikey test-token'
    assert payload['from'] == {'address': 'notifications@example.test', 'name': 'Safe Spot'}
    assert payload['to'] == [{'email_address': {'address': 'recipient@example.test'}}]
    assert payload['textbody'] == 'A test message.'
    assert payload['client_reference'] == note.id
    assert payload['track_opens'] is False and payload['track_clicks'] is False
    monkeypatch.setenv('ZEPTOMAIL_API_KEY', 'Zoho-enczapikey test-token')
    mail.send_zeptomail(note)
    assert requests[-1].headers['Authorization'] == 'Zoho-enczapikey test-token'
    monkeypatch.setenv('ZEPTOMAIL_API_URL', 'http://api.zeptomail.eu/v1.1/email')
    with pytest.raises(ValueError):
        mail.send_zeptomail(note)
    assert len(requests) == 2
