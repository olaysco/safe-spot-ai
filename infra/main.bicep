targetScope = 'subscription'

@minLength(3)
@maxLength(15)
param name string = 'safespot'
param location string = 'uksouth'
@allowed(['true', 'false'])
param enableAI string = 'false'
@allowed(['true', 'false'])
param enableEmail string = 'false'
@secure()
@minLength(20)
param databasePassword string

resource group 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${name}'
  location: location
  tags: {
    project: 'Safe Spot'
    'azd-env-name': name
  }
}

module resources './resources.bicep' = {
  name: '${name}-resources'
  scope: group
  params: {
    name: name
    location: location
    databasePassword: databasePassword
    enableAI: enableAI == 'true'
    enableEmail: enableEmail == 'true'
  }
}

output AZURE_RESOURCE_GROUP string = group.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = resources.outputs.registryEndpoint
output AZURE_CONTAINER_ENVIRONMENT_ID string = resources.outputs.environmentId
output AZURE_IDENTITY_ID string = resources.outputs.identityId
output AZURE_IDENTITY_CLIENT_ID string = resources.outputs.identityClientId
output AZURE_STORAGE_ACCOUNT_URL string = resources.outputs.storageUrl
output AZURE_POSTGRES_HOST string = resources.outputs.databaseHost
output SERVICE_WEB_URI string = resources.outputs.appUrl
output AZURE_AI_ENDPOINT string = resources.outputs.aiEndpoint
output AZURE_AI_TEXT_DEPLOYMENT string = resources.outputs.aiTextDeployment
output AZURE_EMAIL_ENDPOINT string = resources.outputs.emailEndpoint
output AZURE_EMAIL_FROM string = resources.outputs.emailSender
