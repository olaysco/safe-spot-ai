import copy
import os
import smtplib
import time
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

import httpx
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from app import ai, mail
from app.database import Case, Group, Job, Limit, Notification, User
from app.domain import targets


def manager_recipients(db):
    return sorted({email.lower() for email in db.scalars(select(User.email).where(User.role == 'manager'))})


def add_notification(db, key, subject, body, case_ids=None, recipient=None, kind='manager'):
    if db.scalar(select(Notification).where(Notification.key == key)):
        return
    recipients = manager_recipients(db) if kind == 'manager' else [recipient]
    db.add(Notification(key=key, data={'subject': subject, 'body': body,
        'recipient': ', '.join(recipients) if recipients else 'No manager account', 'recipients': recipients,
        'case_ids': case_ids or [], 'kind': kind, 'acknowledged': None}))


def scan_alerts(db):
    now = time.time()
    cases = {c.id: c for c in db.scalars(select(Case))}
    for group in db.scalars(select(Group)):
        g = group.data
        if g['relationship'] != 'recurring':
            continue
        recent = [cases[i] for i in g['case_ids'] if i in cases and cases[i].created >= now - 7 * 86400]
        overdue = [c for c in recent if not c.data['approvals'].get('field') and targets(c)['control_due'] < now]
        if len(recent) >= 3 and overdue:
            refs = ', '.join(c.reference for c in overdue)
            add_notification(db, f'recurrence:{group.id}:{int(now // 86400)}', 'Repeated incidents need review',
                f'{len(recent)} confirmed related incidents were received in seven days. Risk control is overdue for {refs}. Review the case records before action.',
                [c.id for c in overdue])
    for case in cases.values():
        if not case.data['approvals'].get('field') and targets(case)['control_due'] < now:
            add_notification(db, f'overdue:{case.id}:{int(now // 86400)}', f'Risk control overdue: {case.reference}',
                f'Risk control is not yet approved for {case.reference}. Review the case and its internal deadline.', [case.id])
    open_cases = [c for c in cases.values() if not c.data['closed']]
    add_notification(db, f'daily:{int(now // 86400)}', 'Safe Spot daily summary',
        f'{len(open_cases)} cases remain open. {sum(not c.data["approvals"].get("field") for c in open_cases)} have no approved risk control. Review the dashboard for details.', [c.id for c in open_cases])


def process_ai(factory):
    now = time.time()
    with factory() as db:
        job = db.scalar(select(Job).where(Job.kind == 'triage', Job.next_at <= now,
            or_(Job.state == 'pending', (Job.state == 'running') & (Job.lease_until < now))).order_by(Job.next_at))
        if not job:
            return
        claimed = db.execute(update(Job).where(Job.id == job.id, Job.state == job.state, Job.lease_until == job.lease_until)
            .values(state='running', lease_until=now + 120, attempts=job.attempts + 1)).rowcount
        job_id, case_id = job.id, job.case_id
        db.commit()
        if not claimed:
            return
    with factory() as db:
        case = db.get(Case, case_id)
        if not case or not case.data['report'].get('consent'):
            db.get(Job, job_id).state = 'done'
            db.commit()
            return
        report = copy.deepcopy(case.data['report'])
    try:
        result = ai.classify(report)
        failed = False
    except ai.AIUnavailable as exc:
        result, failed = {'status': 'unavailable', 'note': str(exc)}, False
    except Exception:
        result, failed = {'status': 'failed', 'note': 'AI processing failed. Manual review remains available.'}, True
    with factory() as db:
        job, case = db.get(Job, job_id), db.get(Case, case_id)
        job.state = 'pending' if failed and job.attempts < 3 else 'failed' if failed else 'done'
        job.next_at = time.time() + 60 * job.attempts
        job.error = 'AI request failed.' if failed else ''
        if case:
            data = copy.deepcopy(case.data)
            data['ai'] = result
            case.data, case.updated = data, time.time()
        db.commit()


def retry_time(response):
    value = response.headers.get('Retry-After', '')
    try:
        return time.time() + max(300, int(value))
    except ValueError:
        try:
            return max(time.time() + 300, parsedate_to_datetime(value).timestamp())
        except (TypeError, ValueError, OverflowError):
            return time.time() + 300


def deliver(factory):
    mode = os.getenv('EMAIL_MODE', 'capture')
    with factory() as db:
        if mode == 'zeptomail':
            for note in db.scalars(select(Notification).where(Notification.state == 'sending',
                    Notification.data['provider'].as_string() == 'zeptomail')):
                if note.data.get('submitted_at', note.created) < time.time() - 900:
                    note.state = 'delivery_unknown'
            db.commit()
            pause = db.get(Limit, 'email:zeptomail:retry')
            if pause and pause.expires > time.time():
                return
        notes = list(db.scalars(select(Notification).where(Notification.state == 'recorded')
                               .order_by(Notification.created)))
        submitted = 0
        for note in notes:
            if note.data.get('next_attempt', 0) > time.time():
                continue
            ids = note.data.get('case_ids', [])
            if note.key.startswith(('overdue:', 'recurrence:')) and ids:
                cases = [db.get(Case, i) for i in ids]
                if all(not c or c.data['approvals'].get('field') for c in cases):
                    note.state = 'cancelled'
                    continue
            if note.data.get('kind') == 'outcome' and ids:
                case = db.get(Case, ids[0])
                approved = case.data['approvals'].get('response') if case else None
                if not approved or note.key != f'outcome:{case.id}:{approved["at"]}':
                    note.state = 'cancelled'
                    continue
            if note.data.get('kind') == 'manager':
                recipients = manager_recipients(db)
                note.data = {**note.data, 'recipients': recipients,
                             'recipient': ', '.join(recipients) if recipients else 'No manager account'}
                if not recipients:
                    continue
            if mode == 'capture':
                note.state = 'captured'
                continue
            if mode == 'zeptomail':
                if submitted >= 5:
                    break
                note.state = 'sending'
                note.data = {**note.data, 'provider': 'zeptomail', 'submitted_at': time.time()}
                db.commit()
                submitted += 1
                try:
                    request_id = mail.send_zeptomail(note)
                    note.state = 'sent'
                    note.data = {**note.data, 'provider_request_id': request_id}
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    if status == 429:
                        note.state = 'recorded'
                        next_attempt = retry_time(exc.response)
                        note.data = {**note.data, 'next_attempt': next_attempt}
                        db.merge(Limit(key='email:zeptomail:retry', count=1, expires=next_attempt))
                        db.commit()
                        break
                    elif 400 <= status < 500 and status not in (408, 409):
                        note.state = 'failed'
                    else:
                        note.state = 'delivery_unknown'
                except Exception:
                    # Do not repeat a request when acceptance is unknown.
                    note.state = 'delivery_unknown'
                db.commit()
                continue
            if mode != 'smtp':
                raise ValueError('The email mode is not supported.')
            note.state = 'sending'
            db.commit()
            msg = EmailMessage()
            msg['From'] = os.getenv('SMTP_FROM', 'safespot@example.test')
            msg['To'] = note.data['recipient']
            msg['Subject'] = note.data['subject']
            msg['Message-ID'] = f'<{note.id}@safespot.local>'
            msg.set_content(note.data['body'])
            try:
                with smtplib.SMTP(os.getenv('SMTP_HOST', '127.0.0.1'), int(os.getenv('SMTP_PORT', '1025')), timeout=15) as smtp:
                    if os.getenv('SMTP_TLS') == 'true':
                        smtp.starttls()
                    if os.getenv('SMTP_USERNAME'):
                        smtp.login(os.environ['SMTP_USERNAME'], os.environ['SMTP_PASSWORD'])
                    smtp.send_message(msg)
                note.state = 'sent'
            except Exception:
                note.state = 'delivery_unknown'
            db.commit()
        db.commit()


def tick(factory):
    try:
        process_ai(factory)
        with factory() as db:
            scan_alerts(db)
            db.commit()
        deliver(factory)
    except (IntegrityError, StaleDataError):
        # The next worker cycle retries concurrent changes.
        pass


def run_once():
    from sqlalchemy import text
    from app.database import connect
    engine, factory = connect()
    try:
        with engine.connect() as connection:
            locked = engine.dialect.name == 'postgresql'
            if locked and not connection.scalar(text('SELECT pg_try_advisory_lock(73401928)')):
                return
            try:
                tick(factory)
            finally:
                if locked:
                    connection.execute(text('SELECT pg_advisory_unlock(73401928)'))
    finally:
        engine.dispose()


if __name__ == '__main__':
    run_once()
