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

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app import ai, assistant, assignment, photo_analysis, schemas
from app.storage import create_storage
from app.database import Attachment, Case, Group, Job, Limit, Notification, Session, User, connect, uid
from app.domain import approval, audit, invalidate, new_case, require, riddor_details, serialize, status, targets
from app.security import digest, hash_password, normalize_reference, report_reference, verify_password
from app import manager_overview
from app.worker import add_notification, scan_alerts, tick

log = logging.getLogger('safespot')
STATIC = Path(__file__).parent / 'static'


def create_app(database_url=None, worker=True):
    engine, factory = connect(database_url)
    evidence_storage = create_storage()

    @asynccontextmanager
    async def lifespan(app):
        if ai.capabilities()['text'] and os.getenv('TEXT_AI_AUTH_MODE') == 'entra':
            try:
                await asyncio.wait_for(asyncio.to_thread(ai.auth_headers), timeout=10)
            except Exception:
                log.warning('AI authentication preparation failed. Requests can try again.')
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
        evidence_storage.close()
        engine.dispose()

    app = FastAPI(title='Safe Spot', lifespan=lifespan)
    app.state.db = factory
    app.state.storage = evidence_storage

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
        elif request.url.path == '/' or request.url.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'no-cache'
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
                'demo': True, 'storage': 'server', 'speech': 'browser',
                'departments': list(assignment.DEPARTMENTS)}

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
    def report_assistance(payload: schemas.ReportAssistance, request: Request, response: Response, db=Depends(db_session)):
        started = time.perf_counter()
        rate_limit(request, db, 'assistance', 20)
        prepared = time.perf_counter()
        try:
            details = ai.extract_details(payload.description)
        except Exception:
            log.warning('Report assistance failed after %.3f seconds.', time.perf_counter()-started)
            raise HTTPException(503, 'AI assistance is unavailable. Complete the report yourself.')
        finished = time.perf_counter()
        response.headers['Server-Timing'] = f'prepare;dur={(prepared-started)*1000:.1f}, ai;dur={(finished-prepared)*1000:.1f}'
        log.info('Report assistance completed: prepare=%.3fs ai=%.3fs.', prepared-started, finished-prepared)
        return {'details': details, 'requires_review': True}

    @app.post('/api/report-photo-analysis')
    async def analyze_report_photo(request: Request, file: UploadFile = File(...),
                                   consent: bool = Form(False), description: str = Form(''), db=Depends(db_session)):
        require(consent, 'Approve AI photo analysis before continuing.', 403)
        require(len(description) <= 8000, 'The description is too long.', 422)
        rate_limit(request, db, 'photo_analysis', 10)
        try:
            content = await file.read(photo_analysis.MAX_BYTES + 1)
            return await asyncio.to_thread(photo_analysis.analyze, content, consent=True, description=description)
        except photo_analysis.PhotoInvalid as exc:
            raise HTTPException(exc.status_code, str(exc))
        except ai.AIUnavailable:
            raise HTTPException(503, 'Photo analysis is unavailable. You can describe the photo yourself.')
        finally:
            await file.close()

    @app.post('/api/reports', status_code=201)
    def report(payload: schemas.Report, request: Request, db=Depends(db_session)):
        rate_limit(request, db, 'report', 30)
        data = new_case(payload.model_dump(exclude={'confirmed'}))
        reference = report_reference()
        case = Case(reference=reference, tracking_hash=digest(reference), data=data)
        db.add(case)
        db.flush()
        add_notification(db, 'new-report:'+case.id, f'New report: {reference}',
                         f'Review report {reference} at {payload.location}.', [case.id], kind='handler')
        if payload.consent:
            db.add(Job(id='triage:'+case.id, case_id=case.id, kind='triage'))
        if any(term in (payload.description+' '+payload.remains).lower() for term in ('fire', 'electric shock', 'unconscious', 'gas leak')):
            add_notification(db, 'urgent:'+case.id, 'Urgent review requested', f'{reference} contains an urgent indicator. A person must assess it.', [case.id])
        if payload.email:
            origin = os.getenv('PUBLIC_ORIGIN', 'http://127.0.0.1:8000').rstrip('/')
            add_notification(db, 'receipt:'+case.id, f'Report received: {reference}', f'We received your report. Reference: {reference}. Use this reference to check progress at {origin}.', [case.id], payload.email, 'receipt')
        db.commit()
        return {'reference': reference, 'id': case.id, 'status': 'Needs review'}

    @app.post('/api/tracking')
    def tracking(payload: schemas.Tracking, request: Request, db=Depends(db_session)):
        rate_limit(request, db, 'tracking', 60)
        case = db.scalar(select(Case).where(Case.reference == normalize_reference(payload.reference)))
        require(case, 'Report not found. Check the reference.', 404)
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

    @app.post('/api/cases/{case_id}/assignment-recommendation')
    def recommend_assignment(case_id: str, payload: schemas.AssignmentRequest,
                             user=Depends(current_user), db=Depends(db_session)):
        role(user, 'handler', 'manager')
        case = fetch_case(db, case_id, user, payload.version)
        recommendation = assignment.recommend(db, case, payload.department)
        data = copy.deepcopy(case.data)
        data['assignment_recommendation'] = recommendation
        audit(data, user, 'Assignment recommendation prepared', recommendation['reason'])
        return {'case': persist(db, case, data), 'recommendation': recommendation}

    @app.post('/api/cases/{case_id}/triage')
    def triage(case_id: str, payload: schemas.Triage, user=Depends(current_user), db=Depends(db_session)):
        role(user, 'handler', 'manager')
        case = fetch_case(db, case_id, user, payload.version)
        officer = db.get(User, payload.officer_id)
        require(officer and officer.role == 'officer', 'Select a field officer.', 422)
        assignment_snapshot = assignment.validate_assignment(db, case, officer.id, payload.department) if payload.approve else None
        data = copy.deepcopy(case.data)
        invalidate(data, 'triage')
        for key in ('category', 'priority', 'officer_id'):
            data[key] = getattr(payload, key)
        data['department'] = assignment_snapshot['department'] if assignment_snapshot else payload.department
        if payload.approve:
            data['assignment'] = assignment_snapshot
            data['approvals']['triage'] = approval(user, {
                **{k: data[k] for k in ('category', 'priority', 'officer_id', 'department')},
                'capacity_check': assignment_snapshot, 'reason': payload.reason,
                'recommendation': data.get('assignment_recommendation'),
            })
            approved_at = data['approvals']['triage']['at']
            add_notification(db, f'assignment:{case.id}:{approved_at}', f'Case assigned: {case.reference}',
                             f'You have an approved assignment for {case.reference} at {data["report"]["location"]}. '
                             'Open Safe Spot to review the case.', [case.id], kind='officer',
                             staff_user_id=officer.id, approval_stage='triage', approval_at=approved_at)
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
            approved_at = data['approvals']['field']['at']
            add_notification(db, f'field-review:{case.id}:{approved_at}', f'Risk control ready for review: {case.reference}',
                             f'The field officer approved risk control for {case.reference}. Review the outcome response.',
                             [case.id], kind='handler', approval_stage='field', approval_at=approved_at)
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
        require(ai.capabilities()['decision'], 'AI is not connected.', 503)
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

    def assistant_review(case, review_id):
        review = next((item for item in case.data.get('assistant', {}).get('reviews', [])
                       if item['id'] == review_id), None)
        require(review, 'Review not found.', 404)
        require(review['fingerprint'] == assistant.fingerprint(assistant.evidence(case)),
                'The case evidence changed. Prepare a new AI review.')
        return review

    def record_assistant(data, user, review_id, action, detail, **fields):
        audit(data, user, action, detail)
        data['history'][0]['assistant'] = {'review_id': review_id, **fields}

    @app.post('/api/cases/{case_id}/assistant/review')
    def prepare_assistant(case_id: str, payload: schemas.Revision, user=Depends(current_user), db=Depends(db_session)):
        role(user, 'handler', 'manager')
        case = fetch_case(db, case_id, user, payload.version)
        require(case.data['report']['consent'], 'The reporter did not consent to AI assistance.', 403)
        require(ai.capabilities()['text'], 'AI is not connected. You can write a draft manually.', 503)
        source = assistant.evidence(case)
        possible = assistant.candidates(case, db.scalars(select(Case).order_by(Case.created.desc()).limit(300)))
        sources = [assistant.evidence(item) for item in possible]
        try:
            result = assistant.generate_review(source, sources)
        except Exception:
            raise HTTPException(503, 'AI could not prepare the review. Try again or continue manually.')
        review = {
            'id': uid(), 'at': time.time(), 'by': user.name, 'user_id': user.id,
            'model': os.getenv('TEXT_AI_MODEL', ''), 'result': result, 'source': source,
            'fingerprint': assistant.fingerprint(source),
            'candidates': [{**item, 'case_id': record.id, 'fingerprint': assistant.fingerprint(item)}
                           for item, record in zip(sources, possible)],
            'decisions': {}, 'relationships': {},
        }
        data = copy.deepcopy(case.data)
        data.setdefault('assistant', {}).setdefault('reviews', []).append(review)
        record_assistant(data, user, review['id'], 'AI review prepared', 'Suggestions are ready for review.')
        return persist(db, case, data)

    @app.post('/api/cases/{case_id}/assistant/decision')
    def assistant_decision(case_id: str, payload: schemas.AssistantDecision, user=Depends(current_user), db=Depends(db_session)):
        role(user, 'handler', 'manager')
        case = fetch_case(db, case_id, user, payload.version)
        review = assistant_review(case, payload.review_id)
        require(not review['decisions'].get(payload.field), 'This suggestion already has a recorded decision.')
        original = review['result'][payload.field]['value']
        value = payload.value if payload.action == 'change' else original
        if payload.action != 'dismiss':
            require(bool(value.strip()), 'Enter a value for the suggestion.', 422)
            if payload.field in ai.TRIAGE_CHOICES:
                require(value in ai.TRIAGE_CHOICES[payload.field] and value != 'Cannot determine',
                        'Select a category or priority before accepting this suggestion.', 422)
        data = copy.deepcopy(case.data)
        saved = next(item for item in data['assistant']['reviews'] if item['id'] == payload.review_id)
        decision = {'action': payload.action, 'value': value, 'original': original,
                    'by': user.name, 'user_id': user.id, 'at': time.time()}
        saved['decisions'][payload.field] = decision
        if payload.field == 'summary' and payload.action != 'dismiss':
            data['assistant'].setdefault('notes', []).append({**decision, 'review_id': review['id']})
        record_assistant(data, user, review['id'], 'AI suggestion reviewed',
                         f'{payload.field}: {payload.action}. {value}',
                         field=payload.field, decision=decision)
        return persist(db, case, data)

    @app.post('/api/cases/{case_id}/assistant/draft')
    def assistant_draft(case_id: str, payload: schemas.AssistantDraft, user=Depends(current_user), db=Depends(db_session)):
        role(user, 'handler', 'manager')
        case = fetch_case(db, case_id, user, payload.version)
        if payload.review_id:
            assistant_review(case, payload.review_id)
        data = copy.deepcopy(case.data)
        data.setdefault('assistant', {})['draft'] = {
            'text': payload.text, 'review_id': payload.review_id,
            'by': user.name, 'user_id': user.id, 'at': time.time(),
        }
        record_assistant(data, user, payload.review_id, 'Follow-up draft saved', payload.text)
        return persist(db, case, data)

    @app.post('/api/cases/{case_id}/assistant/relationship')
    def assistant_relationship(case_id: str, payload: schemas.AssistantRelationship, user=Depends(current_user), db=Depends(db_session)):
        role(user, 'handler', 'manager')
        case = fetch_case(db, case_id, user, payload.version)
        review = assistant_review(case, payload.review_id)
        proposal = next((item for item in review['result']['related'] if item['reference'] == payload.reference), None)
        require(proposal, 'Related report not found in this review.', 404)
        require(not review['relationships'].get(payload.reference), 'This relationship already has a recorded decision.')
        source = next(item for item in review['candidates'] if item['reference'] == payload.reference)
        other = fetch_case(db, source['case_id'], user)
        require(source['fingerprint'] == assistant.fingerprint(assistant.evidence(other)),
                'The related case changed. Prepare a new AI review.')
        data = copy.deepcopy(case.data)
        saved = next(item for item in data['assistant']['reviews'] if item['id'] == payload.review_id)
        decision = {'action': payload.action, 'relationship': payload.relationship, 'reason': payload.reason,
                    'by': user.name, 'user_id': user.id, 'at': time.time()}
        if payload.action == 'confirm':
            ids = sorted([case.id, other.id])
            duplicate = any(set(ids).issubset(g.data['case_ids']) and g.data['relationship'] == payload.relationship
                            for g in db.scalars(select(Group)))
            require(not duplicate, 'This relationship is already recorded.')
            group = Group(id=uid(), data={
                'case_ids': ids, 'relationship': payload.relationship, 'reason': payload.reason,
                'by': user.name, 'user_id': user.id, 'at': decision['at'], 'review_id': review['id'],
            })
            db.add(group)
            decision['group_id'] = group.id
            other_data = copy.deepcopy(other.data)
            record_assistant(other_data, user, review['id'], 'Incident relationship confirmed',
                             f'{case.reference}: {payload.relationship}. {payload.reason}')
            other.data, other.updated = other_data, time.time()
        saved['relationships'][payload.reference] = decision
        record_assistant(data, user, review['id'], 'AI relationship reviewed',
                         f'{payload.reference}: {payload.action}. {payload.reason}', decision=decision)
        return persist(db, case, data)

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

    @app.get('/api/manager/capacity')
    def capacity_list(user=Depends(current_user), db=Depends(db_session)):
        role(user, 'manager')
        return {'officers': assignment.list_profiles(db), 'departments': list(assignment.DEPARTMENTS), 'basis': assignment.BASIS}

    @app.post('/api/manager/capacity/{officer_id}')
    def capacity_update(officer_id: str, payload: schemas.OfficerCapacity,
                        user=Depends(current_user), db=Depends(db_session)):
        role(user, 'manager')
        assignment.update_profile(db, officer_id, **payload.model_dump(), actor=user)
        db.commit()
        return {'officers': assignment.list_profiles(db), 'departments': list(assignment.DEPARTMENTS), 'basis': assignment.BASIS}

    @app.post('/api/manager/overview')
    def overview(payload: manager_overview.OverviewRequest, request: Request,
                 user=Depends(current_user), db=Depends(db_session)):
        role(user, 'manager')
        rate_limit(request, db, 'manager-overview', 20)
        records = list(db.scalars(select(Case).where(Case.created >= time.time()-payload.days*86400)))
        try:
            return manager_overview.generate(records, payload.days)
        except Exception:
            raise HTTPException(503, 'AI overview is unavailable. Use the dashboard charts or try again.')

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
        reference = request.headers.get('x-report-reference', '')
        tracking = request.headers.get('x-tracking-token', '')
        if reference or tracking:
            rate_limit(request, db, 'reporter_upload', 20)
        reporter = (reference and secrets.compare_digest(digest(case.reference), digest(normalize_reference(reference)))) or (
            tracking and secrets.compare_digest(case.tracking_hash, digest(tracking)))
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
        try:
            await asyncio.to_thread(evidence_storage.put, photo.id, output.getvalue())
        except Exception:
            raise HTTPException(503, 'Image storage is unavailable. Try the upload again.')
        db.add(photo)
        data = copy.deepcopy(case.data)
        if not reporter:
            invalidate(data, 'field')
        audit(data, actor, 'Evidence image added', photo.name)
        try:
            result = persist(db, case, data)
            return {'id': photo.id, 'name': photo.name} if reporter else result
        except Exception:
            try:
                await asyncio.to_thread(evidence_storage.delete, photo.id)
            except Exception:
                log.exception('Evidence cleanup failed.')
            raise

    @app.get('/api/attachments/{photo_id}')
    def image(photo_id: str, user=Depends(current_user), db=Depends(db_session)):
        photo = db.get(Attachment, photo_id)
        require(photo, 'Image not found.', 404)
        fetch_case(db, photo.case_id, user)
        try:
            content = evidence_storage.get(photo.id)
        except FileNotFoundError:
            raise HTTPException(404, 'Image not found.')
        except Exception:
            raise HTTPException(503, 'Image storage is unavailable. Try again later.')
        return Response(content, media_type='image/jpeg')

    @app.get('/')
    def home():
        return FileResponse(STATIC / 'index.html', headers={'Cache-Control': 'no-cache'})

    app.mount('/static', StaticFiles(directory=STATIC), name='static')
    return app


app = create_app()
