param name string
param location string
param image string
param environmentId string
param appUrl string
param identityId string
param identityClientId string
param registryEndpoint string
param storageUrl string
param databaseHost string
@secure()
@minLength(20)
param databasePassword string

module runtime './runtime.bicep' = {
  name: 'worker-runtime'
  params: {
    serviceKind: 'worker'
    name: name
    location: location
    image: image
    environmentId: environmentId
    appUrl: appUrl
    identityId: identityId
    identityClientId: identityClientId
    registryEndpoint: registryEndpoint
    storageUrl: storageUrl
    databaseUrl: 'postgresql+psycopg://safespotadmin:${uriComponent(databasePassword)}@${databaseHost}:5432/safespot?sslmode=require'
  }
}
