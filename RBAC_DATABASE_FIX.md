# Database RBAC Permissions Fix

## Problem
User `jeffw@renci.org` has permissions for `clusters.postgresql.cnpg.io` but not for `databases.postgresql.cnpg.io` in the `jeffw` namespace.

## Root Cause
The CloudNativePG helm-installed ClusterRoles may not include permissions for the Database CRD (a newer feature), or the user's existing role bindings don't cover database resources.

## Solution

A **cluster administrator** needs to apply RBAC permissions. Choose one of the options below:

### Option 1: Namespace-scoped permissions for specific user (Quick Fix)

Apply the provided `rbac-database.yaml`:

```bash
kubectl apply -f rbac-database.yaml
```

This grants `jeffw@renci.org` full permissions for Database CRDs in the `jeffw` namespace.

### Option 2: Check/Update CloudNativePG ClusterRoles (Cluster-wide Fix)

1. **Check if CloudNativePG ClusterRoles include databases:**
   ```bash
   kubectl get clusterrole cnpg-cloudnative-pg-edit -o yaml | grep -A5 databases
   ```

2. **If databases are NOT included**, create a ClusterRole supplement:

   ```yaml
   # cnpg-database-permissions.yaml
   apiVersion: rbac.authorization.k8s.io/v1
   kind: ClusterRole
   metadata:
     name: cnpg-database-admin
     labels:
       app.kubernetes.io/name: cloudnative-pg
   rules:
     - apiGroups: ["postgresql.cnpg.io"]
       resources: ["databases"]
       verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]

   ---
   # Bind to users who need database access
   apiVersion: rbac.authorization.k8s.io/v1
   kind: ClusterRoleBinding
   metadata:
     name: jeffw-database-admin
   subjects:
     - kind: User
       name: jeffw@renci.org
       apiGroup: rbac.authorization.k8s.io
   roleRef:
     kind: ClusterRole
     name: cnpg-database-admin
     apiGroup: rbac.authorization.k8s.io
   ```

3. **Apply:**
   ```bash
   kubectl apply -f cnpg-database-permissions.yaml
   ```

### Option 3: Aggregate to existing CloudNativePG roles

If you want database permissions to automatically apply to anyone with CloudNativePG edit permissions:

```yaml
# cnpg-database-aggregate.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: cnpg-database-permissions
  labels:
    # This label makes it aggregate into the cnpg-cloudnative-pg-edit role
    cnpg.io/aggregate-to-edit: "true"
rules:
  - apiGroups: ["postgresql.cnpg.io"]
    resources: ["databases"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

**Note:** This requires the CloudNativePG ClusterRoles to use aggregation. Check with:
```bash
kubectl get clusterrole cnpg-cloudnative-pg-edit -o yaml | grep aggregationRule
```

## Verification

After applying the fix, verify permissions:

```bash
# Check if user can now list databases
kubectl auth can-i list databases.postgresql.cnpg.io -n jeffw --as=jeffw@renci.org

# Should return: yes
```

## For Other Users

If other users need database permissions:
- **Option 1**: Add them to `rbac-database.yaml` subjects list
- **Option 2**: Use ClusterRole/ClusterRoleBinding (Option 2 or 3 above)

## Related Resources
- CloudNativePG Database CRD docs: https://cloudnative-pg.io/documentation/current/database/
- CloudNativePG RBAC: https://cloudnative-pg.io/documentation/current/security/
