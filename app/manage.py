"""Create local accounts and fictional demonstration records."""
import argparse
import secrets
import time
from pathlib import Path
from sqlalchemy import select
from app.database import Case, Group, User, connect
from app.domain import approval, audit, new_case
from app.security import digest, hash_password


def seed():
    engine, factory = connect()
    path = Path('.local/demo-accounts.txt')
    credentials = []
    with factory() as db:
        for role, name in [('handler', 'Alex Morgan'), ('officer', 'Sam Taylor'), ('manager', 'Jo Patel')]:
            email = role + '@safespot.test'
            if not db.scalar(select(User).where(User.email == email)):
                password = secrets.token_urlsafe(18)
                db.add(User(name=name, email=email, role=role, password=hash_password(password)))
                credentials.append(f'{role}: {email}  {password}')
        db.commit()
        if credentials:
            path.parent.mkdir(exist_ok=True)
            with path.open('a') as handle:
                handle.write('\n'.join(credentials) + '\n')
            path.chmod(0o600)
        if not db.scalar(select(Case)):
            handler = db.scalar(select(User).where(User.role == 'handler'))
            officer = db.scalar(select(User).where(User.role == 'officer'))
            ids = []
            for index, (location, description) in enumerate([
                ('East entrance', 'Water remains on the floor beside the entrance.'),
                ('East entrance', 'The entrance floor became wet again this morning.'),
                ('East entrance', 'Another water leak appeared near the entrance mat.'),
                ('Workshop', 'A loose cable crosses the marked walking route.'),
                ('Library', 'A shelf bracket is loose near the study area.'),
                ('West stairs', 'The stair rail moves when a person holds it.'),
                ('Workshop', 'A damaged plug was found during an equipment check.'),
                ('Library', 'A box obstructed the exit route. Staff removed it.'),
            ]):
                report = {'description': description, 'location': location, 'time': 'Fictional demonstration record',
                    'harm': 'No injury reported', 'remains': 'Needs inspection', 'age_range': 'Under 18' if index == 0 else '18 and over',
                    'consent': False, 'name': '', 'email': '', 'confirmed': True}
                data = new_case(report)
                created = time.time() - (index + 2) * 3600
                if index >= 3:
                    data.update(category='Hazard', priority='Urgent', officer_id=officer.id)
                    data['approvals']['triage'] = approval(handler, {'category': 'Hazard', 'priority': 'Urgent', 'officer_id': officer.id})
                    data['approvals']['triage']['at'] = created + 1800
                    audit(data, handler, 'Assignment approved', 'Fictional demonstration record')
                if index >= 6:
                    data['findings'] = {'details': 'The officer inspected the area.', 'evidence': 'Fictional inspection record',
                        'assistance': 'None', 'control': 'The obstruction or damaged item was removed.'}
                    data['approvals']['field'] = approval(officer, data['findings'])
                    data['approvals']['field']['at'] = created + 7200
                case = Case(reference=f'SS-DEMO{index+1:04}', tracking_hash=digest(secrets.token_urlsafe(32)), created=created, data=data)
                db.add(case)
                db.flush()
                ids.append(case.id)
            db.add(Group(data={'case_ids': ids[:3], 'relationship': 'recurring', 'reason': 'Fictional reports describe leaks on separate occasions.', 'by': handler.name, 'at': time.time()}))
            db.commit()
    engine.dispose()
    print('Local setup is complete. Account details: .local/demo-accounts.txt')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Safe Spot local setup')
    parser.add_argument('command', choices=['seed'])
    parser.parse_args()
    seed()
