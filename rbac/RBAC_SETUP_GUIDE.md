# RBAC Setup Script Documentation

The `setup_rbac.py` script automates the creation and management of Kubernetes RBAC resources for the CloudNativePG MCP server.

## Overview

Instead of manually applying YAML files, this script programmatically creates:
- **ServiceAccount**: Identity for the MCP server
- **Role/ClusterRole**: Permissions for CloudNativePG operations
- **RoleBinding/ClusterRoleBinding**: Binding the service account to the role

## Features

✅ **Parameterized**: Customize namespace, service account name, and scope  
✅ **Idempotent**: Safe to run multiple times (checks if resources exist)  
✅ **Dry-run mode**: Preview changes before applying  
✅ **Teardown support**: Clean removal of RBAC resources  
✅ **Error handling**: Clear error messages and permission hints  
✅ **Interactive**: Confirms before deleting resources  

## Installation

The script uses the same dependencies as the MCP server:

```bash
pip install kubernetes
```

## Usage

### Context-Aware Namespace Detection

The script automatically detects your current Kubernetes context's namespace, making it easier to work with different environments:

```bash
# Check your current namespace
kubectl config view --minify --output 'jsonpath={..namespace}'

# Switch to a different namespace
kubectl config set-context --current --namespace=production

# Run setup (will use production namespace)
python setup_rbac.py

# Or explicitly override
python setup_rbac.py --namespace staging
```

**Example workflow:**
```bash
# Work in dev environment
kubectl config set-context --current --namespace=dev
python setup_rbac.py  # Creates resources in 'dev'

# Work in production
kubectl config set-context --current --namespace=production
python setup_rbac.py  # Creates resources in 'production'
```

### Basic Setup (Cluster-Wide Permissions)

Create RBAC resources with default settings:

```bash
# Uses current context's namespace (or 'default' if not set)
python setup_rbac.py
```

The script automatically detects your current Kubernetes context namespace. You can check your current namespace with:
```bash
kubectl config view --minify --output 'jsonpath={..namespace}'
```

This creates:
- ServiceAccount: `<current-namespace>/cnpg-mcp-server`
- ClusterRole: `cnpg-mcp-server-role`
- ClusterRoleBinding: `cnpg-mcp-server-binding`

### Custom Namespace and Service Account

```bash
python setup_rbac.py \
  --namespace production \
  --service-account postgres-mcp
```

### Namespace-Scoped Permissions

For limiting access to a single namespace:

```bash
python setup_rbac.py \
  --namespace production \
  --service-account cnpg-mcp-server \
  --scope namespace
```

This creates Role and RoleBinding instead of ClusterRole/ClusterRoleBinding.

### Dry Run (Preview Changes)

See what would be created without actually creating it:

```bash
python setup_rbac.py --dry-run
```

Example output:
```
============================================================
CloudNativePG MCP Server - RBAC Setup
============================================================

Configuration:
  Namespace: default
  Service Account: cnpg-mcp-server
  Scope: cluster
  Dry Run: True

[DRY RUN] Would create ServiceAccount: default/cnpg-mcp-server

[DRY RUN] Would create ClusterRole: cnpg-mcp-server-role

[DRY RUN] Would create ClusterRoleBinding: cnpg-mcp-server-binding
  Subject: ServiceAccount default/cnpg-mcp-server
  Role: ClusterRole cnpg-mcp-server-role
```

### Delete RBAC Resources

Remove all created resources:

```bash
python setup_rbac.py --delete
```

You'll be prompted for confirmation:
```
Are you sure you want to delete these RBAC resources? (yes/no): yes
```

### Dry Run Deletion

Preview what would be deleted:

```bash
python setup_rbac.py --delete --dry-run
```

## Command-Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--namespace` | *from context* | Kubernetes namespace for ServiceAccount (inferred from current kubectl context) |
| `--service-account` | `cnpg-mcp-server` | Name of the ServiceAccount |
| `--scope` | `cluster` | Permission scope: `cluster` or `namespace` |
| `--dry-run` | `false` | Preview without making changes |
| `--delete` | `false` | Delete resources instead of creating |

**Note:** The namespace is automatically detected from your current Kubernetes context. Use `kubectl config view --minify` to see your current context settings.

## Permission Scopes

### Cluster-Wide (`--scope cluster`)

**Creates:**
- ClusterRole (cluster-scoped)
- ClusterRoleBinding (cluster-scoped)

**Allows:**
- ✅ Access to CloudNativePG resources in **all namespaces**
- ✅ Simpler for multi-namespace deployments
- ✅ Better for shared MCP server

**Requires:**
- Cluster-admin or equivalent permissions

**Use when:**
- Managing clusters across multiple namespaces
- Running a shared team MCP server
- You have cluster-admin access

### Namespace-Scoped (`--scope namespace`)

**Creates:**
- Role (namespace-scoped)
- RoleBinding (namespace-scoped)

**Allows:**
- ✅ Access to CloudNativePG resources in **one namespace only**
- ✅ More restrictive (principle of least privilege)
- ✅ Suitable for isolated environments

**Requires:**
- Admin permissions in the target namespace

**Use when:**
- Managing clusters in a single namespace
- You don't have cluster-admin access
- Following strict security policies
- Testing in isolated namespace

## Examples

### Example 1: Development Environment

```bash
# Create cluster-wide access in default namespace
python setup_rbac.py

# Verify permissions
kubectl auth can-i list clusters.postgresql.cnpg.io \
  --as=system:serviceaccount:default:cnpg-mcp-server
```

### Example 2: Production Environment

```bash
# Create namespace-scoped access in production
python setup_rbac.py \
  --namespace production \
  --service-account cnpg-mcp-prod \
  --scope namespace

# Test with dry-run first
python setup_rbac.py \
  --namespace production \
  --service-account cnpg-mcp-prod \
  --scope namespace \
  --dry-run
```

### Example 3: Multiple Namespaces

```bash
# Set up for production namespace
python setup_rbac.py \
  --namespace production \
  --service-account cnpg-mcp-server \
  --scope cluster

# Set up for staging namespace (same service account, already has cluster role)
python setup_rbac.py \
  --namespace staging \
  --service-account cnpg-mcp-server \
  --scope cluster
```

### Example 4: Cleanup

```bash
# Remove all RBAC resources
python setup_rbac.py --delete

# Or for specific namespace
python setup_rbac.py \
  --namespace production \
  --service-account cnpg-mcp-prod \
  --delete
```

## Verification

After running the script, verify the permissions:

### Check ServiceAccount

```bash
kubectl get serviceaccount cnpg-mcp-server -n default
```

### Check Role/ClusterRole

```bash
# For cluster-wide
kubectl get clusterrole cnpg-mcp-server-role

# For namespace-scoped
kubectl get role cnpg-mcp-server-role -n production
```

### Check Binding

```bash
# For cluster-wide
kubectl get clusterrolebinding cnpg-mcp-server-binding

# For namespace-scoped
kubectl get rolebinding cnpg-mcp-server-binding -n production
```

### Test Permissions

```bash
# Check if the service account can list clusters
kubectl auth can-i list clusters.postgresql.cnpg.io \
  --as=system:serviceaccount:default:cnpg-mcp-server

# Check if it can create clusters
kubectl auth can-i create clusters.postgresql.cnpg.io \
  --as=system:serviceaccount:default:cnpg-mcp-server \
  --namespace production
```

## Troubleshooting

### Error: "Failed to load Kubernetes config"

**Problem**: Script can't connect to Kubernetes cluster.

**Solutions:**
```bash
# Verify kubectl works
kubectl cluster-info

# Check KUBECONFIG
echo $KUBECONFIG

# Try explicit kubeconfig
export KUBECONFIG=~/.kube/config
python setup_rbac.py
```

### Error: "403 Forbidden" or "You need cluster-admin permissions"

**Problem**: Your user doesn't have sufficient permissions.

**Solutions:**
```bash
# Check your permissions
kubectl auth can-i create clusterroles

# For namespace-scoped (requires less permissions)
python setup_rbac.py --scope namespace

# Or ask cluster admin to run the script
```

### Error: "Already exists"

**Problem**: Resources already exist (this is usually fine).

**Solution:**
The script will skip existing resources and report success. If you want to recreate:

```bash
# Delete first
python setup_rbac.py --delete

# Then recreate
python setup_rbac.py
```

### Warning: Resources Exist But Permissions Don't Work

**Problem**: Resources exist but permissions still fail.

**Diagnosis:**
```bash
# Check the role has correct rules
kubectl get clusterrole cnpg-mcp-server-role -o yaml

# Check the binding is correct
kubectl get clusterrolebinding cnpg-mcp-server-binding -o yaml

# Test specific permission
kubectl auth can-i list clusters.postgresql.cnpg.io \
  --as=system:serviceaccount:default:cnpg-mcp-server
```

**Solution:**
```bash
# Delete and recreate
python setup_rbac.py --delete
python setup_rbac.py
```

## Integration with MCP Server

### Using with Claude Desktop

After running the setup script, configure the MCP server to use the service account:

```json
{
  "mcpServers": {
    "cloudnative-pg": {
      "command": "python",
      "args": ["/path/to/cnpg_mcp_server.py"],
      "env": {
        "KUBECONFIG": "/path/to/.kube/config"
      }
    }
  }
}
```

The MCP server will automatically use your kubeconfig, which should have access to the cluster.

### Using in Kubernetes Deployment

Update your deployment to use the service account:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cnpg-mcp-server
spec:
  template:
    spec:
      serviceAccountName: cnpg-mcp-server  # Use the created service account
      containers:
      - name: mcp-server
        image: your-registry/cnpg-mcp-server:latest
```

## Security Best Practices

1. **Use namespace-scoped permissions** when possible (principle of least privilege)
2. **Regularly audit** RBAC permissions:
   ```bash
   kubectl get clusterrolebinding cnpg-mcp-server-binding -o yaml
   ```
3. **Rotate service accounts** periodically
4. **Monitor usage** via audit logs
5. **Use separate service accounts** for different environments (dev, staging, prod)
6. **Delete unused RBAC resources**:
   ```bash
   python setup_rbac.py --delete
   ```

## Advanced Usage

### Multiple Service Accounts

Create separate service accounts for different purposes:

```bash
# Read-only service account
python setup_rbac.py \
  --service-account cnpg-mcp-readonly \
  --scope namespace

# Admin service account (modify script rules as needed)
python setup_rbac.py \
  --service-account cnpg-mcp-admin
```

### Custom Role Rules

To customize permissions, edit the `get_cluster_role()` or `get_role()` functions in the script:

```python
def get_cluster_role(name: str) -> Dict[str, Any]:
    return {
        # ... existing code ...
        "rules": [
            # Add or modify rules here
            {
                "apiGroups": ["postgresql.cnpg.io"],
                "resources": ["clusters"],
                "verbs": ["get", "list"]  # Read-only
            }
        ]
    }
```

### Environment-Specific Setup

Use environment variables for configuration:

```bash
#!/bin/bash
# setup-dev.sh
export NAMESPACE="dev"
export SERVICE_ACCOUNT="cnpg-mcp-dev"

python setup_rbac.py \
  --namespace "$NAMESPACE" \
  --service-account "$SERVICE_ACCOUNT" \
  --scope namespace
```

## Comparison with YAML Approach

| Aspect | YAML (`kubectl apply`) | Python Script |
|--------|----------------------|---------------|
| **Flexibility** | Static | Parameterized |
| **Reusability** | Manual editing | CLI arguments |
| **Idempotency** | kubectl handles | Script handles |
| **Validation** | At apply time | Before creation |
| **Dry-run** | `kubectl apply --dry-run` | `--dry-run` flag |
| **Cleanup** | Manual deletion | `--delete` flag |
| **Customization** | Edit files | Pass parameters |
| **Error handling** | kubectl messages | Custom messages |

## Summary

The RBAC setup script provides:
- ✅ **Easy parameterization** for different environments
- ✅ **Dry-run mode** for safe testing
- ✅ **Idempotent operations** (safe to re-run)
- ✅ **Clear error messages** with helpful hints
- ✅ **Both creation and cleanup** in one tool
- ✅ **Flexible scope** (cluster-wide or namespace-scoped)

**Quick Start:**
```bash
# Setup
python setup_rbac.py

# Verify
kubectl auth can-i list clusters.postgresql.cnpg.io \
  --as=system:serviceaccount:default:cnpg-mcp-server

# Clean up (if needed)
python setup_rbac.py --delete
```
