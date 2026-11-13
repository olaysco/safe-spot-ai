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

Use a sender domain verified in your ZeptoMail account.
Copy the full email API URL from the SMTP/API page.
The URL must match your account region.
Add these settings to `.local/zeptomail.env`:

```dotenv
ZEPTOMAIL_API_URL="YOUR_FULL_EMAIL_API_URL"
ZEPTOMAIL_FROM="notifications@your-domain.com"
ZEPTOMAIL_API_KEY="YOUR_SEND_MAIL_TOKEN"
```

Import the settings and deploy both services:

```sh
chmod 600 .local/zeptomail.env
azd env set --file .local/zeptomail.env
azd deploy --all
```

Git excludes `.local/`.
Bicep stores the API key in a Container Apps secret for the worker.
The web container does not receive the API key.

The worker sends queued email every five minutes.
Reporters receive receipts and approved outcomes.
Case handlers receive new reports and approved risk control updates.
Assigned field officers receive approved assignments.
Manager alerts go to the email addresses of current manager accounts in Safe Spot.
Staff alerts stay queued if the role has no account.
Existing captured messages remain in the demonstration outbox.
The outbox records provider acceptance; it does not confirm inbox receipt.
The worker does not repeat requests with an unknown result.

For the demonstration, route all email to one inbox:

```sh
azd env set DEMO_EMAIL_TO functionzy@gmail.com
azd deploy --all
```

This includes reporter receipts, approved outcomes, and staff alerts.
Each subject identifies the role and message purpose.
The email includes an HTML template and a plain text version.
Set `DEMO_EMAIL_TO` to an empty value to restore normal recipients.

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
| Email, when enabled | Zoho ZeptoMail API; verified sender domain; worker secret |

Email stays in capture mode until the ZeptoMail settings are configured.
AI stays disabled until `SAFE_SPOT_AI_ENABLED` is set to `true`.
Free allowances depend on your subscription and usage.
Image builds, networking, and other resources can incur charges.
The preview does not calculate costs.

After deployment, check staff sign-in, report creation, image access, and scheduled worker execution.
