# Azure deployment

Bicep defines the Azure resources.
The deployment script uses Azure CLI to preview changes, build the image, and deploy the application.
This version uses Azure CLI directly, rather than Azure Developer CLI (`azd`).
The two deployment stages create the registry before the application image is built.

## Resources

| Resource | Configuration |
|---|---|
| Container Apps | Consumption, 0.25 vCPU, 0.5 GiB, zero to one web replica |
| Scheduled worker | One run every five minutes, 240-second timeout |
| PostgreSQL | Version 16, Burstable B1MS, 32 GB, seven-day local backup |
| Blob Storage | Standard LRS, Hot tier, private evidence container |
| Container Registry | Standard tier, administrator access disabled |
| Network | Separate application and database subnets, private PostgreSQL DNS |
| Managed identity | Image pull access and evidence container access |

The web app can stop when idle.
The scheduled job processes queued work without keeping the web app running.
Each worker run processes one AI triage task and checks notifications.
The PostgreSQL advisory lock prevents overlapping worker runs.

The application uses a managed identity for Blob Storage access.
The database password is stored as a Container Apps secret.
This hackathon version uses the PostgreSQL administrator account for schema creation and application queries.
A separate application database role is a later hardening task.
Image requests still pass through staff authorization in the API.

Email stays in capture mode.
AI providers are not configured by this deployment.
The template does not create a paid AI endpoint.

## First deployment

Install Azure CLI using the [Microsoft installation instructions](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-macos).
Run these commands from the project directory.

```sh
az login
az account list --output table
az bicep install
```

The subscription account must permit resource creation and role assignments.
Owner access includes these permissions.
Contributor access alone does not permit role assignments.

Preview the deployment with your subscription ID.

```sh
python3 scripts/azure.py plan --subscription YOUR_SUBSCRIPTION_ID --location uksouth
```

The script generates a database password in `.local/azure/<subscription>/safespot/parameters.json`.
This file is excluded from Git and restricted to the local user.
Keep this file for later deployments.
Do not share it or place it in source control.

The preview contacts Azure but does not create the listed resources.
It does not calculate charges or confirm free-offer eligibility.
The region defaults to UK South.
Availability, quotas, and subscription policies can require another region.

After reviewing the preview, deploy with the same subscription and region.

```sh
python3 scripts/azure.py deploy --subscription YOUR_SUBSCRIPTION_ID --location uksouth
```

This command creates billable Azure resources.
It first creates the infrastructure and registry.
It builds a Linux image through Azure Container Registry.
It then deploys the web app and scheduled worker.
The script prints the application URL.

For later updates, run the preview and deployment commands again.
The script preserves the database password and records the image version.
Deployments use incremental mode.
Removing a resource from a template does not automatically delete that resource.

## Staff accounts

Open the application URL once to start the web replica.
Create each staff account through an interactive container session.

```sh
az containerapp exec --resource-group rg-safespot --name safespot-web --command "python -m app.manage user"
```

Enter a name, email, role, and password when prompted.
The password does not appear in shell arguments or application logs.
Repeat this command for the handler, officer, and manager accounts.
Do not run the local demo seed command on the hosted database.

## Cost scope

The database and registry tiers match the allowances supplied in this conversation.
Free allowances still depend on the subscription, expiry date, and total usage.
Blob Storage has storage, request, and transfer meters.
Registry image builds, private DNS, networking, and worker execution can have separate charges.
Log Analytics is not enabled by this template.
Do not treat this template as a guarantee of zero cost.

## Local validation

```sh
az bicep build --file infra/main.bicep --outfile .local/azure-template.json
.venv/bin/python -m pytest -q
python3 scripts/azure.py --help
```

Local compilation checks Bicep syntax and resource types.
Storage tests use a controlled Azure SDK substitute.
An Azure deployment and live Blob Storage test remain necessary after sign-in.

Reference: [Azure Bicep](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/overview).
Reference: [Azure Blob Storage for Python](https://learn.microsoft.com/en-us/azure/storage/blobs/storage-quickstart-blobs-python).
