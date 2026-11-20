"""Create local accounts and fictional demonstration records."""
import argparse
import secrets
import time
from pathlib import Path
from sqlalchemy import select
from app.database import Case, Group, OfficerProfile, User, connect
from app.domain import approval, audit, new_case
from app.security import digest, hash_password
from app.schemas import DEMO_LOGIN_EMAILS


DEMO_ACCOUNTS = [
    ('handler', 'Alex Morgan', 'functionzy+case@gmail.com'),
    ('officer', 'Sam Taylor', 'functionzy+field@gmail.com'),
    ('manager', 'Jo Patel', 'functionzy+manager@gmail.com'),
]


def configure_demo_accounts(db):
    accounts = {}
    for role, name, email in DEMO_ACCOUNTS:
        account = db.scalar(select(User).where(User.email == email))
        if not account:
            account = db.scalar(select(User).where(User.email == role+'@safespot.test'))
        if account and account.role != role:
            raise SystemExit('A demo email belongs to another role. Check the account before continuing.')
        if not account:
            account = User(name=name, role=role, email=email, password='')
            db.add(account)
        account.email = email
        account.password = hash_password('password')
        accounts[role] = account
    return accounts


def save_demo_credentials():
    path = Path('.local/demo-accounts.txt')
    path.parent.mkdir(exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    logins = {email: login for login, email in DEMO_LOGIN_EMAILS.items()}
    path.write_text(''.join(f'{role}: {logins[email]}  password\n' for role, _, email in DEMO_ACCOUNTS))


def configure_demo_officers(db, primary):
    db.flush()
    rows = [
        (primary, 'Facilities', True, 6),
        ('alex.facilities@example.test', 'Facilities', True, 4),
        ('lee.facilities@example.test', 'Facilities', False, 4),
        ('morgan.security@example.test', 'Security', True, 3),
        ('robin.safety@example.test', 'Health and Safety', True, 3),
    ]
    names = {'alex.facilities@example.test': 'Alex Reed', 'lee.facilities@example.test': 'Lee Chen',
             'morgan.security@example.test': 'Morgan Ellis', 'robin.safety@example.test': 'Robin Blake'}
    for account, department, available, capacity in rows:
        if isinstance(account, str):
            email = account
            account = db.scalar(select(User).where(User.email == email))
            if account and account.role != 'officer':
                raise SystemExit('A demonstration officer email belongs to another role.')
            if not account:
                account = User(name=names[email], role='officer', email=email, password=hash_password('password'))
                db.add(account)
                db.flush()
        if not db.get(OfficerProfile, account.id):
            db.add(OfficerProfile(user_id=account.id, department=department, available=available,
                                  capacity=capacity, demo=True))


def demo_accounts():
    engine, factory = connect()
    with factory() as db:
        configure_demo_accounts(db)
        db.commit()
    save_demo_credentials()
    engine.dispose()
    print('Demo accounts are ready. Account details: .local/demo-accounts.txt')


def seed():
    engine, factory = connect()
    with factory() as db:
        accounts = configure_demo_accounts(db)
        configure_demo_officers(db, accounts['officer'])
        db.commit()
        save_demo_credentials()
        if not db.scalar(select(Case)):
            handler = db.scalar(select(User).where(User.role == 'handler'))
            officer = accounts['officer']
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


def create_user():
    from getpass import getpass
    name = input('Staff name: ').strip()
    email = input('Staff email: ').strip().lower()
    role = input('Role (handler, officer, manager): ').strip()
    password = getpass('Password (at least 14 characters): ')
    if not name or '@' not in email or role not in ('handler', 'officer', 'manager') or len(password) < 14:
        raise SystemExit('Check the account details and password length.')
    if password != getpass('Enter the password again: '):
        raise SystemExit('The passwords do not match.')
    engine, factory = connect()
    try:
        with factory() as db:
            if db.scalar(select(User).where(User.email == email)):
                raise SystemExit('This account already exists.')
            db.add(User(name=name, email=email, role=role, password=hash_password(password)))
            db.commit()
    finally:
        engine.dispose()
    print('The staff account is created.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Safe Spot account setup')
    parser.add_argument('command', choices=['seed', 'user', 'demo-accounts'])
    args = parser.parse_args()
    {'seed': seed, 'user': create_user, 'demo-accounts': demo_accounts}[args.command]()
