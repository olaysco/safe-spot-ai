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
param aiEndpoint string = ''
param aiTextDeployment string = ''
@secure()
@minLength(20)
param databasePassword string

module runtime './runtime.bicep' = {
  name: 'web-runtime'
  params: {
    serviceKind: 'web'
    name: name
    location: location
    image: image
    environmentId: environmentId
    appUrl: appUrl
    identityId: identityId
    identityClientId: identityClientId
    registryEndpoint: registryEndpoint
    storageUrl: storageUrl
    aiEndpoint: aiEndpoint
    aiTextDeployment: aiTextDeployment
    databaseUrl: 'postgresql+psycopg://safespotadmin:${uriComponent(databasePassword)}@${databaseHost}:5432/safespot?sslmode=require'
  }
}
