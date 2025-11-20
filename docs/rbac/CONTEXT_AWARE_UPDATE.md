# Context-Aware Namespace Feature - Update Summary

## Overview

Updated the `setup_rbac.py` script to automatically detect and use the current Kubernetes context's namespace as the default, making it more intuitive and reducing the need for explicit `--namespace` flags.

## What Changed

### 1. **New Function: `get_current_namespace()`**

Added a helper function that reads the current namespace from the active Kubernetes context:

```python
def get_current_namespace() -> str:
    """
    Get the current namespace from the Kubernetes context.
    
    Returns:
        Current namespace from context, or 'default' if not set.
    """
    try:
        contexts, active_context = config.list_kube_config_contexts()
        
        if not active_context:
            return "default"
        
        namespace = active_context.get('context', {}).get('namespace')
        
        if namespace:
            return namespace
        
        return "default"
        
    except Exception:
        return "default"
```

### 2. **Updated `parse_args()` Function**

Modified to use the current context namespace as the dynamic default:

**Before:**
```python
parser.add_argument(
    "--namespace",
    default="default",
    help="Kubernetes namespace for the service account (default: default)"
)
```

**After:**
```python
current_namespace = get_current_namespace()

parser.add_argument(
    "--namespace",
    default=current_namespace,
    help=f"Kubernetes namespace for the service account (default: inferred from context, currently '{current_namespace}')"
)
```

### 3. **Enhanced Help Text**

The help output now shows:
- The current context's namespace
- Examples without explicit namespace flags
- Information that the namespace is auto-detected

Example help output:
```
Current context namespace: production

Examples:
  # Setup with cluster-wide permissions (uses current context namespace)
  python setup_rbac.py
  
  # Setup with explicit namespace
  python setup_rbac.py --namespace staging
```

## Benefits

### ✅ **More Intuitive Workflow**

Before:
```bash
# Had to specify namespace explicitly
kubectl config set-context --current --namespace=production
python setup_rbac.py --namespace production
```

After:
```bash
# Just switch context, script follows
kubectl config set-context --current --namespace=production
python setup_rbac.py  # Automatically uses 'production'
```

### ✅ **Fewer Arguments Needed**

```bash
# Old way - verbose
python setup_rbac.py --namespace dev
python setup_rbac.py --namespace staging  
python setup_rbac.py --namespace production

# New way - concise
kubectl config set-context --current --namespace=dev
python setup_rbac.py

kubectl config set-context --current --namespace=staging
python setup_rbac.py

kubectl config set-context --current --namespace=production
python setup_rbac.py
```

### ✅ **Context Awareness**

The script now follows Kubernetes best practices by respecting the current context, just like `kubectl` does:

```bash
# Check current context
kubectl config current-context

# Check current namespace
kubectl config view --minify --output 'jsonpath={..namespace}'

# Script automatically uses the same namespace
python setup_rbac.py --dry-run
```

### ✅ **Still Fully Overridable**

You can always explicitly specify a namespace:

```bash
# Use current context's namespace
python setup_rbac.py

# Override with explicit namespace
python setup_rbac.py --namespace other-namespace
```

## Usage Examples

### Example 1: Multi-Environment Setup

```bash
# Setup RBAC for dev environment
kubectl config set-context --current --namespace=dev
python setup_rbac.py --service-account cnpg-mcp-dev

# Setup for staging
kubectl config set-context --current --namespace=staging  
python setup_rbac.py --service-account cnpg-mcp-staging

# Setup for production
kubectl config set-context --current --namespace=production
python setup_rbac.py --service-account cnpg-mcp-prod
```

### Example 2: Quick Test

```bash
# Create test namespace and switch to it
kubectl create namespace test-rbac
kubectl config set-context --current --namespace=test-rbac

# Setup RBAC (automatically in test-rbac)
python setup_rbac.py

# Verify
kubectl get serviceaccount -n test-rbac

# Cleanup
python setup_rbac.py --delete
kubectl config set-context --current --namespace=default
kubectl delete namespace test-rbac
```

### Example 3: Check Before Running

```bash
# See what namespace would be used
python setup_rbac.py --help | grep "Current context namespace"

# Or use dry-run to see the configuration
python setup_rbac.py --dry-run

# Output shows:
# Configuration:
#   Namespace: production  <-- from your current context
#   Service Account: cnpg-mcp-server
#   Scope: cluster
```

## Fallback Behavior

The function gracefully handles edge cases:

1. **No kubeconfig found**: Returns `"default"`
2. **No active context**: Returns `"default"`
3. **No namespace in context**: Returns `"default"`
4. **Any exception**: Returns `"default"`

This ensures the script always works, even in unusual environments.

## Integration with kubectl

The script now behaves consistently with kubectl commands:

```bash
# kubectl respects current context
kubectl get pods  # Lists pods in current namespace

# Our script does too
python setup_rbac.py  # Creates resources in current namespace

# Both can be overridden
kubectl get pods -n other-ns
python setup_rbac.py --namespace other-ns
```

## Checking Your Current Namespace

Multiple ways to see what namespace the script will use:

```bash
# Method 1: View context
kubectl config view --minify

# Method 2: Get just the namespace
kubectl config view --minify --output 'jsonpath={..namespace}'

# Method 3: Check the help text
python setup_rbac.py --help

# Method 4: Use dry-run
python setup_rbac.py --dry-run
```

## Documentation Updates

Updated all documentation files to reflect the context-aware behavior:

### Files Modified:

1. **setup_rbac.py**
   - Added `get_current_namespace()` function
   - Updated `parse_args()` to use dynamic default
   - Enhanced help text with current namespace info

2. **RBAC_SETUP_GUIDE.md**
   - Added "Context-Aware Namespace Detection" section
   - Updated command-line options table
   - Added examples showing context switching

3. **README.md**
   - Updated quick setup examples
   - Mentioned context-aware behavior

4. **QUICKSTART.md**
   - Added tip about context detection
   - Showed how to check/switch namespaces

5. **RBAC_SCRIPT_SUMMARY.md**
   - Updated feature list
   - Updated command-line options
   - Added note about context-aware behavior

## Backward Compatibility

✅ **Fully backward compatible**

Old scripts and commands still work:

```bash
# Old way still works
python setup_rbac.py --namespace production

# New way is just shorter
kubectl config set-context --current --namespace=production
python setup_rbac.py
```

## Testing

### Manual Test Scenarios

1. **Default context (no namespace set)**
   ```bash
   kubectl config set-context --current --namespace=
   python setup_rbac.py --dry-run
   # Should use 'default'
   ```

2. **Context with namespace**
   ```bash
   kubectl config set-context --current --namespace=production
   python setup_rbac.py --dry-run
   # Should use 'production'
   ```

3. **Override with flag**
   ```bash
   kubectl config set-context --current --namespace=production
   python setup_rbac.py --namespace staging --dry-run
   # Should use 'staging' (override)
   ```

4. **No kubeconfig**
   ```bash
   unset KUBECONFIG
   python setup_rbac.py --dry-run
   # Should fallback to 'default'
   ```

## Comparison: Before vs After

### Before (Explicit Namespace Required)

```bash
# Working in production
kubectl get clusters -n production
kubectl describe cluster main-db -n production

# Setup RBAC (must remember to specify namespace)
python setup_rbac.py --namespace production

# Easy to forget and create in wrong namespace!
python setup_rbac.py  # Oops, went to 'default'
```

### After (Context-Aware)

```bash
# Working in production
kubectl config set-context --current --namespace=production
kubectl get clusters  # Already in production context
kubectl describe cluster main-db  # No -n needed

# Setup RBAC (automatically uses production)
python setup_rbac.py  # Creates in production ✓
```

## Best Practices

### 1. Set Context Before Running

```bash
# Good practice: explicitly set context first
kubectl config set-context --current --namespace=production
python setup_rbac.py
```

### 2. Verify Before Applying

```bash
# Always use dry-run first
python setup_rbac.py --dry-run

# Check the configuration section shows correct namespace
# Then run for real
python setup_rbac.py
```

### 3. Use Explicit Namespace for Automation

In CI/CD scripts, be explicit for clarity:

```bash
#!/bin/bash
# CI/CD script - be explicit for clarity
python setup_rbac.py \
  --namespace "$ENVIRONMENT" \
  --service-account "cnpg-mcp-$ENVIRONMENT"
```

## Summary

**Key Changes:**
- ✅ Added `get_current_namespace()` function
- ✅ Updated default namespace to be context-aware
- ✅ Enhanced help text to show current namespace
- ✅ Updated all documentation

**Benefits:**
- 🎯 More intuitive - follows kubectl conventions
- ⚡ Faster - fewer flags to type
- 🔒 Safer - works in the namespace you're already using
- 🔄 Compatible - old explicit flags still work

**Result:**
The script now feels like a native part of the Kubernetes toolchain, automatically respecting your current context while still allowing explicit overrides when needed.

## Quick Reference

```bash
# Check current namespace
kubectl config view --minify --output 'jsonpath={..namespace}'

# Switch namespace
kubectl config set-context --current --namespace=production

# Run setup (uses production automatically)
python setup_rbac.py

# Or override
python setup_rbac.py --namespace staging

# Preview with current context
python setup_rbac.py --dry-run
```

**Pro tip:** Use `kubectl config set-context --current --namespace=<ns>` frequently to stay in the right context, and the script will just work!
