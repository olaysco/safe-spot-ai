targetScope = 'subscription'

@minLength(3)
@maxLength(15)
param name string = 'safespot'
param location string = 'uksouth'
@secure()
@minLength(20)
param databasePassword string
param image string = ''

resource group 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${name}'
  location: location
  tags: {
    project: 'Safe Spot'
  }
}

module resources './resources.bicep' = {
  name: '${name}-resources'
  scope: group
  params: {
    name: name
    location: location
    databasePassword: databasePassword
    image: image
  }
}

output resourceGroup string = group.name
output registryName string = resources.outputs.registryName
output registryEndpoint string = resources.outputs.registryEndpoint
output appName string = resources.outputs.appName
output appUrl string = resources.outputs.appUrl
