# Quick Start Guide

Get your CloudNativePG MCP Server running in 5 minutes!

## Prerequisites Checklist

- [ ] Kubernetes cluster is running
- [ ] kubectl is configured (`kubectl get nodes` works)
- [ ] Python 3.9+ is installed
- [ ] CloudNativePG operator is installed

## Step 1: Install CloudNativePG Operator (if not already installed)

```bash
kubectl apply -f https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.22/releases/cnpg-1.22.0.yaml
```

Verify installation:
```bash
kubectl get deployment -n cnpg-system cnpg-controller-manager
```

## Step 2: Set Up RBAC Permissions

### Option A: Using the Setup Script (Recommended)

```bash
# Quick setup (automatically uses your current context's namespace)
python setup_rbac.py

# Or customize for your environment
python setup_rbac.py \
  --namespace production \
  --service-account cnpg-mcp \
  --scope namespace

# Preview changes first (dry-run)
python setup_rbac.py --dry-run
```

**Tip:** The script detects your current namespace from kubectl context:
```bash
# Check current namespace
kubectl config view --minify --output 'jsonpath={..namespace}'

# Switch namespace
kubectl config set-context --current --namespace=production

# Run setup (uses production namespace)
python setup_rbac.py
```

Verify:
```bash
kubectl get serviceaccount cnpg-mcp-server
kubectl auth can-i list clusters.postgresql.cnpg.io \
  --as=system:serviceaccount:default:cnpg-mcp-server
```

### Option B: Using YAML Files

```bash
kubectl apply -f rbac.yaml
```

Verify:
```bash
kubectl get serviceaccount cnpg-mcp-server
kubectl get clusterrole cnpg-mcp-role
```

For more details, see [RBAC_SETUP_GUIDE.md](RBAC_SETUP_GUIDE.md).

## Step 3: Install Python Dependencies

```bash
pip install -r requirements.txt
```

## Step 4: Test the Server

Run a quick syntax check:
```bash
python -m py_compile cnpg_mcp_server.py
```

## Step 5: Create a Test Cluster

Deploy an example cluster:
```bash
kubectl apply -f example-cluster.yaml
```

Wait for it to become ready (this may take 2-3 minutes):
```bash
kubectl get cluster example-cluster -w
```

Press Ctrl+C when status shows "Cluster in healthy state"

## Step 6: Run the MCP Server

### Option A: With Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cloudnative-pg": {
      "command": "python",
      "args": ["/absolute/path/to/cnpg_mcp_server.py"]
    }
  }
}
```

Restart Claude Desktop.

### Option B: Standalone (for testing)

```bash
# The server will run and wait for MCP requests
python cnpg_mcp_server.py
```

## Step 7: Test with Claude

Try these prompts in Claude:

1. **List clusters:**
   ```
   List all PostgreSQL clusters
   ```

2. **Check status:**
   ```
   Get detailed status for the example-cluster in default namespace
   ```

3. **Create a new cluster:**
   ```
   Create a new PostgreSQL cluster named 'test-db' in default namespace with 1 instance
   ```

4. **Scale:**
   ```
   Scale the test-db cluster to 3 instances
   ```

## Common Issues

### "ModuleNotFoundError: No module named 'mcp'"

```bash
pip install --upgrade mcp
```

### "Unable to connect to the server"

Check kubectl connectivity:
```bash
kubectl cluster-info
export KUBECONFIG=~/.kube/config
```

### "Forbidden: User cannot list clusters"

Apply RBAC permissions:
```bash
kubectl apply -f rbac.yaml
```

Verify:
```bash
kubectl auth can-i list clusters.postgresql.cnpg.io --as=system:serviceaccount:default:cnpg-mcp-server
```

### Server appears to hang

This is normal - the server waits for MCP requests. Run in background or use Claude Desktop.

## Next Steps

1. **Read the full README** for advanced configuration
2. **Explore tool functions** in `cnpg_mcp_server.py`
3. **Add custom tools** for your specific workflows
4. **Deploy to Kubernetes** using `kubernetes-deployment.yaml`
5. **Set up backups** following CloudNativePG documentation

## Useful Commands

```bash
# Watch cluster status
kubectl get clusters -A -w

# View cluster details
kubectl describe cluster example-cluster

# Check operator logs
kubectl logs -n cnpg-system deployment/cnpg-controller-manager

# Get connection information
kubectl get secret example-cluster-app -o jsonpath='{.data.password}' | base64 -d

# Access PostgreSQL
kubectl exec -it example-cluster-1 -- psql -U app app
```

## Learning Resources

- [CloudNativePG Documentation](https://cloudnative-pg.io/documentation/current/)
- [MCP Protocol](https://modelcontextprotocol.io/)
- [Kubernetes Python Client](https://github.com/kubernetes-client/python)

## Support

For issues or questions:
1. Check the troubleshooting section in README.md
2. Review CloudNativePG operator logs
3. Verify RBAC permissions
4. Test kubectl connectivity

Happy clustering! 🐘🚀
