param name string
param location string
param identityPrincipalId string

var accountName = '${name}-ai-${uniqueString(resourceGroup().id)}'
// Assign the Cognitive Services OpenAI User role.
var inferenceRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: accountName
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

resource inferenceAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(account.id, identityPrincipalId, inferenceRole)
  scope: account
  properties: {
    roleDefinitionId: inferenceRole
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource textModel 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: 'gpt-5-mini'
  sku: { name: 'GlobalStandard', capacity: 10 }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-5-mini', version: '2025-08-07' }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

output endpoint string = 'https://${accountName}.services.ai.azure.com/openai/v1'
output textDeployment string = textModel.name
