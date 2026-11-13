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
param emailEndpoint string = ''
param emailSender string = ''
param demoEmailTo string = ''
@secure()
param emailApiKey string = ''
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
    aiEndpoint: aiEndpoint
    aiTextDeployment: aiTextDeployment
    emailEndpoint: emailEndpoint
    emailSender: emailSender
    demoEmailTo: demoEmailTo
    emailApiKey: emailApiKey
    databaseUrl: 'postgresql+psycopg://safespotadmin:${uriComponent(databasePassword)}@${databaseHost}:5432/safespot?sslmode=require'
  }
}
