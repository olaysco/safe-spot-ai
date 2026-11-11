param name string
param identityPrincipalId string

resource email 'Microsoft.Communication/emailServices@2023-03-31' = {
  name: '${name}-email'
  location: 'global'
  properties: { dataLocation: 'United Kingdom' }
}

resource domain 'Microsoft.Communication/emailServices/domains@2023-03-31' = {
  parent: email
  name: 'AzureManagedDomain'
  location: 'global'
  properties: {
    domainManagement: 'AzureManaged'
    userEngagementTracking: 'Disabled'
  }
}

resource communication 'Microsoft.Communication/communicationServices@2023-03-31' = {
  name: '${name}-communication-${uniqueString(resourceGroup().id)}'
  location: 'global'
  properties: {
    dataLocation: 'United Kingdom'
    linkedDomains: [domain.id]
  }
}

resource senderRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(resourceGroup().id, 'email-sender')
  properties: {
    roleName: '${name} email sender ${uniqueString(resourceGroup().id)}'
    description: 'Send application email through Azure Communication Services.'
    type: 'CustomRole'
    assignableScopes: [resourceGroup().id]
    permissions: [{
      actions: [
        'Microsoft.Communication/CommunicationServices/read'
        'Microsoft.Communication/CommunicationServices/write'
        'Microsoft.Communication/EmailServices/write'
      ]
      notActions: []
      dataActions: []
      notDataActions: []
    }]
  }
}

resource senderAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(communication.id, identityPrincipalId, senderRole.id)
  scope: communication
  properties: {
    roleDefinitionId: senderRole.id
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output endpoint string = 'https://${communication.properties.hostName}'
output sender string = 'DoNotReply@${domain.properties.mailFromSenderDomain}'
