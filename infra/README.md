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
Open `.azure/safespot/.env` in your editor.
Add this setting with a unique database password:

```dotenv
AZURE_POSTGRES_PASSWORD="REPLACE_WITH_YOUR_DATABASE_PASSWORD"
```

Use at least 20 characters, with uppercase letters, lowercase letters, numbers, and `!` or `-`.
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

## Resources and costs

| Resource | Configuration |
|---|---|
| Web app | Container Apps Consumption; 0.25 vCPU, 0.5 GiB; zero to one replica |
| Worker | Scheduled container job; one run every five minutes |
| Database | PostgreSQL 16; B1MS; 32 GB; private network access |
| Evidence storage | Private Blob container; Standard LRS |
| Image registry | Standard Container Registry; separate remote builds for web and worker |
| Network and access | Separate subnets, private database DNS, and managed identity |

Email stays in capture mode until SMTP is configured.
AI features require separate model connections.
Free allowances depend on your subscription and usage.
Image builds, networking, and other resources can incur charges.
The preview does not calculate costs.

After deployment, check staff sign-in, report creation, image access, and scheduled worker execution.
