"""Preview or deploy the Safe Spot Azure infrastructure."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def save_private(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as handle:
        json.dump(value, handle, indent=2)
    path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description='Preview or deploy Safe Spot on Azure.')
    parser.add_argument('action', choices=['plan', 'deploy'])
    parser.add_argument('--subscription', required=True)
    parser.add_argument('--name', default='safespot')
    parser.add_argument('--location', default='uksouth')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z][a-z0-9-]{2,14}', args.name):
        parser.error('Use 3 to 15 lowercase letters, digits, or hyphens for the name.')
    if not shutil.which('az'):
        raise SystemExit('Install Azure CLI, then run az login before this command.')

    def azure(*parts, capture=False):
        command = ['az', *parts, '--subscription', args.subscription, '--only-show-errors']
        result = subprocess.run(command, cwd=ROOT, check=True, text=True, capture_output=capture)
        return json.loads(result.stdout) if capture else None

    account = azure('account', 'show', capture=True)
    if account['state'] != 'Enabled':
        raise SystemExit('The selected Azure subscription is not enabled.')
    directory = ROOT / '.local' / 'azure' / account['id'] / args.name
    path = directory / 'parameters.json'
    state_path = directory / 'deployment.json'
    if path.exists():
        parameters = json.loads(path.read_text())
        if parameters['parameters']['location']['value'] != args.location:
            raise SystemExit('Use the saved deployment location for this environment.')
    else:
        parameters = {'$schema': 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#',
                      'contentVersion': '1.0.0.0', 'parameters': {
                          'name': {'value': args.name}, 'location': {'value': args.location},
                          'databasePassword': {'value': 'Ss9!' + secrets.token_urlsafe(36)}, 'image': {'value': ''}}}
        save_private(path, parameters)
    common = ['--location', args.location, '--name', args.name, '--template-file', 'infra/main.bicep', '--parameters', '@'+str(path)]
    if args.action == 'plan':
        azure('deployment', 'sub', 'what-if', *common)
        return

    # The first deployment creates the registry before the image build.
    result = azure('deployment', 'sub', 'create', *common, capture=True)
    outputs = {key: value['value'] for key, value in result['properties']['outputs'].items()}
    save_private(state_path, outputs)
    revision = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    tag = revision + '-' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    azure('acr', 'build', '--registry', outputs['registryName'], '--image', 'safespot:'+tag,
          '--platform', 'linux/amd64', '--file', 'Dockerfile', '.')
    parameters['parameters']['image']['value'] = outputs['registryEndpoint'] + '/safespot:' + tag
    save_private(path, parameters)
    azure('deployment', 'sub', 'create', *common, '--output', 'none')
    print('Application URL: ' + outputs['appUrl'])
    print('Create staff accounts with the command in infra/README.md.')


if __name__ == '__main__':
    main()
