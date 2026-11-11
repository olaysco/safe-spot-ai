# Azure deployment

Azure Developer CLI (`azd`) builds and deploys Safe Spot from the Bicep configuration.
Deployment access must permit resource creation and role assignments.

## Setup

Install [Azure Developer CLI](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/install-azd) version 1.37.3 or later.
Install [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-macos) for staff account administration.
Run these commands from the project directory:

```sh
azd auth login
azd env new safespot --location uksouth
```

Select your Azure subscription when prompted.
Create `.azure/safespot/secrets.env` in your editor.
Add this setting with a unique database password:

```dotenv
AZURE_POSTGRES_PASSWORD="REPLACE_WITH_YOUR_DATABASE_PASSWORD"
```

Use at least 20 characters, with uppercase letters, lowercase letters, numbers, and `!` or `-`.
Import the password into the deployment environment:

```sh
chmod 600 .azure/safespot/secrets.env
azd env set --file .azure/safespot/secrets.env
```

Keep the same environment settings and password for subsequent deployments.
Git excludes local settings in `.azure/`.

## Deploy

Preview the shared infrastructure:

```sh
azd provision --preview
```

After you check the preview, deploy the application:

```sh
azd up
```

The preview covers the shared resources in `main.bicep` and `resources.bicep`.
Deployment also creates the web app and worker through `web.bicep`, `worker.bicep`, and `runtime.bicep`.
The command prints the application URL.
Azure charges can apply.

## Staff accounts

Open the application URL to start the web service.
Sign in to Azure CLI:

```sh
az login
```

Replace `YOUR_SUBSCRIPTION_ID` with the subscription ID selected for `azd`.
Run this command for each staff account:

```sh
az containerapp exec \
  --subscription YOUR_SUBSCRIPTION_ID \
  --resource-group rg-safespot \
  --name safespot-web \
  --command "python -m app.manage user"
```

Enter the staff name, email, role, and password when prompted.

## Updates

For application changes, run:

```sh
azd deploy --all
```

For shared infrastructure changes, repeat the preview and `azd up` commands.

## Enable AI

Enable GPT-5-mini for report assistance, triage suggestions, response drafts, and manager summaries:

```sh
azd env set SAFE_SPOT_AI_ENABLED true
azd provision --preview
azd up
```

Bicep creates one GPT-5-mini deployment in Microsoft Foundry.
The web app and worker use managed identity for access.
No AI API key is required in Azure.
Staff must review and approve AI suggestions.

The deployment uses Global Standard billing and model version `2025-08-07`.
Azure charges for model usage.
Global Standard can process requests outside the resource region.
The Azure subscription must have model quota in the selected region.
Voice input continues to use browser speech recognition.

## Enable email

Set the manager address and enable Azure Email:

```sh
azd env set SAFE_SPOT_MANAGER_EMAIL manager@example.com
azd env set SAFE_SPOT_EMAIL_ENABLED true
azd provision --preview
azd up
```

Replace `manager@example.com` with the address for manager alerts.
Bicep creates an Azure-managed sender domain and grants the application identity access to send email.
The worker sends report receipts, approved outcomes, and manager alerts.
It checks the queue every five minutes.
Existing captured messages remain in the demonstration outbox.

Azure-managed domains permit [10 emails per hour](https://learn.microsoft.com/en-us/azure/communication-services/concepts/service-limits#rate-limits-for-email).
Additional messages stay queued.
The outbox records send status; it does not confirm inbox receipt.
Azure charges for email use.
Azure Email [retires on 30 September 2028](https://learn.microsoft.com/en-us/azure/communication-services/acs-retirement-and-breaking-changes-guide#acs-email).

## Resources and costs

| Resource | Configuration |
|---|---|
| Web app | Container Apps Consumption; 0.25 vCPU, 0.5 GiB; zero to one replica |
| Worker | Scheduled container job; one run every five minutes |
| Database | PostgreSQL 16; B1MS; 32 GB; private network access |
| Evidence storage | Private Blob container; Standard LRS |
| Image registry | Standard Container Registry; separate remote builds for web and worker |
| Network and access | Separate subnets, private database DNS, and managed identity |
| AI, when enabled | GPT-5-mini; Global Standard; capacity 10; managed identity access |
| Email, when enabled | Azure Communication Services; managed sender domain; managed identity access |

Email stays in capture mode until the email service and manager address are configured.
AI stays disabled until `SAFE_SPOT_AI_ENABLED` is set to `true`.
Free allowances depend on your subscription and usage.
Image builds, networking, and other resources can incur charges.
The preview does not calculate costs.

After deployment, check staff sign-in, report creation, image access, and scheduled worker execution.
