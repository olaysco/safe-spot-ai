import os
import re
from html import escape
from pathlib import Path
from string import Template
from urllib.parse import urlsplit

import httpx


ROLE_LABELS = {'receipt': 'Reporter', 'outcome': 'Reporter', 'handler': 'Case handler',
               'officer': 'Field officer', 'manager': 'Manager'}
EMAIL_TEMPLATE = Template((Path(__file__).parent / 'templates' / 'notification.html').read_text())


def prepare_message(note):
    data = note.data
    intended = data.get('recipients') or [address.strip() for address in data.get('recipient', '').split(',') if address.strip()]
    demo_to = os.getenv('DEMO_EMAIL_TO', '').strip()
    if demo_to and not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', demo_to):
        raise ValueError('The demo email address is invalid.')
    role = ROLE_LABELS.get(data.get('kind'), 'Notification')
    prefix = 'Safe Spot demo' if demo_to else 'Safe Spot'
    subject = f'[{prefix} | {role}] {data["subject"]}'
    body = data['body']
    origin = os.getenv('PUBLIC_ORIGIN', '').strip().rstrip('/')
    url = urlsplit(origin)
    action = ''
    if url.scheme in ('https', 'http') and url.hostname and not url.username and not url.password:
        action = f'<a href="{escape(origin, quote=True)}" style="display:inline-block;padding:14px 24px;border-radius:6px;background:#285e53;color:#ffffff;font-size:16px;font-weight:700;text-decoration:none;">Open Safe Spot</a>'
    reference = re.search(r'\bSS-[A-Z0-9-]+\b', data['subject'] + ' ' + body)
    reference = reference.group(0) if reference else ''
    title = data['subject'].removesuffix(reference).rstrip(': ') if reference else data['subject']
    reference_card = ''
    if reference:
        reference_card = f'<div style="margin:0 0 24px;padding:16px 20px;border-left:4px solid #285e53;background:#e5f2ed;border-radius:4px;"><div style="font-size:12px;font-weight:700;color:#285e53;letter-spacing:1px;">REPORT REFERENCE</div><div style="margin-top:4px;font-size:20px;font-weight:700;color:#172126;">{escape(reference)}</div></div>'
    paragraphs = ''.join(f'<p style="margin:0 0 18px;line-height:1.65;overflow-wrap:anywhere;">{escape(line)}</p>'
                         for line in body.splitlines() if line.strip())
    demo_details = ''
    text = body
    if demo_to:
        demo_details = f'<p style="margin:8px 0 0;font-size:12px;line-height:1.6;overflow-wrap:anywhere;">Demo inbox: {escape(demo_to)}<br>Original recipient: {escape(", ".join(intended))}</p>'
        text = f'Demo email for: {role}\nOriginal recipient: {", ".join(intended)}\n\n{body}'
    html = EMAIL_TEMPLATE.substitute(title=escape(title), subject=escape(subject), role=escape(role),
        mode='DEMONSTRATION' if demo_to else 'CASE UPDATE', reference=reference_card,
        body=paragraphs, action=action, demo_details=demo_details)
    recipients = [demo_to] if demo_to else intended
    note.data = {**data, 'delivery_recipients': recipients, 'delivery_subject': subject}
    return {'recipients': recipients, 'subject': subject, 'text': text, 'html': html}


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
    content = prepare_message(note)
    message = {
        'from': {'address': sender, 'name': 'Safe Spot'},
        'to': [{'email_address': {'address': address}}
               for address in content['recipients']],
        'subject': content['subject'],
        'textbody': content['text'],
        'htmlbody': content['html'],
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
