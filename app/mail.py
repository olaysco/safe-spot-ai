import os
from urllib.parse import urlsplit

import httpx


def send_zeptomail(note):
    endpoint = os.getenv('ZEPTOMAIL_API_URL', '').strip()
    token = os.getenv('ZEPTOMAIL_API_KEY', '').strip()
    sender = os.getenv('ZEPTOMAIL_FROM', '').strip()
    url = urlsplit(endpoint)
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path != '/v1.1/email' or not token or not sender):
        raise ValueError('The ZeptoMail settings are incomplete or invalid.')
    if not token.lower().startswith('zoho-enczapikey '):
        token = 'Zoho-enczapikey ' + token
    message = {
        'from': {'address': sender, 'name': 'Safe Spot'},
        'to': [{'email_address': {'address': address}}
               for address in note.data.get('recipients', [note.data['recipient']])],
        'subject': note.data['subject'],
        'textbody': note.data['body'],
        'client_reference': note.id,
        'track_opens': False,
        'track_clicks': False,
    }
    with httpx.Client(timeout=httpx.Timeout(20, connect=10), follow_redirects=False) as client:
        response = client.post(endpoint, headers={'Authorization': token}, json=message)
        response.raise_for_status()
        result = response.json()
    if result.get('message') != 'OK' or not isinstance(result.get('request_id'), str) or not result['request_id']:
        raise RuntimeError('ZeptoMail did not confirm acceptance of the email.')
    return result['request_id']
