import json
import time
import uuid
from types import SimpleNamespace

import pytest
import httpx

from app import mail
from app.database import Case, Limit, Notification, User, connect
from app.worker import add_notification, deliver


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


def test_manager_alerts_wait_for_accounts_and_use_current_roles(email_system, monkeypatch):
    factory, sent = email_system
    monkeypatch.setenv('MANAGER_EMAIL', 'old-setting@example.test')
    with factory() as db:
        add_notification(db, 'manager-test', 'Manager test', 'A test message.')
        db.commit()
        note = db.query(Notification).filter_by(key='manager-test').one()
        note_id = note.id
    deliver(factory)
    with factory() as db:
        assert db.get(Notification, note_id).state == 'recorded'
        assert sent == []
        former = User(name='Former manager', email='former@example.test', role='manager', password='unused')
        db.add(former)
        db.flush()
        add_notification(db, 'another-manager-test', 'Another test', 'A test message.')
        former.role = 'handler'
        db.add_all([
            User(name='First manager', email='first@example.test', role='manager', password='unused'),
            User(name='Second manager', email='second@example.test', role='manager', password='unused'),
            User(name='Officer', email='officer@example.test', role='officer', password='unused'),
        ])
        db.commit()
    deliver(factory)
    with factory() as db:
        for note in db.query(Notification).all():
            assert note.state == 'sent'
            assert note.data['recipients'] == ['first@example.test', 'second@example.test']
            assert note.data['recipient'] == 'first@example.test, second@example.test'
    assert len(sent) == 2


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
    assert 'A test message.' in payload['htmlbody']
    assert '<html lang="en">' in payload['htmlbody']
    assert payload['client_reference'] == note.id
    assert payload['track_opens'] is False and payload['track_clicks'] is False
    monkeypatch.setenv('ZEPTOMAIL_API_KEY', 'Zoho-enczapikey test-token')
    note.data['recipients'] = ['first@example.test', 'second@example.test']
    mail.send_zeptomail(note)
    assert requests[-1].headers['Authorization'] == 'Zoho-enczapikey test-token'
    assert json.loads(requests[-1].content)['to'] == [
        {'email_address': {'address': 'first@example.test'}},
        {'email_address': {'address': 'second@example.test'}},
    ]
    monkeypatch.setenv('ZEPTOMAIL_API_URL', 'http://api.zeptomail.eu/v1.1/email')
    with pytest.raises(ValueError):
        mail.send_zeptomail(note)
    assert len(requests) == 2


@pytest.mark.parametrize('kind,role', [('receipt', 'Reporter'), ('outcome', 'Reporter'),
    ('handler', 'Case handler'), ('officer', 'Field officer'), ('manager', 'Manager')])
def test_demo_email_routes_to_one_inbox_and_identifies_role(monkeypatch, kind, role):
    monkeypatch.setenv('DEMO_EMAIL_TO', 'functionzy@gmail.com')
    monkeypatch.setenv('PUBLIC_ORIGIN', 'https://safespot.example.test')
    note = SimpleNamespace(data={'kind': kind, 'subject': 'Report received: SS-DEMO0009',
        'body': 'Water remains near the entrance. <script>alert(1)</script>',
        'recipient': 'original@example.test', 'recipients': ['original@example.test']})
    message = mail.prepare_message(note)
    assert message['recipients'] == ['functionzy@gmail.com']
    assert message['subject'] == f'[Safe Spot demo | {role}] Report received: SS-DEMO0009'
    assert note.data['delivery_recipients'] == ['functionzy@gmail.com']
    assert note.data['recipients'] == ['original@example.test']
    assert 'original@example.test' in message['text']
    assert '<script>' not in message['html']
    assert '&lt;script&gt;' in message['html']
    assert 'href="https://safespot.example.test"' in message['html']
    assert mail.prepare_message(note) == message
    monkeypatch.delenv('DEMO_EMAIL_TO')
    assert mail.prepare_message(note)['recipients'] == ['original@example.test']


def test_demo_email_provider_payload_has_only_the_demo_recipient(monkeypatch):
    monkeypatch.setenv('DEMO_EMAIL_TO', 'functionzy@gmail.com')
    monkeypatch.setenv('ZEPTOMAIL_API_URL', 'https://api.zeptomail.eu/v1.1/email')
    monkeypatch.setenv('ZEPTOMAIL_FROM', 'notifications@example.test')
    monkeypatch.setenv('ZEPTOMAIL_API_KEY', 'test-token')
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'message': 'OK', 'request_id': 'demo-accepted'})
    client_class = httpx.Client
    monkeypatch.setattr(mail.httpx, 'Client', lambda **kwargs: client_class(
        transport=httpx.MockTransport(respond), **kwargs))
    note = SimpleNamespace(id='demo-note', data={'kind': 'manager', 'subject': 'Daily summary',
        'body': 'Two cases remain open.', 'recipients': ['one@example.test', 'two@example.test']})
    assert mail.send_zeptomail(note) == 'demo-accepted'
    assert requests[0]['to'] == [{'email_address': {'address': 'functionzy@gmail.com'}}]
    assert requests[0]['subject'] == '[Safe Spot demo | Manager] Daily summary'
    assert 'Two cases remain open.' in requests[0]['htmlbody']
    monkeypatch.setenv('DEMO_EMAIL_TO', 'invalid\naddress')
    with pytest.raises(ValueError):
        mail.send_zeptomail(note)
    assert len(requests) == 1
