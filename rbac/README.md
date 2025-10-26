# RBAC Setup Scripts

This directory contains scripts for setting up RBAC permissions for the CloudNativePG MCP server.

## Scripts Overview

### `bind_cnpg_role.py` ⭐ (Recommended)

**Use this when**: You installed CloudNativePG via helm chart.

This script binds existing CloudNativePG ClusterRoles (created by helm) to a ServiceAccount. It's simpler and follows Kubernetes best practices of reusing existing roles.

```bash
# Create ServiceAccount and bind to edit role (recommended)
python bind_cnpg_role.py --namespace default --service-account cnpg-mcp-server

# Options
python bind_cnpg_role.py --namespace default --service-account cnpg-mcp-server --role edit   # Edit access (default)
python bind_cnpg_role.py --namespace default --service-account cnpg-mcp-server --role view   # Read-only
python bind_cnpg_role.py --namespace default --service-account cnpg-mcp-server --role admin  # Full admin

# Dry run
python bind_cnpg_role.py --dry-run

# Delete
python bind_cnpg_role.py --delete
```

**What it does:**
- Creates a ServiceAccount
- Binds to existing `cnpg-cloudnative-pg-{edit|view|admin}` ClusterRole
- Optionally binds to Kubernetes built-in `view` role (for pods, logs, events)

**Requirements:**
- CloudNativePG installed via helm
- Cluster-admin permissions

### `setup_rbac.py` (Legacy/Custom)

**Use this when**: You didn't install CloudNativePG via helm, or need custom RBAC configuration.

This script creates custom ClusterRoles with specific permissions and binds them to a ServiceAccount.

```bash
# Create with cluster-wide permissions
python setup_rbac.py --namespace default --service-account cnpg-mcp-server --scope cluster

# Create with namespace-scoped permissions
python setup_rbac.py --namespace production --service-account cnpg-mcp --scope namespace

# Dry run
python setup_rbac.py --dry-run

# Delete
python setup_rbac.py --delete
```

**What it does:**
- Creates a ServiceAccount
- Creates a custom ClusterRole or Role with CNPG permissions
- Creates a binding between the ServiceAccount and the role

**Requirements:**
- Cluster-admin permissions

## Quick Decision Guide

```
Did you install CloudNativePG via helm?
│
├─ Yes → Use bind_cnpg_role.py (recommended)
│         ✓ Simpler
│         ✓ Reuses existing roles
│         ✓ Best practice
│
└─ No  → Use setup_rbac.py
          ✓ Creates custom roles
          ✓ More control over permissions
          ✓ Works without helm installation
```

## CloudNativePG Roles (Created by Helm)

The helm chart creates these ClusterRoles:

| Role Name | Description | Use Case |
|-----------|-------------|----------|
| `cnpg-cloudnative-pg` | Full admin access | Development/testing only |
| `cnpg-cloudnative-pg-edit` | Create, modify, delete clusters | **Recommended for MCP server** |
| `cnpg-cloudnative-pg-view` | Read-only access | Monitoring, read-only operations |

## Examples

### Example 1: Production setup with edit permissions

```bash
python bind_cnpg_role.py \
  --namespace production \
  --service-account cnpg-mcp-server \
  --role edit
```

### Example 2: Read-only setup for monitoring

```bash
python bind_cnpg_role.py \
  --namespace monitoring \
  --service-account cnpg-monitor \
  --role view
```

### Example 3: Custom RBAC without helm

```bash
python setup_rbac.py \
  --namespace default \
  --service-account cnpg-mcp-server \
  --scope cluster
```

### Example 4: Namespace-scoped permissions

```bash
python setup_rbac.py \
  --namespace production \
  --service-account cnpg-mcp \
  --scope namespace
```

## Verification

After running either script, verify the setup:

```bash
# Check ServiceAccount exists
kubectl get serviceaccount cnpg-mcp-server -n default

# Check CloudNativePG roles exist (if using bind_cnpg_role.py)
kubectl get clusterroles | grep cnpg

# Test permissions
kubectl auth can-i get clusters.postgresql.cnpg.io \
  --as=system:serviceaccount:default:cnpg-mcp-server

kubectl auth can-i create clusters.postgresql.cnpg.io \
  --as=system:serviceaccount:default:cnpg-mcp-server

kubectl auth can-i list pods \
  --as=system:serviceaccount:default:cnpg-mcp-server
```

All should return `yes` if permissions are correctly configured.

## Troubleshooting

### "ClusterRole not found"

If `bind_cnpg_role.py` reports that CloudNativePG roles don't exist:

```bash
# Verify helm installation
helm list -A | grep cnpg

# Check for CNPG roles
kubectl get clusterroles | grep cnpg

# If roles don't exist, install CloudNativePG via helm
helm repo add cloudnative-pg https://cloudnative-pg.github.io/charts
helm install cnpg cloudnative-pg/cloudnative-pg

# Wait for installation to complete
kubectl wait --for=condition=available --timeout=300s deployment/cnpg-controller-manager -n cnpg-system
```

### "Permission denied"

Both scripts require cluster-admin permissions:

```bash
# Check your permissions
kubectl auth can-i create clusterrolebindings

# If permission denied, you need to either:
# 1. Use an account with cluster-admin permissions
# 2. Contact your cluster administrator
# 3. Use namespace-scoped permissions with setup_rbac.py --scope namespace
```

### Script fails to load kubeconfig

```bash
# Verify kubectl is configured
kubectl cluster-info

# Check KUBECONFIG environment variable
echo $KUBECONFIG

# If needed, set it explicitly
export KUBECONFIG=~/.kube/config

# Verify you can access the cluster
kubectl get nodes
```

### ImportError: No module named 'kubernetes'

```bash
# Install dependencies
cd ..  # Go to project root
pip install -r requirements.txt
```

## Alternative: Using kubectl apply

Instead of Python scripts, you can use the provided YAML manifest:

```bash
# From project root
kubectl apply -f rbac.yaml
```

This creates:
- ServiceAccount: `cnpg-mcp-server`
- ClusterRoleBindings to `cnpg-cloudnative-pg-edit` and `view` roles

## See Also

- [Main README](../README.md) - Full project documentation
- [QUICKSTART](../QUICKSTART.md) - Quick start guide
- [CloudNativePG RBAC Documentation](https://cloudnative-pg.io/documentation/current/security/)
- [Kubernetes RBAC](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)
