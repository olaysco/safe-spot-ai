import hashlib
import hmac
import secrets


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def report_reference():
    alphabet = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'
    value = ''.join(secrets.choice(alphabet) for _ in range(10))
    return f'SS-{value[:5]}-{value[5:]}'


def normalize_reference(value):
    compact = ''.join(value.upper().split()).replace('-', '')
    if compact.startswith('SS'):
        if len(compact) == 12:
            return f'SS-{compact[2:7]}-{compact[7:]}'
        if len(compact) == 10:
            return 'SS-' + compact[2:]
    return value.strip().upper()


def hash_password(password):
    salt = secrets.token_hex(16)
    key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return salt + ':' + key.hex()


def verify_password(password, stored):
    salt, expected = stored.split(':')
    key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return hmac.compare_digest(key.hex(), expected)
