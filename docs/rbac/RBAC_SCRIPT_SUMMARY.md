# RBAC Setup Script - Implementation Summary

## Overview

Created a comprehensive Python script (`setup_rbac.py`) to automate Kubernetes RBAC setup for the CloudNativePG MCP server, replacing the need to manually edit and apply YAML files.

## What Was Added

### 1. Main Script: `setup_rbac.py`

**Features:**
- ✅ Creates ServiceAccount, Role/ClusterRole, and RoleBinding/ClusterRoleBinding
- ✅ Parameterized via CLI arguments (namespace, service-account, scope)
- ✅ **Context-aware**: Automatically detects current namespace from kubectl context
- ✅ Supports both cluster-wide and namespace-scoped permissions
- ✅ Dry-run mode to preview changes
- ✅ Idempotent - safe to run multiple times
- ✅ Teardown support (`--delete` flag)
- ✅ Interactive confirmation before deletion
- ✅ Clear error messages with helpful hints
- ✅ Permission checking and validation

**Lines of code:** ~800 lines (including comprehensive error handling and documentation)

### 2. Documentation: `RBAC_SETUP_GUIDE.md`

**Sections:**
- Overview and features
- Installation instructions
- Usage examples (basic and advanced)
- Command-line options reference
- Permission scopes comparison (cluster vs namespace)
- Verification steps
- Troubleshooting guide
- Security best practices
- Integration examples

**Length:** ~400 lines

### 3. Updated Documentation

**Modified files:**
- `README.md` - Added RBAC setup script section
- `QUICKSTART.md` - Updated Step 2 to recommend the script

## Usage Examples

### Basic Usage

```bash
# Default setup (uses current context's namespace, cluster-wide access)
python setup_rbac.py

# Custom namespace and service account
python setup_rbac.py \
  --namespace production \
  --service-account cnpg-mcp

# Namespace-scoped (more restrictive)
python setup_rbac.py \
  --namespace dev \
  --scope namespace

# Dry-run first
python setup_rbac.py --dry-run

# Clean up
python setup_rbac.py --delete
```

### Command-Line Options

```
--namespace <name>         Kubernetes namespace (default: from current context)
--service-account <name>   Service account name (default: cnpg-mcp-server)
--scope <cluster|namespace> Permission scope (default: cluster)
--dry-run                  Preview without applying
--delete                   Remove resources
```

**Context-aware:** The namespace defaults to your current kubectl context, making it seamless to work across different environments.

## Architecture

```
setup_rbac.py
│
├── Resource Definitions
│   ├── get_service_account()
│   ├── get_cluster_role()
│   ├── get_role()
│   ├── get_cluster_role_binding()
│   └── get_role_binding()
│
├── RBACManager Class
│   ├── create_service_account()
│   ├── create_cluster_role()
│   ├── create_role()
│   ├── create_cluster_role_binding()
│   ├── create_role_binding()
│   ├── delete_service_account()
│   ├── delete_cluster_role()
│   ├── delete_role()
│   ├── delete_cluster_role_binding()
│   └── delete_role_binding()
│
├── Orchestration Functions
│   ├── setup_rbac()
│   └── teardown_rbac()
│
└── CLI Entry Point
    ├── parse_args()
    └── main()
```

## Benefits Over Static YAML

| Feature | YAML Files | Python Script |
|---------|------------|---------------|
| **Customization** | Edit files manually | Pass CLI arguments |
| **Multiple environments** | Copy/edit files | Same script, different args |
| **Validation** | At apply time | Before creation |
| **Error handling** | kubectl errors | Custom helpful messages |
| **Idempotency** | kubectl handles | Script checks first |
| **Dry-run** | `kubectl --dry-run` | `--dry-run` flag |
| **Cleanup** | Manual deletion | `--delete` flag |
| **Confirmation** | No | Yes (for deletion) |
| **Reusability** | Low | High |

## Example Workflow

### Development Environment

```bash
# Setup
python setup_rbac.py --namespace dev --scope namespace

# Verify
kubectl auth can-i list clusters.postgresql.cnpg.io \
  --as=system:serviceaccount:dev:cnpg-mcp-server

# Use in deployment
kubectl set serviceaccount deployment/cnpg-mcp-server cnpg-mcp-server -n dev
```

### Production Environment

```bash
# Preview first
python setup_rbac.py \
  --namespace production \
  --service-account cnpg-mcp-prod \
  --scope cluster \
  --dry-run

# Apply
python setup_rbac.py \
  --namespace production \
  --service-account cnpg-mcp-prod \
  --scope cluster

# Verify
kubectl get clusterrole cnpg-mcp-prod-role -o yaml
```

### Multiple Namespaces

```bash
# Create namespace-scoped access for each environment
for ns in dev staging prod; do
  python setup_rbac.py \
    --namespace $ns \
    --service-account cnpg-mcp-$ns \
    --scope namespace
done
```

### Cleanup

```bash
# Remove resources
python setup_rbac.py --delete

# Or for specific environment
python setup_rbac.py \
  --namespace dev \
  --service-account cnpg-mcp-dev \
  --delete
```

## Error Handling

The script provides helpful error messages with suggestions:

### Example: Insufficient Permissions

```
✗ Failed to create ClusterRole cnpg-mcp-server-role: Forbidden
  Hint: You need cluster-admin permissions to create ClusterRoles
```

Suggestion: Use `--scope namespace` instead

### Example: Already Exists

```
✓ ServiceAccount default/cnpg-mcp-server already exists
✓ ClusterRole cnpg-mcp-server-role already exists
✓ ClusterRoleBinding cnpg-mcp-server-binding already exists

✓ RBAC setup completed successfully!
```

The script is idempotent - running it multiple times is safe.

## Verification Steps Built-in

After successful setup, the script suggests verification commands:

```
✓ RBAC setup completed successfully!

Next steps:
  1. Use the service account in your MCP server deployment:
     serviceAccountName: cnpg-mcp-server
  2. Verify permissions:
     kubectl auth can-i list clusters.postgresql.cnpg.io \
       --as=system:serviceaccount:default:cnpg-mcp-server
```

## Integration Points

### With MCP Server Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cnpg-mcp-server
spec:
  template:
    spec:
      serviceAccountName: cnpg-mcp-server  # Created by script
      containers:
      - name: mcp-server
        image: cnpg-mcp-server:latest
```

### With CI/CD Pipelines

```bash
#!/bin/bash
# deploy.sh

# Setup RBAC
python setup_rbac.py \
  --namespace $ENVIRONMENT \
  --service-account cnpg-mcp-$ENVIRONMENT \
  --scope namespace

# Deploy application
kubectl apply -f deployment.yaml -n $ENVIRONMENT
```

### With Terraform/Infrastructure as Code

```python
# Can be wrapped in Terraform's local-exec provisioner
resource "null_resource" "rbac_setup" {
  provisioner "local-exec" {
    command = "python setup_rbac.py --namespace ${var.namespace}"
  }
}
```

## Testing

```bash
# Syntax check
python -m py_compile setup_rbac.py

# Dry-run test
python setup_rbac.py --dry-run

# Full test cycle
python setup_rbac.py --namespace test-ns --dry-run
python setup_rbac.py --namespace test-ns
kubectl get serviceaccount -n test-ns
python setup_rbac.py --namespace test-ns --delete
```

## Security Considerations

The script implements several security best practices:

1. **Least privilege**: Supports namespace-scoped permissions
2. **Explicit confirmation**: Requires "yes" before deletion
3. **Audit trail**: Clear output of all operations
4. **No hardcoded credentials**: Uses kubeconfig authentication
5. **Dry-run mode**: Test before applying
6. **Idempotent operations**: Safe to run multiple times

## Comparison: Script vs Manual YAML

### Time Savings

**Manual YAML approach:**
1. Edit rbac.yaml file (2-3 minutes)
2. Replace namespace/service-account values
3. Apply: `kubectl apply -f rbac.yaml`
4. Verify each resource
5. If mistake: edit and reapply

**Script approach:**
```bash
python setup_rbac.py --namespace prod --service-account cnpg-mcp-prod
```
Done in one command (10 seconds).

### Error Reduction

**Manual YAML:**
- Typos in namespace/service-account names
- Forgot to update all occurrences
- Wrong scope (cluster vs namespace)

**Script:**
- Parameters validated
- Consistent naming
- Clear scope selection

## Future Enhancements

Possible improvements for the script:

1. **Configuration file support**: Load settings from YAML/JSON
2. **Backup existing resources**: Before modification
3. **Custom permission rules**: Via config file
4. **Multiple service accounts**: Batch creation
5. **Resource quotas**: Check before creation
6. **Webhook integration**: Notify on changes
7. **Prometheus metrics**: Track RBAC operations

## Summary

The RBAC setup script provides:

✅ **Automation**: One command instead of editing YAML  
✅ **Flexibility**: Different params for different environments  
✅ **Safety**: Dry-run and confirmation before changes  
✅ **Reliability**: Idempotent and error-resistant  
✅ **Usability**: Clear messages and helpful hints  
✅ **Maintainability**: Single source of truth for RBAC config  

**Result**: Faster, safer, and more consistent RBAC setup for CloudNativePG MCP server deployments.

## Files Added/Modified

**New files:**
- `setup_rbac.py` (executable script, 800 lines)
- `RBAC_SETUP_GUIDE.md` (comprehensive documentation, 400 lines)

**Modified files:**
- `README.md` (added RBAC script section)
- `QUICKSTART.md` (updated Step 2)

**Total addition:** ~1,200 lines of code and documentation

## Quick Reference Card

```bash
# SETUP
python setup_rbac.py                              # Cluster-wide, default
python setup_rbac.py --scope namespace            # Namespace-scoped
python setup_rbac.py --namespace prod             # Custom namespace
python setup_rbac.py --dry-run                    # Preview only

# VERIFY
kubectl get serviceaccount cnpg-mcp-server
kubectl auth can-i list clusters.postgresql.cnpg.io \
  --as=system:serviceaccount:default:cnpg-mcp-server

# CLEANUP
python setup_rbac.py --delete                     # Remove resources
python setup_rbac.py --delete --dry-run           # Preview deletion

# HELP
python setup_rbac.py --help                       # Show all options
```
