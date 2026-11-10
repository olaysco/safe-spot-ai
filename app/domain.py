import copy
import time
from datetime import date, timedelta
from fastapi import HTTPException

TARGETS = {'Immediate': (0, 0), 'Urgent': (1, 4), 'Routine': (4, 24)}


def new_case(report):
    return {
        'report': report, 'category': '', 'priority': '', 'officer_id': '',
        'findings': {}, 'response': '', 'closed': False, 'approvals': {},
        'sent': None, 'history': [], 'ai': {'status': 'pending' if report.get('consent') else 'declined'},
        'riddor': {'kind': 'unreviewed'},
    }


def status(data):
    if data['closed']:
        return 'Closed'
    if data['approvals'].get('field'):
        return 'Risk controlled'
    if data['approvals'].get('triage'):
        return 'Assigned'
    return 'Needs review'


def audit(data, actor, action, detail=''):
    data['history'].insert(0, {'by': actor.name, 'user_id': actor.id, 'at': time.time(), 'action': action, 'detail': detail})


def invalidate(data, stage):
    keys = {'triage': ['triage', 'field', 'response', 'closure'], 'field': ['field', 'response', 'closure'], 'response': ['response', 'closure']}[stage]
    for key in keys:
        data['approvals'].pop(key, None)
    data['sent'] = None
    data['closed'] = False


def approval(actor, snapshot):
    return {'by': actor.name, 'user_id': actor.id, 'at': time.time(), 'snapshot': copy.deepcopy(snapshot)}


def require(condition, detail, code=409):
    if not condition:
        raise HTTPException(code, detail)


def targets(case):
    priority = case.data['priority'] if case.data['approvals'].get('triage') else 'Urgent'
    review, control = TARGETS.get(priority, TARGETS['Urgent'])
    return {'review_due': case.created + review * 3600, 'control_due': case.created + control * 3600,
            'basis': 'Internal demonstration targets', 'review_hours': review, 'control_hours': control}


def riddor_details(value):
    kind = value.get('kind', 'unreviewed')
    if kind in ('none', 'unreviewed'):
        return {'status': 'Not reportable' if kind == 'none' else 'Needs review', 'due': None, 'action_due': False}
    start = date.fromisoformat(value['incident_date'])
    due = start + timedelta(days=10 if kind == 'ten' else 15 if kind == 'fifteen' else 0)
    receipt = value.get('received_date')
    if kind == 'ten' and not value.get('notified_date'):
        state = 'Notification evidence needed' if receipt else 'Notify without delay'
        action = True
    elif receipt:
        state = 'Received late' if date.fromisoformat(receipt) > due else 'Receipt recorded'
        action = False
    else:
        state = 'Report overdue' if due < date.today() else 'Report on diagnosis receipt' if kind == 'disease' else 'Report pending'
        action = due <= date.today()
    return {'status': state, 'due': due.isoformat(), 'action_due': action}


def serialize(case, attachments=None):
    return {'id': case.id, 'reference': case.reference, 'version': case.version,
            'created': case.created, 'updated': case.updated, 'status': status(case.data),
            'targets': targets(case), 'riddor_status': riddor_details(case.data.get('riddor', {})),
            **case.data, 'attachments': attachments or []}
