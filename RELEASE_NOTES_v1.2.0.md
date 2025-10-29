# CloudNativePG MCP Server v1.2.0

Smithery.ai publication release! 🎉

## Overview
MCP server for managing PostgreSQL clusters using CloudNativePG in Kubernetes. Built with FastMCP for simplified development with automatic schema generation.

## Installation

### Via Smithery.ai (Recommended)
```bash
npx @smithery/cli install cnpg-mcp-server --client claude
```

### Via pip
```bash
pip install git+https://github.com/helxplatform/cnpg-mcp.git
cnpg-mcp-server
```

### Manual
```bash
git clone https://github.com/helxplatform/cnpg-mcp.git
cd cnpg-mcp
pip install -r requirements.txt
python cnpg_mcp_server.py
```

## What's New in v1.2.0

### Publication Ready
- ✅ **Smithery.ai configuration** - Published to MCP server registry
- ✅ **Python package setup** - Installable via pip
- ✅ **Clean credentials** - Removed all hardcoded development values
- ✅ **Fixed documentation** - kubectl CLI not required (uses Python client)

### Features (12 Tools)

**Cluster Management (5 tools)**
- `list_postgres_clusters` - List all clusters with optional namespace filtering
- `get_cluster_status` - Get detailed cluster information
- `create_postgres_cluster` - Create HA PostgreSQL clusters
- `scale_postgres_cluster` - Scale cluster instances up/down
- `delete_postgres_cluster` - Delete cluster with automatic secret cleanup

**Role/User Management (4 tools)**
- `list_postgres_roles` - List roles in a cluster
- `create_postgres_role` - Create role with auto-generated password (stored in K8s secret)
- `update_postgres_role` - Update role attributes and password
- `delete_postgres_role` - Delete role and associated secret

**Database Management (3 tools)**
- `list_postgres_databases` - List databases managed by Database CRDs
- `create_postgres_database` - Create database with reclaim policy
- `delete_postgres_database` - Delete Database CRD

### Key Features
- 📊 **JSON Format Output** - 4 tools support structured JSON for programmatic use
- 🔐 **Automatic Secret Management** - Passwords stored in Kubernetes secrets named `cnpg-{cluster}-user-{role}`
- 🧹 **Automatic Cleanup** - Secrets deleted when cluster is deleted (prevents orphaned credentials)
- 🚀 **FastMCP** - Simplified server with auto-generated schemas from type hints
- 🎯 **Smart Defaults** - Automatic namespace inference from Kubernetes context
- ⚡ **Lazy Initialization** - Kubernetes clients initialized on first use

## Requirements
- Kubernetes cluster with CloudNativePG operator installed
- Python 3.11 or higher
- Kubernetes config file (kubeconfig) with cluster access
- Appropriate RBAC permissions (cnpg-cloudnative-pg-edit recommended)

**Note**: kubectl CLI is NOT required - server uses Kubernetes Python client library directly

## Architecture
- **Runtime**: Python 3.11+
- **Framework**: FastMCP (auto-schema generation)
- **Transport**: stdio (local) and HTTP/SSE (remote, ready to use)
- **K8s Client**: kubernetes Python library (no kubectl subprocess calls)
- **Code**: ~1,915 lines, single-file architecture

## Documentation
- **README**: https://github.com/helxplatform/cnpg-mcp/blob/main/README.md
- **Quick Start**: https://github.com/helxplatform/cnpg-mcp/blob/main/QUICKSTART.md
- **Publishing Guide**: https://github.com/helxplatform/cnpg-mcp/blob/main/PUBLISHING.md
- **Developer Guide**: https://github.com/helxplatform/cnpg-mcp/blob/main/CLAUDE.md

## Security
- MIT License
- No hardcoded credentials
- Automatic password generation (16 chars)
- Secrets labeled for easy management
- RBAC-based access control
- Destructive operations require explicit confirmation

## Changes Since v1.1.0
- Added Smithery.ai configuration
- Added Python package setup (setup.py, MANIFEST.in)
- Removed hardcoded development credentials
- Fixed documentation about kubectl requirement
- Enhanced README with multiple installation options
- Improved RBAC examples with generic placeholders

## Upgrade Notes
If upgrading from earlier versions:
- Secret naming convention changed to `cnpg-{cluster}-user-{role}`
- Existing secrets will need to be manually migrated or recreated
- No breaking changes to tool APIs

## Support
- Issues: https://github.com/helxplatform/cnpg-mcp/issues
- Documentation: https://github.com/helxplatform/cnpg-mcp#readme

---

Built with ❤️ by helxplatform
