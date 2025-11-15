# Helm Chart and Makefile - Implementation Summary

Complete implementation of Helm chart and Makefile for deploying the CloudNativePG MCP Server.

## 📦 What Was Created

### **Helm Chart (`chart/`)**

A production-ready Helm chart with:

#### **Modified Files:**
1. **`Chart.yaml`** - Chart metadata
   - Updated description for CNPG MCP Server
   - Version: 1.0.0
   - Keywords and maintainer info

2. **`values.yaml`** - Default configuration
   - 2 replicas for HA by default
   - OIDC authentication enabled
   - Autoscaling configured (2-10 replicas)
   - Resource limits: 100m/256Mi request, 500m/512Mi limit
   - Health checks with proper paths
   - Security contexts (non-root user)
   - Ingress with TLS support

3. **`templates/deployment.yaml`** - Deployment resource
   - HTTP transport mode configured
   - OIDC config via ConfigMap
   - Proper health/readiness probes (`/health`)
   - Security context enforced
   - Auto-restart on config changes (checksum annotation)

4. **`templates/service.yaml`** - Service resource
   - ClusterIP on port 3000
   - Annotations support

5. **`templates/ingress.yaml`** - Ingress resource
   - Kubernetes 1.19+ compatibility
   - TLS and cert-manager integration
   - Security headers

6. **`templates/serviceaccount.yaml`** - ServiceAccount
   - Automatic creation
   - Annotation support

7. **`templates/NOTES.txt`** - Post-install notes
   - Shows endpoints and access instructions
   - OIDC status warning
   - Useful commands

#### **New Files Created:**

8. **`templates/configmap.yaml`** - OIDC configuration
   - OIDC_ISSUER
   - OIDC_AUDIENCE
   - Optional: JWKS_URI, DCR_PROXY_URL, SCOPE

9. **`templates/rolebinding.yaml`** - RBAC
   - Binds ServiceAccount to CloudNativePG ClusterRole
   - Supports: edit (default), view, admin roles

10. **`templates/pdb.yaml`** - PodDisruptionBudget
    - Ensures minAvailable: 1 during disruptions
    - Controlled by `podDisruptionBudget.enabled`

11. **`templates/networkpolicy.yaml`** - NetworkPolicy
    - Ingress/Egress rules
    - Controlled by `networkPolicy.enabled`

12. **`README.md`** - Chart documentation
    - Configuration reference
    - Quick start guide
    - IdP-specific examples
    - Troubleshooting

---

### **Makefile**

A comprehensive Makefile with targets for:

#### **Configuration:**
- `make config` - Generate `make.env` from `make_config.py`
- `make config-show` - Display current configuration

#### **Container Build:**
- `make build` - Build container image
- `make build-no-cache` - Build without cache
- `make push` - Push to registry
- `make build-push` - Build and push
- `make test-image` - Test container locally

#### **Helm Operations:**
- `make helm-lint` - Lint chart
- `make helm-template` - Render templates
- `make helm-install` - Install release
- `make helm-upgrade` - Upgrade release
- `make helm-uninstall` - Remove release
- `make helm-status` - Show status
- `make helm-values` - Show values

#### **Development:**
- `make dev-start-http` - Start server locally
- `make dev-test-stdio` - Test stdio mode
- `make dev-test-http` - Test HTTP mode

#### **Kubernetes:**
- `make k8s-logs` - View pod logs
- `make k8s-pods` - List pods
- `make k8s-describe` - Describe resources
- `make k8s-port-forward` - Port forward
- `make k8s-shell` - Shell access

#### **Utility:**
- `make clean` - Remove generated files
- `make help` - Show all commands

---

### **Documentation**

13. **`HELM_DEPLOYMENT_GUIDE.md`** - Complete deployment guide
    - Quick start (5 minutes)
    - Makefile reference
    - Configuration examples
    - Deployment scenarios (dev, staging, prod)
    - Upgrade procedures
    - Troubleshooting

---

## 🚀 Quick Start

### 1. Generate Configuration

```bash
make config
```

This runs `make_config.py` and creates `make.env` with auto-detected settings.

### 2. Edit Configuration

```bash
vim make.env
```

Example:
```bash
IMAGE_REPO=ghcr.io/your-org/cnpg-mcp-server
IMAGE_TAG=v1.0.0
CONTAINER_TOOL=docker
HELM_RELEASE=cnpg-mcp
HELM_NAMESPACE=default
```

### 3. Build and Push Image

```bash
make build-push
```

### 4. Deploy with Helm

```bash
make helm-install
```

Or with custom values:
```bash
helm install cnpg-mcp chart/ -f values-override.yaml
```

---

## 📋 Key Features

### **Production-Ready Defaults**

✅ **High Availability**
- 2 replicas by default
- PodDisruptionBudget (minAvailable: 1)
- Autoscaling (2-10 replicas)

✅ **Security**
- OIDC authentication enabled by default
- Non-root user (uid: 1000)
- Security context enforced
- Capabilities dropped
- TLS-ready Ingress

✅ **RBAC**
- ServiceAccount created automatically
- RoleBinding to CloudNativePG roles
- Supports: edit, view, admin roles

✅ **Observability**
- Health checks at `/health`
- Readiness probes
- Resource requests/limits
- Config change detection

✅ **Flexibility**
- ConfigMap for OIDC settings
- Ingress with TLS support
- Network policies (optional)
- Multiple IdP support

---

## 🎯 Helm Values Configuration

### **Image Configuration**

```yaml
image:
  repository: ghcr.io/your-org/cnpg-mcp-server
  tag: "v1.0.0"
  pullPolicy: IfNotPresent
```

### **OIDC Authentication**

```yaml
oidc:
  enabled: true
  issuer: "https://auth.example.com"
  audience: "mcp-api"
  # Optional
  jwksUri: ""
  dcrProxyUrl: ""
  scope: "openid"
```

### **RBAC**

```yaml
rbac:
  create: true
  cnpgRole: "cnpg-cloudnative-pg-edit"  # or view, admin
```

### **Ingress**

```yaml
ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt
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

### **Autoscaling**

```yaml
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80
```

---

## 📊 Deployment Scenarios

### **Development**

```bash
# Minimal resources, no OIDC (insecure!)
helm install cnpg-mcp chart/ \
  --set replicaCount=1 \
  --set oidc.enabled=false \
  --set autoscaling.enabled=false
```

### **Staging**

```bash
# OIDC enabled, moderate resources
helm install cnpg-mcp chart/ \
  --set image.tag=v1.0.0-rc1 \
  --set oidc.issuer=https://staging-auth.example.com \
  --set ingress.enabled=true \
  --set ingress.hosts[0].host=mcp-staging.example.com \
  --namespace staging --create-namespace
```

### **Production**

```bash
# Full HA, security, monitoring
helm install cnpg-mcp chart/ \
  -f values-prod.yaml \
  --namespace production \
  --create-namespace
```

---

## 🔧 Makefile Workflow

### **Standard Workflow**

```bash
# 1. Generate config
make config

# 2. Edit settings
vim make.env

# 3. Build image
make build

# 4. Push to registry
make push

# 5. Deploy
make helm-install

# 6. Monitor
make k8s-logs
make k8s-pods

# 7. Test
make k8s-port-forward
# In another terminal:
curl http://localhost:3000/health
```

### **Development Workflow**

```bash
# Build and test locally
make build
make test-image

# Test with inspector
make dev-test-http
```

### **Update Workflow**

```bash
# Update code and rebuild
make build-no-cache
make push

# Upgrade deployment
make helm-upgrade

# Monitor rollout
make k8s-pods
make k8s-logs
```

---

## 🛠️ Integration with `make_config.py`

The Makefile integrates with `make_config.py` for automatic configuration:

```bash
# make_config.py generates make.env with:
# - IMAGE_REPO (from git remote or default)
# - IMAGE_TAG (from git branch/tag)
# - CONTAINER_TOOL (docker or podman)
# - Other derived values

# Makefile includes make.env:
-include make.env

# Then uses variables:
IMAGE_FULL := $(IMAGE_REPO):$(IMAGE_TAG)
```

---

## 📁 File Structure

```
cnpg-mcp/
├── Makefile                          # Build and deployment automation
├── make_config.py                    # Configuration generator
├── make.env                          # Generated configuration (gitignored)
├── Dockerfile                        # Container image definition
├── chart/                            # Helm chart
│   ├── Chart.yaml                    # Chart metadata
│   ├── values.yaml                   # Default configuration
│   ├── README.md                     # Chart documentation
│   └── templates/
│       ├── deployment.yaml           # Deployment resource
│       ├── service.yaml              # Service resource
│       ├── ingress.yaml              # Ingress resource
│       ├── serviceaccount.yaml       # ServiceAccount
│       ├── configmap.yaml            # OIDC configuration
│       ├── rolebinding.yaml          # RBAC binding
│       ├── pdb.yaml                  # PodDisruptionBudget
│       ├── networkpolicy.yaml        # NetworkPolicy
│       ├── hpa.yaml                  # HorizontalPodAutoscaler
│       ├── NOTES.txt                 # Post-install notes
│       ├── _helpers.tpl              # Template helpers
│       └── tests/
│           └── test-connection.yaml  # Helm test
└── HELM_DEPLOYMENT_GUIDE.md         # Deployment guide
```

---

## ✅ Verification

### **Test Chart Locally**

```bash
# Lint chart
helm lint chart/

# Render templates
helm template test-release chart/ --namespace default

# Dry run install
helm install cnpg-mcp chart/ --dry-run --debug
```

### **Test Deployed Service**

```bash
# Port forward
kubectl port-forward svc/cnpg-mcp-cnpg-mcp 3000:3000

# Health check
curl http://localhost:3000/health

# OAuth metadata
curl http://localhost:3000/.well-known/oauth-authorization-server

# MCP endpoint (with token)
./test-inspector.sh --transport http --url http://localhost:3000 --token-file token.txt
```

---

## 🎓 Next Steps

1. **Customize Values**: Edit `values.yaml` or create `values-override.yaml`
2. **Configure OIDC**: Set up your identity provider (see `OIDC_SETUP.md`)
3. **Build Image**: Run `make build-push`
4. **Deploy**: Run `make helm-install`
5. **Monitor**: Use `make k8s-logs` and `make k8s-pods`
6. **Test**: Use port-forward and test-inspector

---

## 📚 Documentation

- **`chart/README.md`** - Helm chart reference
- **`HELM_DEPLOYMENT_GUIDE.md`** - Complete deployment guide
- **`OIDC_SETUP.md`** - OIDC configuration
- **`QUICK_START_HTTP.md`** - HTTP mode quick start
- **`CLAUDE.md`** - Project documentation

---

## 🔒 Security Notes

- Always enable OIDC in production (`oidc.enabled=true`)
- Use TLS for Ingress (cert-manager recommended)
- Configure network policies for traffic isolation
- Use least-privilege RBAC roles
- Set resource limits to prevent resource exhaustion
- Run with non-root user (enforced by default)
- Regular security updates for base image

---

## 💡 Tips

1. **Use `make help`** to see all available commands
2. **Keep `make.env` in `.gitignore`** (it's environment-specific)
3. **Version your values files** in Git (without secrets)
4. **Test in staging** before production deployments
5. **Monitor resource usage** and adjust limits/requests
6. **Use namespaces** to isolate environments
7. **Enable autoscaling** for production workloads
8. **Set up alerts** for pod failures and resource exhaustion

---

## 🐛 Common Issues

### "Image pull failed"
- Ensure image is pushed to registry
- Check `imagePullSecrets` if using private registry
- Verify IMAGE_REPO and IMAGE_TAG in `make.env`

### "OIDC authentication fails"
- Check ConfigMap values: `kubectl get configmap <name> -o yaml`
- Verify OIDC issuer is accessible from pods
- Check pod logs for auth errors

### "RBAC permission denied"
- Verify CloudNativePG roles exist: `kubectl get clusterroles | grep cnpg`
- Check RoleBinding: `kubectl get rolebinding <name> -o yaml`
- Test permissions: `kubectl auth can-i ...`

### "Pod won't start"
- Check events: `kubectl describe pod <pod-name>`
- View logs: `kubectl logs <pod-name>`
- Verify resource limits aren't too low

---

All files are in place and ready to use! 🎉
