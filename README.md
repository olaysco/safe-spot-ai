# Safe Spot

Safe Spot is a health, safety, and environment (HSE) application that uses AI to turn safety concerns into action.
It helps teams create safer environments through simple reporting, informed decisions, and a clear record of action.

From the first report to risk control and case closure, Safe Spot connects reporters, case handlers, field officers, and managers.
People review the evidence and approve each critical decision.

## Features

- **Simple incident reporting.** Guided steps help people explain what happened, identify the location, and add photos without technical knowledge.
- **Voice input.** Reporters can speak their description in supported browsers, then check and edit the text.
- **AI assistance.** Connected models can extract report details, suggest categories and priorities, and prepare outcome responses and manager summaries.
- **Human approval.** Staff approve assignments, field findings, risk control, outcome responses, and closure. Changes cancel affected approvals.
- **Report tracking.** A reference and private tracking code let reporters check progress without a staff account.
- **Case management.** Handlers can filter reports by status, priority, officer, location, deadline, and reporter age group.
- **Field operations.** Assigned officers can record inspection findings, attach evidence, record required assistance, and confirm risk control.
- **Manager dashboards.** Counts, progress charts, location groups, and risk control times help managers identify work that needs attention.
- **Recurring incident review.** Staff can link recurring incidents or multiple reports about one event while retaining each report.
- **Alerts and reporting deadlines.** Scheduled checks flag overdue risk control and confirmed recurring incidents. Staff can record RIDDOR reporting decisions and dates.
- **Private evidence and decision history.** Staff permissions protect case records and images. The application records who approved each action and when.

AI features require a connected model service.
Manual reporting and case management remain available without AI.

## Deployment

### Run locally

Install Python 3.13.
Run these commands from the project directory.

```sh
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/python -m app.manage seed
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [Safe Spot](http://127.0.0.1:8000).
Demo staff accounts are saved in `.local/demo-accounts.txt`.

Local deployments use SQLite and local image storage.
Configure model connections and SMTP through the environment variables in [.env.example](.env.example).
The server reads exported environment variables; it does not load `.env` automatically.
Email remains in the application outbox until SMTP delivery is enabled.

### Deploy to Azure

Azure Developer CLI (`azd`) builds and deploys Safe Spot.
Bicep defines Container Apps hosting, PostgreSQL, private Blob Storage, Container Registry, and a scheduled worker.

**1. Install the Azure tools.**

Install [Azure Developer CLI](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/install-azd) version 1.37.3 or later.
Install [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-macos) for staff account administration.

**2. Set the deployment environment.**

```sh
azd auth login
azd env new safespot --location uksouth
```

Select your Azure subscription when prompted.
Open `.azure/safespot/.env` in your editor.
Add this setting with a unique database password:

```dotenv
AZURE_POSTGRES_PASSWORD="REPLACE_WITH_YOUR_DATABASE_PASSWORD"
```

Use at least 20 characters, with uppercase letters, lowercase letters, numbers, and `!` or `-`.
Keep this password for subsequent deployments.
Git excludes the `.azure` directory.

**3. Preview and deploy.**

Preview the shared infrastructure:

```sh
azd provision --preview
```

After you check the preview, deploy the application:

```sh
azd up
```

This command creates Azure resources, builds both services, and prints the application URL.
Azure charges can apply.
The preview covers shared resources; deployment also creates the web app and worker.

**4. Create staff accounts.**

Open the application URL to start the web service.
Sign in to Azure CLI:

```sh
az login
```

Replace `YOUR_SUBSCRIPTION_ID` with the subscription ID selected for `azd`.
Run this command for each staff account.

```sh
az containerapp exec \
  --subscription YOUR_SUBSCRIPTION_ID \
  --resource-group rg-safespot \
  --name safespot-web \
  --command "python -m app.manage user"
```

Enter the staff name, email, role, and password when prompted.

**5. Deploy updates.**

For application changes, run:

```sh
azd deploy --all
```

For shared infrastructure changes, repeat the preview and `azd up` commands.

See the [Azure deployment guide](infra/README.md) for permissions, configuration, and cost details.
