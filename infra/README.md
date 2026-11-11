# Azure infrastructure

Azure Developer CLI (`azd`) builds and deploys Safe Spot.
Bicep defines the Azure resources.
Follow the [README deployment steps](../README.md#deploy-to-azure) for installation, subscription selection, database credentials, and staff accounts.
Deployment access must permit resource creation and role assignments.

## Resources

| Resource | Configuration |
|---|---|
| Web app | Container Apps Consumption; 0.25 vCPU, 0.5 GiB; zero to one replica |
| Worker | Scheduled container job; one run every five minutes |
| Database | PostgreSQL 16; B1MS; 32 GB; private network access |
| Evidence storage | Private Blob container; Standard LRS |
| Image registry | Standard Container Registry; remote image builds |
| Network and access | Separate subnets, private database DNS, and managed identity |

The web app and worker use the same code with separate image builds.
Email stays in capture mode until SMTP is configured.
AI features require separate model connections.

## Deployment

After you complete the README setup, preview the shared infrastructure:

```sh
azd provision --preview
```

After you check the preview, deploy the application:

```sh
azd up
```

The preview covers `main.bicep` and `resources.bicep`.
Deployment also applies `web.bicep` and `worker.bicep`, which use the shared settings in `runtime.bicep`.
See the [Microsoft deployment workflow](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/container-apps-workflows) for this deployment method.

For application updates, run:

```sh
azd deploy --all
```

For shared infrastructure changes, repeat the preview and `azd up` commands.
Keep the same environment settings and database password for subsequent deployments.
Git excludes local settings in `.azure/`.

## Costs and checks

Free allowances depend on your subscription and usage.
Database, registry, image builds, networking, storage, and worker execution can incur charges.
The preview does not calculate costs.

Local Bicep compilation does not confirm Azure permissions, quotas, or service operation.
After deployment, check staff sign-in, report creation, image access, and scheduled worker execution.
