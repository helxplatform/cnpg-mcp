# Helm Deployment Guide

Complete guide for deploying CloudNativePG MCP Server using Helm and the included Makefile.

## Prerequisites

- Kubernetes cluster (1.19+)
- Helm 3.0+
- kubectl configured
- CloudNativePG operator installed
- Docker or Podman (for building images)
- Python 3.7+ (for make_config.py)

## Quick Start (5 Minutes)

### 1. Generate Configuration

```bash
# Run make config to generate make.env
make config

# This creates a make.env file with auto-detected settings
```

### 2. Customize Configuration

Edit `make.env` to match your environment:

```bash
# Edit configuration
vim make.env
```

Example `make.env`:

```bash
IMAGE_REPO=ghcr.io/your-org/cnpg-mcp-server
IMAGE_TAG=v1.0.0
CONTAINER_TOOL=docker
HELM_RELEASE=cnpg-mcp
HELM_NAMESPACE=default
```

### 3. Build and Push Container Image

```bash
# Build the container image
make build

# Push to your registry (requires authentication)
make push

# Or do both in one command
make build-push
```

### 4. Configure Helm Values

Create a `values-override.yaml` file:

```yaml
# Image from your registry
image:
  repository: ghcr.io/your-org/cnpg-mcp-server
  tag: "v1.0.0"

# OIDC Configuration (REQUIRED for production)
oidc:
  enabled: true
  issuer: "https://auth.example.com"
  audience: "mcp-api"

# Ingress (optional but recommended)
ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: mcp-api.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: mcp-api-tls
      hosts:
        - mcp-api.example.com
```

### 5. Deploy with Helm

```bash
# Install using Makefile (uses make.env values)
make helm-install

# Or manually with custom values
helm install cnpg-mcp chart/ \
  -f values-override.yaml \
  --namespace default \
  --create-namespace
```

### 6. Verify Deployment

```bash
# Check pod status
make k8s-pods

# View logs
make k8s-logs

# Test via port-forward
make k8s-port-forward
# Then in another terminal:
curl http://localhost:3000/health
```

## Makefile Reference

### Configuration Commands

```bash
make config           # Generate make.env configuration
make config-show      # Display current configuration
```

### Container Build Commands

```bash
make build            # Build container image
make build-no-cache   # Build without cache
make push             # Push image to registry
make build-push       # Build and push in one command
make test-image       # Test container locally
```

### Helm Commands

```bash
make helm-lint        # Lint Helm chart
make helm-template    # Render templates (dry-run)
make helm-install     # Install chart
make helm-upgrade     # Upgrade existing release
make helm-uninstall   # Remove release
make helm-status      # Show release status
make helm-values      # Show deployed values
```

### Development Commands

```bash
make dev-start-http   # Start server locally in HTTP mode
make dev-test-stdio   # Test with stdio transport
make dev-test-http    # Test with HTTP transport
```

### Kubernetes Commands

```bash
make k8s-logs         # View pod logs
make k8s-pods         # List pods
make k8s-describe     # Describe resources
make k8s-port-forward # Port forward to service
make k8s-shell        # Open shell in pod
```

### Utility Commands

```bash
make clean            # Remove generated files
make help             # Show all available commands
```

## Configuration Options

### Helm Values Structure

```yaml
# Replica configuration
replicaCount: 2

# Container image
image:
  repository: ghcr.io/your-org/cnpg-mcp-server
  pullPolicy: IfNotPresent
  tag: ""  # Uses appVersion from Chart.yaml if empty

# ServiceAccount
serviceAccount:
  create: true
  name: "cnpg-mcp-server"
  annotations: {}

# RBAC
rbac:
  create: true
  cnpgRole: "cnpg-cloudnative-pg-edit"  # Options: edit, view, admin

# OIDC Authentication
oidc:
  enabled: true
  issuer: "https://auth.example.com"
  audience: "mcp-api"
  jwksUri: ""           # Optional override
  dcrProxyUrl: ""       # Optional DCR proxy
  scope: "openid"       # OAuth2 scope

# Resources
resources:
  limits:
    cpu: 500m
    memory: 512Mi
  requests:
    cpu: 100m
    memory: 256Mi

# Autoscaling
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80

# Service
service:
  type: ClusterIP
  port: 3000

# Ingress
ingress:
  enabled: false
  className: "nginx"
  hosts:
    - host: mcp-api.example.com
      paths:
        - path: /
          pathType: Prefix

# Pod Disruption Budget
podDisruptionBudget:
  enabled: true
  minAvailable: 1

# Network Policy
networkPolicy:
  enabled: false
```

## Deployment Scenarios

### Development Environment

```yaml
# values-dev.yaml
replicaCount: 1

oidc:
  enabled: false  # WARNING: Insecure!

autoscaling:
  enabled: false

resources:
  requests:
    cpu: 50m
    memory: 128Mi
  limits:
    cpu: 200m
    memory: 256Mi
```

Deploy:
```bash
helm install cnpg-mcp chart/ -f values-dev.yaml
```

### Staging Environment

```yaml
# values-staging.yaml
image:
  repository: ghcr.io/your-org/cnpg-mcp-server
  tag: "v1.0.0-rc1"

oidc:
  enabled: true
  issuer: "https://staging-auth.example.com"
  audience: "mcp-staging-api"

ingress:
  enabled: true
  hosts:
    - host: mcp-staging.example.com
      paths:
        - path: /
          pathType: Prefix
```

Deploy:
```bash
helm install cnpg-mcp chart/ -f values-staging.yaml --namespace staging
```

### Production Environment

```yaml
# values-prod.yaml
replicaCount: 3

image:
  repository: ghcr.io/your-org/cnpg-mcp-server
  tag: "v1.0.0"
  pullPolicy: IfNotPresent

oidc:
  enabled: true
  issuer: "https://auth.example.com"
  audience: "mcp-api"

ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/rate-limit: "100"
  hosts:
    - host: mcp.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: mcp-tls
      hosts:
        - mcp.example.com

autoscaling:
  enabled: true
  minReplicas: 3
  maxReplicas: 20

resources:
  requests:
    cpu: 200m
    memory: 512Mi
  limits:
    cpu: 1000m
    memory: 1Gi

networkPolicy:
  enabled: true
```

Deploy:
```bash
helm install cnpg-mcp chart/ \
  -f values-prod.yaml \
  --namespace production \
  --create-namespace
```

## Upgrading

### Upgrade Container Image

```bash
# Update make.env with new tag
vim make.env

# Build and push new image
make build-push

# Upgrade Helm release
make helm-upgrade
```

### Upgrade with New Values

```bash
# Edit values
vim values-override.yaml

# Upgrade
helm upgrade cnpg-mcp chart/ -f values-override.yaml
```

### Upgrade with CLI Override

```bash
helm upgrade cnpg-mcp chart/ \
  --set image.tag=v1.1.0 \
  --set oidc.issuer=https://new-auth.example.com
```

## Rollback

```bash
# List releases
helm history cnpg-mcp

# Rollback to previous version
helm rollback cnpg-mcp

# Rollback to specific revision
helm rollback cnpg-mcp 2
```

## Monitoring and Debugging

### Check Pod Status

```bash
kubectl get pods -l app.kubernetes.io/name=cnpg-mcp -n default
```

### View Logs

```bash
# Using Makefile
make k8s-logs

# Using kubectl
kubectl logs -f -l app.kubernetes.io/name=cnpg-mcp -n default

# Specific pod
kubectl logs -f <pod-name> -n default
```

### Describe Resources

```bash
# Using Makefile
make k8s-describe

# Using kubectl
kubectl describe deployment cnpg-mcp -n default
kubectl describe pod <pod-name> -n default
```

### Port Forward for Testing

```bash
# Using Makefile
make k8s-port-forward

# Using kubectl
kubectl port-forward svc/cnpg-mcp-cnpg-mcp 3000:3000 -n default
```

Then test:
```bash
# Health check
curl http://localhost:3000/health

# OAuth metadata
curl http://localhost:3000/.well-known/oauth-authorization-server

# MCP endpoint (requires token)
./test-inspector.sh --transport http --url http://localhost:3000 --token-file token.txt
```

### Get Shell Access

```bash
# Using Makefile
make k8s-shell

# Using kubectl
kubectl exec -it <pod-name> -n default -- /bin/bash
```

## Troubleshooting

### Pod Not Starting

1. Check pod events:
   ```bash
   kubectl describe pod <pod-name>
   ```

2. Common issues:
   - Image pull errors (check registry credentials)
   - Resource limits too low
   - Missing RBAC permissions

### OIDC Authentication Fails

1. Check ConfigMap:
   ```bash
   kubectl get configmap cnpg-mcp-cnpg-mcp-oidc-config -o yaml
   ```

2. Verify OIDC issuer is accessible from pods:
   ```bash
   kubectl exec <pod-name> -- curl -v https://auth.example.com/.well-known/openid-configuration
   ```

3. Check pod logs for auth errors:
   ```bash
   kubectl logs <pod-name> | grep -i oidc
   ```

### RBAC Permission Errors

1. Check RoleBinding:
   ```bash
   kubectl get rolebinding cnpg-mcp-cnpg-mcp -o yaml
   ```

2. Verify CloudNativePG roles exist:
   ```bash
   kubectl get clusterroles | grep cnpg
   ```

3. Test permissions:
   ```bash
   kubectl auth can-i get clusters.postgresql.cnpg.io \
     --as=system:serviceaccount:default:cnpg-mcp-server
   ```

### Ingress Not Working

1. Check Ingress resource:
   ```bash
   kubectl get ingress cnpg-mcp-cnpg-mcp
   kubectl describe ingress cnpg-mcp-cnpg-mcp
   ```

2. Verify Ingress controller is running:
   ```bash
   kubectl get pods -n ingress-nginx
   ```

3. Check TLS certificate:
   ```bash
   kubectl get certificate mcp-api-tls
   kubectl describe certificate mcp-api-tls
   ```

## Security Checklist

- [ ] OIDC authentication enabled (`oidc.enabled=true`)
- [ ] Strong issuer and audience configured
- [ ] TLS enabled on Ingress
- [ ] Resource limits set
- [ ] RBAC using least-privilege role
- [ ] Network policies enabled (optional)
- [ ] Pod security context configured
- [ ] Image from trusted registry
- [ ] Regular security updates

## Best Practices

1. **Use Version Tags**: Always use specific version tags, never `latest`
2. **Enable Autoscaling**: Configure HPA for production workloads
3. **Set Resource Limits**: Prevent resource exhaustion
4. **Enable PodDisruptionBudget**: Ensure availability during updates
5. **Use Namespaces**: Isolate environments
6. **Monitor Logs**: Centralize logging (Loki, ELK, etc.)
7. **Regular Backups**: Backup configuration and values
8. **Test Upgrades**: Test in staging before production
9. **Document Changes**: Track configuration changes in Git

## Additional Resources

- [Helm Documentation](https://helm.sh/docs/)
- [Kubernetes Best Practices](https://kubernetes.io/docs/concepts/configuration/overview/)
- [CloudNativePG Operator](https://cloudnative-pg.io/)
- [OIDC Setup Guide](OIDC_SETUP.md)
- [Project Documentation](CLAUDE.md)
