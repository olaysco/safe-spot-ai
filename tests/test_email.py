import time
import uuid
from types import SimpleNamespace

import pytest
from azure.core.exceptions import HttpResponseError

from app import mail
from app.database import Case, Limit, Notification, connect
from app.worker import deliver


@pytest.fixture
def email_system(tmp_path, monkeypatch):
    engine, factory = connect(f'sqlite:///{tmp_path}/email.db')
    monkeypatch.setenv('EMAIL_MODE', 'azure')
    sent = []
    monkeypatch.setattr(mail, 'send_azure', lambda note: sent.append(note.id))
    monkeypatch.setattr(mail, 'azure_status', lambda note: 'Succeeded')
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


def test_azure_delivery_checks_status_without_resending(email_system):
    factory, sent = email_system
    note_id = add_message(factory)
    deliver(factory)
    with factory() as db:
        assert db.get(Notification, note_id).state == 'sending'
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


def test_hourly_limit_and_provider_throttle_keep_mail_queued(email_system, monkeypatch):
    factory, sent = email_system
    note_id = add_message(factory)
    with factory() as db:
        db.add(Limit(key='email:azure:send', count=10, expires=time.time()+3600))
        db.commit()
    deliver(factory)
    assert sent == []
    with factory() as db:
        assert db.get(Notification, note_id).state == 'recorded'
        db.get(Limit, 'email:azure:send').count = 0
        db.commit()

    def throttled(note):
        sent.append(note.id)
        error = HttpResponseError('The email service is busy.')
        error.status_code = 429
        raise error

    monkeypatch.setattr(mail, 'send_azure', throttled)
    deliver(factory)
    deliver(factory)
    with factory() as db:
        note = db.get(Notification, note_id)
        assert note.state == 'recorded'
        assert note.data['next_attempt'] > time.time()
    assert sent == [note_id]


def test_uncertain_send_uses_operation_status_before_another_send(email_system, monkeypatch):
    factory, sent = email_system
    note_id = add_message(factory)

    def disconnected(note):
        sent.append(note.id)
        raise TimeoutError('The connection timed out.')

    monkeypatch.setattr(mail, 'send_azure', disconnected)
    deliver(factory)
    deliver(factory)
    with factory() as db:
        assert db.get(Notification, note_id).state == 'sent'
    assert sent == [note_id]


def test_azure_adapter_uses_one_operation_id_and_defers_status_checks(monkeypatch):
    calls, requests = [], []
    monkeypatch.setenv('AZURE_EMAIL_ENDPOINT', 'https://safespot.communication.azure.com')
    monkeypatch.setenv('AZURE_EMAIL_FROM', 'DoNotReply@example.test')

    def begin_send(message, **kwargs):
        calls.append((message, kwargs))
        return SimpleNamespace(result=lambda: {'status': 'Running'})

    def send_request(request):
        requests.append(request)
        return SimpleNamespace(status_code=200, json=lambda: {'status': 'Succeeded'})

    monkeypatch.setattr(mail, 'azure_client', lambda: SimpleNamespace(begin_send=begin_send, send_request=send_request))
    note = SimpleNamespace(id=uuid.uuid4().hex, data={
        'recipient': 'recipient@example.test', 'subject': 'A test', 'body': 'A test message.',
    })
    mail.send_azure(note)
    assert calls[0][0]['senderAddress'] == 'DoNotReply@example.test'
    assert calls[0][0]['recipients'] == {'to': [{'address': 'recipient@example.test'}]}
    assert calls[0][1] == {'operation_id': str(uuid.UUID(note.id)), 'polling': False}
    assert mail.azure_status(note) == 'Succeeded'
    assert str(uuid.UUID(note.id)) in requests[0].url
