@allowed(['web', 'worker'])
param serviceKind string
param name string
param location string
param image string
param environmentId string
param appUrl string
param identityId string
param identityClientId string
param registryEndpoint string
param storageUrl string
@secure()
param databaseUrl string

var identity = { type: 'UserAssigned', userAssignedIdentities: { '${identityId}': {} } }
var registry = { server: registryEndpoint, identity: identityId }
var secrets = [{ name: 'database-url', value: databaseUrl }]
var variables = [
  { name: 'DATABASE_URL', secretRef: 'database-url' }
  { name: 'PUBLIC_ORIGIN', value: appUrl }
  { name: 'COOKIE_SECURE', value: 'true' }
  { name: 'WORKER_ENABLED', value: 'false' }
  { name: 'EMAIL_MODE', value: 'capture' }
  { name: 'STORAGE_BACKEND', value: 'azure' }
  { name: 'AZURE_STORAGE_ACCOUNT_URL', value: storageUrl }
  { name: 'AZURE_STORAGE_CONTAINER', value: 'evidence' }
  { name: 'AZURE_CLIENT_ID', value: identityClientId }
]
resource app 'Microsoft.App/containerApps@2025-01-01' = if (serviceKind == 'web') {
  name: '${name}-web'
  location: location
  tags: { 'azd-env-name': name, 'azd-service-name': serviceKind }
  identity: identity
  properties: {
    environmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: secrets
      registries: [registry]
      ingress: { external: true, targetPort: 8000, transport: 'http', allowInsecure: false }
    }
    template: {
      containers: [
        {
          name: 'web'
          image: image
          env: variables
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          probes: [
            { type: 'Readiness', httpGet: { path: '/api/health', port: 8000 }, periodSeconds: 10 }
            {
              type: 'Liveness'
              httpGet: { path: '/api/health', port: 8000 }
              initialDelaySeconds: 30
              periodSeconds: 30
            }
          ]
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
}
resource worker 'Microsoft.App/jobs@2025-01-01' = if (serviceKind == 'worker') {
  name: '${name}-worker'
  location: location
  tags: { 'azd-env-name': name, 'azd-service-name': serviceKind }
  identity: identity
  properties: {
    environmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Schedule'
      replicaTimeout: 240
      replicaRetryLimit: 0
      scheduleTriggerConfig: { cronExpression: '*/5 * * * *', parallelism: 1, replicaCompletionCount: 1 }
      secrets: secrets
      registries: [registry]
    }
    template: {
      containers: [
        {
          name: 'worker'
          image: image
          command: ['python', '-m', 'app.worker']
          env: variables
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
        }
      ]
    }
  }
}
