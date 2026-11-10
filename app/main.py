import asyncio
import copy
import io
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app import ai, schemas
from app.database import Attachment, Case, Group, Job, Limit, Notification, Session, User, connect, uid
from app.domain import approval, audit, invalidate, new_case, require, riddor_details, serialize, status, targets
from app.security import digest, hash_password, verify_password
from app.worker import add_notification, scan_alerts, tick

log = logging.getLogger('safespot')
STATIC = Path(__file__).parent / 'static'


def create_app(database_url=None, worker=True):
    engine, factory = connect(database_url)
    uploads = Path(os.getenv('UPLOAD_DIR', '.local/uploads'))
    uploads.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app):
        stop = asyncio.Event()
        async def run_worker():
            while not stop.is_set():
                try:
                    await asyncio.to_thread(tick, factory)
                except Exception:
                    log.exception('Background processing failed.')
                try:
                    await asyncio.wait_for(stop.wait(), timeout=30)
                except TimeoutError:
                    pass
        task = asyncio.create_task(run_worker()) if worker and os.getenv('WORKER_ENABLED', 'true') == 'true' else None
        yield
        stop.set()
        if task:
            await task
        engine.dispose()

    app = FastAPI(title='Safe Spot', lifespan=lifespan)
    app.state.db = factory

    @app.middleware('http')
    async def boundary(request, call_next):
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            if request.headers.get('x-safe-spot') != '1':
                return JSONResponse({'detail': 'Refresh the page before you try again.'}, status_code=403)
            origin = request.headers.get('origin')
            allowed = os.getenv('PUBLIC_ORIGIN', 'http://127.0.0.1:8000').rstrip('/')
            if origin and origin != allowed:
                return JSONResponse({'detail': 'This origin is not allowed.'}, status_code=403)
            try:
                too_large = int(request.headers.get('content-length', '0')) > 6 * 1024 * 1024
            except ValueError:
                too_large = True
            if too_large:
                return JSONResponse({'detail': 'The request is too large.'}, status_code=413)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
        if request.url.path.startswith('/api'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(StaleDataError)
    async def stale_handler(request, exc):
        return JSONResponse({'detail': 'Another person changed this record. Reload it before saving.'}, status_code=409)

    @app.exception_handler(IntegrityError)
    async def conflict_handler(request, exc):
        return JSONResponse({'detail': 'The record changed. Refresh the page and try again.'}, status_code=409)

    def db_session():
        with factory() as db:
            yield db

    def current_user(request: Request, db=Depends(db_session)):
        value = request.cookies.get('safe_spot_session', '')
        session = db.get(Session, digest(value)) if value else None
        if not session or session.expires <= time.time():
            raise HTTPException(401, 'Sign in to continue.')
        user = db.get(User, session.user_id)
        if not user:
            raise HTTPException(401, 'Sign in to continue.')
        return user

    def role(user, *roles):
        require(user.role in roles, 'Your role cannot perform this action.', 403)

    def fetch_case(db, case_id, user, version=None):
        case = db.get(Case, case_id)
        require(case is not None, 'Case not found.', 404)
        if user.role == 'officer':
            require(case.data['officer_id'] == user.id and case.data['approvals'].get('triage'), 'Case not found.', 404)
        if version is not None:
            require(case.version == version, 'Another person changed this case. Reload it before saving.')
        return case

    def persist(db, case, data):
        case.data, case.updated = data, time.time()
        db.commit()
        return full_case(db, case)

    def full_case(db, case):
        photos = [{'id': a.id, 'name': a.name} for a in db.scalars(select(Attachment).where(Attachment.case_id == case.id))]
        return serialize(case, photos)

    def rate_limit(request, db, bucket, maximum):
        key = digest(bucket + ':' + (request.client.host if request.client else 'unknown'))
        now = time.time()
        limit = db.get(Limit, key)
        if not limit or limit.expires <= now:
            if limit:
                db.delete(limit)
                db.flush()
            db.add(Limit(key=key, count=1, expires=now+900))
        else:
            require(limit.count < maximum, 'Too many attempts. Try again in 15 minutes.', 429)
            db.execute(update(Limit).where(Limit.key == key).values(count=Limit.count+1))
        db.commit()

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'service': 'Safe Spot'}

    @app.get('/api/config')
    def config():
        return {'ai': ai.capabilities(), 'email_mode': os.getenv('EMAIL_MODE', 'capture'),
                'demo': True, 'storage': 'server', 'speech': 'not_connected'}

    @app.post('/api/auth/login')
    def login(payload: schemas.Login, request: Request, response: Response, db=Depends(db_session)):
        rate_limit(request, db, 'login', 20)
        user = db.scalar(select(User).where(User.email == payload.email.lower()))
        stored = user.password if user else hash_password('unknown-account')
        require(verify_password(payload.password, stored) and user, 'Email or password is incorrect.', 401)
        token = secrets.token_urlsafe(32)
        db.add(Session(token=digest(token), user_id=user.id, expires=time.time()+8*3600))
        db.execute(delete(Session).where(Session.expires < time.time()))
        db.commit()
        response.set_cookie('safe_spot_session', token, httponly=True, secure=os.getenv('COOKIE_SECURE') == 'true', samesite='strict', max_age=8*3600)
        return {'id': user.id, 'name': user.name, 'role': user.role}

    @app.post('/api/auth/logout')
    def logout(request: Request, response: Response, db=Depends(db_session)):
        token = request.cookies.get('safe_spot_session', '')
        db.execute(delete(Session).where(Session.token == digest(token)))
        db.commit()
        response.delete_cookie('safe_spot_session')
        return {'ok': True}

    @app.get('/api/auth/me')
    def me(user=Depends(current_user)):
        return {'id': user.id, 'name': user.name, 'role': user.role}

    @app.get('/api/staff')
    def staff(user=Depends(current_user), db=Depends(db_session)):
        return [{'id': u.id, 'name': u.name, 'role': u.role} for u in db.scalars(select(User))]

    @app.post('/api/report-assistance')
    def report_assistance(payload: schemas.ReportAssistance, request: Request, db=Depends(db_session)):
        import json
        rate_limit(request, db, 'assistance', 20)
        try:
            result = ai.generate('Extract only explicit report details. Return a JSON object with location, time, harm, and remains. Use an empty string for missing details. Do not infer a place, time, injury, or current condition.', {'description': payload.description})
            values = json.loads(result)
            require(isinstance(values, dict), 'AI returned invalid details. Complete the report yourself.', 503)
            details = {key: values.get(key, '') for key in ('location', 'time', 'harm', 'remains')}
            require(all(isinstance(v, str) and len(v) <= 2000 for v in details.values()), 'AI returned invalid details. Complete the report yourself.', 503)
        except Exception:
            raise HTTPException(503, 'AI assistance is unavailable. Complete the report yourself.')
        return {'details': details, 'requires_review': True}

    @app.post('/api/reports', status_code=201)
    def report(payload: schemas.Report, request: Request, db=Depends(db_session)):
        rate_limit(request, db, 'report', 30)
        token = secrets.token_urlsafe(32)
        data = new_case(payload.model_dump(exclude={'confirmed'}))
        reference = 'SS-' + secrets.token_hex(4).upper()
        case = Case(reference=reference, tracking_hash=digest(token), data=data)
        db.add(case)
        db.flush()
        if payload.consent:
            db.add(Job(id='triage:'+case.id, case_id=case.id, kind='triage'))
        if any(term in (payload.description+' '+payload.remains).lower() for term in ('fire', 'electric shock', 'unconscious', 'gas leak')):
            add_notification(db, 'urgent:'+case.id, 'Urgent review requested', f'{reference} contains an urgent indicator. A person must assess it.', [case.id])
        if payload.email:
            add_notification(db, 'receipt:'+case.id, f'Report received: {reference}', f'We received your report. Reference: {reference}. Keep your tracking code from the receipt screen.', [case.id], payload.email, 'receipt')
        db.commit()
        return {'reference': reference, 'tracking_token': token, 'id': case.id, 'status': 'Needs review'}

    @app.post('/api/tracking')
    def tracking(payload: schemas.Tracking, request: Request, db=Depends(db_session)):
        rate_limit(request, db, 'tracking', 60)
        case = db.scalar(select(Case).where(Case.reference == payload.reference.upper()))
        require(case and secrets.compare_digest(case.tracking_hash, digest(payload.token)), 'Report not found. Check the reference and tracking code.', 404)
        data = case.data
        return {'reference': case.reference, 'status': status(data), 'created': case.created,
                'reviewed': data['approvals'].get('triage', {}).get('at'), 'controlled': data['approvals'].get('field', {}).get('at'),
                'closed': data['approvals'].get('closure', {}).get('at'),
                'next_step': 'The case is closed.' if data['closed'] else 'Staff will review the outcome.' if data['approvals'].get('field') else 'The assigned officer will record action.' if data['approvals'].get('triage') else 'A case handler will review the report.'}

    @app.get('/api/cases')
    def cases(user=Depends(current_user), db=Depends(db_session)):
        records = list(db.scalars(select(Case).order_by(Case.created.desc())))
        if user.role == 'officer':
            records = [c for c in records if c.data['officer_id'] == user.id and c.data['approvals'].get('triage')]
        return [serialize(c) for c in records]

    @app.get('/api/cases/{case_id}')
    def detail(case_id: str, user=Depends(current_user), db=Depends(db_session)):
        return full_case(db, fetch_case(db, case_id, user))

    @app.post('/api/cases/{case_id}/triage')
    def triage(case_id: str, payload: schemas.Triage, user=Depends(current_user), db=Depends(db_session)):
        role(user, 'handler', 'manager')
        case = fetch_case(db, case_id, user, payload.version)
        officer = db.get(User, payload.officer_id)
        require(officer and officer.role == 'officer', 'Select a field officer.', 422)
        data = copy.deepcopy(case.data)
        invalidate(data, 'triage')
        for key in ('category', 'priority', 'officer_id'):
            data[key] = getattr(payload, key)
        if payload.approve:
            data['approvals']['triage'] = approval(user, {k: data[k] for k in ('category', 'priority', 'officer_id')})
        audit(data, user, 'Triage approved' if payload.approve else 'Triage draft saved', payload.reason)
        return persist(db, case, data)

    @app.post('/api/cases/{case_id}/findings')
    def findings(case_id: str, payload: schemas.Findings, user=Depends(current_user), db=Depends(db_session)):
        role(user, 'officer')
        case = fetch_case(db, case_id, user, payload.version)
        data = copy.deepcopy(case.data)
        require(data['approvals'].get('triage'), 'Approve the assignment before field work.')
        invalidate(data, 'field')
        data['findings'] = payload.model_dump(exclude={'version', 'approve'})
        if payload.approve:
            data['approvals']['field'] = approval(user, data['findings'])
        audit(data, user, 'Risk control approved' if payload.approve else 'Findings draft saved')
        return persist(db, case, data)

    @app.post('/api/cases/{case_id}/response')
    def response_draft(case_id: str, payload: schemas.Outcome, user=Depends(current_user), db=Depends(db_session)):
        role(user, 'handler', 'manager')
        case = fetch_case(db, case_id, user, payload.version)
        data = copy.deepcopy(case.data)
        invalidate(data, 'response')
        data['response'] = payload.text
        if payload.approve:
            require(data['approvals'].get('field'), 'Approve risk control before the outcome.')
            data['approvals']['response'] = approval(user, payload.text)
        audit(data, user, 'Exact response approved' if payload.approve else 'Response draft saved')
        return persist(db, case, data)

    @app.post('/api/cases/{case_id}/send')
    def send(case_id: str, payload: schemas.Revision, user=Depends(current_user), db=Depends(db_session)):
        role(user, 'handler', 'manager')
        case = fetch_case(db, case_id, user, payload.version)
        data = copy.deepcopy(case.data)
        approved = data['approvals'].get('response')
        require(data['approvals'].get('triage') and data['approvals'].get('field') and approved and approved['snapshot'] == data['response'], 'Approve the current response before recording it.')
        data['sent'] = {'at': time.time(), 'approval_at': approved['at'], 'text': data['response'], 'by': user.name}
        if data['report'].get('email'):
            add_notification(db, f'outcome:{case.id}:{approved["at"]}', f'Outcome for {case.reference}', data['response'], [case.id], data['report']['email'], 'outcome')
        audit(data, user, 'Outcome recorded', 'Delivery status is available in the outbox.')
        return persist(db, case, data)

    @app.post('/api/cases/{case_id}/close')
    def close(case_id: str, payload: schemas.Revision, user=Depends(current_user), db=Depends(db_session)):
        role(user, 'handler', 'manager')
        case = fetch_case(db, case_id, user, payload.version)
        data = copy.deepcopy(case.data)
        approved, sent = data['approvals'].get('response'), data.get('sent')
        require(data['approvals'].get('field') and approved and sent and sent['approval_at'] == approved['at'] and sent['text'] == data['response'], 'Record the approved outcome before closure.')
        data['closed'] = True
        data['approvals']['closure'] = approval(user, data['response'])
        audit(data, user, 'Closure approved')
        return persist(db, case, data)

    @app.post('/api/cases/{case_id}/reopen')
    def reopen(case_id: str, payload: schemas.Reopen, user=Depends(current_user), db=Depends(db_session)):
        role(user, 'handler', 'manager')
        case = fetch_case(db, case_id, user, payload.version)
        data = copy.deepcopy(case.data)
        invalidate(data, 'field')
        audit(data, user, 'Case reopened', payload.reason)
        return persist(db, case, data)

    @app.post('/api/cases/{case_id}/riddor')
    def riddor(case_id: str, payload: schemas.Riddor, user=Depends(current_user), db=Depends(db_session)):
        role(user, 'handler', 'manager')
        case = fetch_case(db, case_id, user, payload.version)
        if payload.kind not in ('none', 'unreviewed'):
            try:
                start = date.fromisoformat(payload.incident_date)
                require(start <= date.today(), 'The incident date cannot be in the future.', 422)
                for value in (payload.notified_date, payload.received_date):
                    if value:
                        require(start <= date.fromisoformat(value) <= date.today(), 'Check the notification and receipt dates.', 422)
            except ValueError:
                raise HTTPException(422, 'Enter valid dates for the reporting review.')
        data = copy.deepcopy(case.data)
        data['riddor'] = {**payload.model_dump(exclude={'version'}), 'by': user.name, 'at': time.time()}
        audit(data, user, 'RIDDOR review confirmed', payload.reason)
        return persist(db, case, data)

    @app.post('/api/cases/{case_id}/ai/retry')
    def ai_retry(case_id: str, payload: schemas.Revision, user=Depends(current_user), db=Depends(db_session)):
        role(user, 'handler', 'manager')
        case = fetch_case(db, case_id, user, payload.version)
        require(case.data['report']['consent'], 'The reporter did not consent to AI assistance.', 403)
        require(ai.capabilities()['decision'], 'The decision model is not connected.', 503)
        job = db.get(Job, 'triage:'+case.id)
        if not job:
            job = Job(id='triage:'+case.id, case_id=case.id, kind='triage')
            db.add(job)
        require(job.state != 'running', 'AI processing is already running.')
        job.state, job.attempts, job.next_at = 'pending', 0, time.time()
        data = copy.deepcopy(case.data)
        data['ai'] = {'status': 'pending'}
        return persist(db, case, data)

    @app.post('/api/cases/{case_id}/ai/response')
    def ai_response(case_id: str, payload: schemas.Revision, user=Depends(current_user), db=Depends(db_session)):
        role(user, 'handler', 'manager')
        case = fetch_case(db, case_id, user, payload.version)
        require(case.data['report']['consent'], 'AI assistance was not permitted for this report.', 403)
        require(case.data['approvals'].get('field'), 'Approve field findings before drafting an outcome.')
        try:
            text = ai.generate('Draft an outcome response for the reporter. Do not include staff names.', {'reference': case.reference, 'location': case.data['report']['location'], 'findings': case.data['findings']})
        except Exception:
            raise HTTPException(503, 'The text model is unavailable. Write the response manually.')
        data = copy.deepcopy(case.data)
        invalidate(data, 'response')
        data['response'] = text
        audit(data, user, 'AI response draft prepared', 'The draft requires exact-content approval.')
        return persist(db, case, data)

    @app.get('/api/groups')
    def groups(user=Depends(current_user), db=Depends(db_session)):
        role(user, 'handler', 'manager')
        return [{'id': g.id, 'version': g.version, **g.data} for g in db.scalars(select(Group))]

    @app.post('/api/groups', status_code=201)
    def group_review(payload: schemas.GroupReview, user=Depends(current_user), db=Depends(db_session)):
        role(user, 'handler', 'manager')
        ids = sorted(set(payload.case_ids))
        require(len(ids) >= 2, 'Select at least two different reports.', 422)
        for i in ids:
            fetch_case(db, i, user)
        group = Group(data={'case_ids': ids, 'relationship': payload.relationship, 'reason': payload.reason, 'by': user.name, 'at': time.time()})
        db.add(group)
        for i in ids:
            case = db.get(Case, i)
            data = copy.deepcopy(case.data)
            audit(data, user, 'Incident relationship confirmed', payload.relationship + ': ' + payload.reason)
            case.data = data
        db.commit()
        return {'id': group.id, **group.data}

    @app.delete('/api/groups/{group_id}')
    def remove_group(group_id: str, user=Depends(current_user), db=Depends(db_session)):
        role(user, 'handler', 'manager')
        group = db.get(Group, group_id)
        require(group, 'Group not found.', 404)
        for i in group.data['case_ids']:
            case = db.get(Case, i)
            if case:
                data = copy.deepcopy(case.data)
                audit(data, user, 'Incident group removed', group_id)
                case.data = data
        db.delete(group)
        db.commit()
        return {'ok': True}

    @app.get('/api/notifications')
    def notifications(user=Depends(current_user), db=Depends(db_session)):
        role(user, 'handler', 'manager')
        return [{'id': n.id, 'created': n.created, 'state': n.state, **n.data} for n in db.scalars(select(Notification).order_by(Notification.created.desc()).limit(100))]

    @app.post('/api/notifications/scan')
    def scan(user=Depends(current_user), db=Depends(db_session)):
        role(user, 'manager')
        scan_alerts(db)
        db.commit()
        return {'ok': True}

    @app.post('/api/notifications/{note_id}/acknowledge')
    def acknowledge(note_id: str, user=Depends(current_user), db=Depends(db_session)):
        role(user, 'manager')
        note = db.get(Notification, note_id)
        require(note, 'Notification not found.', 404)
        data = copy.deepcopy(note.data)
        data['acknowledged'] = {'by': user.name, 'at': time.time()}
        note.data = data
        db.commit()
        return {'ok': True}

    @app.post('/api/manager/summary')
    def summary(user=Depends(current_user), db=Depends(db_session)):
        role(user, 'manager')
        counts = {}
        for c in db.scalars(select(Case)):
            counts[status(c.data)] = counts.get(status(c.data), 0) + 1
        try:
            text = ai.generate('Draft a manager summary from these counts. Do not infer causes or future incidents.', counts)
        except Exception:
            raise HTTPException(503, 'The text model is unavailable. Dashboard counts remain available.')
        return {'text': text, 'label': 'AI draft · Review before action', 'counts': counts}

    @app.post('/api/cases/{case_id}/attachments', status_code=201)
    async def upload(case_id: str, request: Request, file: UploadFile = File(...), db=Depends(db_session)):
        case = db.get(Case, case_id)
        require(case, 'Case not found.', 404)
        tracking = request.headers.get('x-tracking-token', '')
        reporter = tracking and secrets.compare_digest(case.tracking_hash, digest(tracking))
        if reporter:
            require(not case.data['approvals'].get('triage') and time.time()-case.created < 3600, 'Staff have started review. Ask staff to add further evidence.', 403)
            actor = type('ReporterActor', (), {'id': 'reporter', 'name': 'Reporter'})()
        else:
            actor = current_user(request, db)
            fetch_case(db, case_id, actor)
        existing = list(db.scalars(select(Attachment).where(Attachment.case_id == case_id)))
        require(len(existing) < 6, 'This case already has six images.', 422)
        content = await file.read(5*1024*1024+1)
        require(len(content) <= 5*1024*1024, 'Choose an image under 5 MB.', 413)
        try:
            image = Image.open(io.BytesIO(content))
            require(image.format in ('JPEG', 'PNG', 'WEBP') and image.width*image.height <= 20_000_000, 'Choose a smaller JPEG, PNG, or WebP image.', 422)
            image.load()
            output = io.BytesIO()
            image.convert('RGB').save(output, format='JPEG', quality=85)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise HTTPException(422, 'The image could not be read.')
        photo = Attachment(id=uid(), case_id=case.id, name=Path(file.filename or 'photo').name[:140], mime='image/jpeg')
        path = uploads / photo.id
        path.write_bytes(output.getvalue())
        db.add(photo)
        data = copy.deepcopy(case.data)
        if not reporter:
            invalidate(data, 'field')
        audit(data, actor, 'Evidence image added', photo.name)
        try:
            result = persist(db, case, data)
            return {'id': photo.id, 'name': photo.name} if reporter else result
        except Exception:
            path.unlink(missing_ok=True)
            raise

    @app.get('/api/attachments/{photo_id}')
    def image(photo_id: str, user=Depends(current_user), db=Depends(db_session)):
        photo = db.get(Attachment, photo_id)
        require(photo, 'Image not found.', 404)
        fetch_case(db, photo.case_id, user)
        return FileResponse(uploads / photo.id, media_type='image/jpeg')

    @app.get('/')
    def home():
        return FileResponse(STATIC / 'index.html')

    app.mount('/static', StaticFiles(directory=STATIC), name='static')
    return app


app = create_app()
