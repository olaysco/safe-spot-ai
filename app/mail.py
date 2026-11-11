import os
import uuid
from functools import lru_cache

from azure.communication.email import EmailClient
from azure.core.exceptions import HttpResponseError
from azure.core.rest import HttpRequest
from azure.identity import DefaultAzureCredential


@lru_cache(maxsize=1)
def azure_client():
    credential = DefaultAzureCredential(managed_identity_client_id=os.getenv('AZURE_CLIENT_ID'),
                                        exclude_interactive_browser_credential=True)
    return EmailClient(os.environ['AZURE_EMAIL_ENDPOINT'], credential,
                       connection_timeout=10, read_timeout=20, retry_total=0)


def operation_id(note):
    return str(uuid.UUID(note.id))


def send_azure(note):
    message = {
        'senderAddress': os.environ['AZURE_EMAIL_FROM'],
        'recipients': {'to': [{'address': note.data['recipient']}]},
        'content': {'subject': note.data['subject'], 'plainText': note.data['body']},
    }
    # The worker checks the result during a subsequent run.
    azure_client().begin_send(message, operation_id=operation_id(note), polling=False).result()


def azure_status(note):
    endpoint = os.environ['AZURE_EMAIL_ENDPOINT'].rstrip('/')
    response = azure_client().send_request(HttpRequest(
        'GET', f'{endpoint}/emails/operations/{operation_id(note)}?api-version=2025-09-01'))
    if response.status_code != 200:
        raise HttpResponseError(response=response)
    return response.json()['status']
