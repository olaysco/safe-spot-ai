param name string
param location string
@secure()
param databasePassword string
param image string

var suffix = uniqueString(resourceGroup().id)
var appName = '${name}-web'
var blobRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
var acrPullRole = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '7f951dda-4ed3-4680-a7ca-43fe172d538d'
)

resource network 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${name}-network'
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: ['10.40.0.0/16']
    }
    subnets: [
      {
        name: 'apps'
        properties: {
          addressPrefix: '10.40.0.0/23'
          delegations: [{ name: 'apps', properties: { serviceName: 'Microsoft.App/environments' } }]
        }
      }
      {
        name: 'database'
        properties: {
          addressPrefix: '10.40.2.0/28'
          delegations: [{ name: 'database', properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' } }]
        }
      }
    ]
  }
}
resource dns 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: '${name}.postgres.database.azure.com'
  location: 'global'
}
resource dnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: dns
  name: '${name}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: network.id }
  }
}
resource database 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: '${name}-pg-${suffix}'
  location: location
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '16'
    administratorLogin: 'safespotadmin'
    administratorLoginPassword: databasePassword
    storage: { storageSizeGB: 32, autoGrow: 'Disabled' }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    network: {
      delegatedSubnetResourceId: '${network.id}/subnets/database'
      privateDnsZoneArmResourceId: dns.id
      publicNetworkAccess: 'Disabled'
    }
  }
  dependsOn: [dnsLink]
}
resource appDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: database
  name: 'safespot'
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
}
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'ss${suffix}'
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}
resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {}
}
resource evidence 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobs
  name: 'evidence'
  properties: { publicAccess: 'None' }
}
resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'ss${suffix}'
  location: location
  sku: { name: 'Standard' }
  properties: { adminUserEnabled: false }
}
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${name}-identity'
  location: location
}
resource storageAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(evidence.id, identity.id, blobRole)
  scope: evidence
  properties: {
    roleDefinitionId: blobRole
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}
resource registryAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, acrPullRole)
  scope: registry
  properties: {
    roleDefinitionId: acrPullRole
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}
resource environment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: '${name}-environment'
  location: location
  properties: {
    appLogsConfiguration: { destination: 'none' }
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
    vnetConfiguration: {
      infrastructureSubnetId: '${network.id}/subnets/apps'
      internal: false
    }
  }
}

module runtime './runtime.bicep' = if (!empty(image)) {
  name: '${name}-runtime'
  params: {
    name: name
    location: location
    image: image
    environmentId: environment.id
    appUrl: 'https://${appName}.${environment.properties.defaultDomain}'
    identityId: identity.id
    identityClientId: identity.properties.clientId
    registryEndpoint: registry.properties.loginServer
    storageUrl: storage.properties.primaryEndpoints.blob
    databaseUrl: 'postgresql+psycopg://safespotadmin:${uriComponent(databasePassword)}@${database.properties.fullyQualifiedDomainName}:5432/safespot?sslmode=require'
  }
  dependsOn: [appDatabase, storageAccess, registryAccess]
}
output registryName string = registry.name
output registryEndpoint string = registry.properties.loginServer
output appName string = appName
output appUrl string = 'https://${appName}.${environment.properties.defaultDomain}'
