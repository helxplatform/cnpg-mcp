# Publishing Guide for cnpg-mcp-server

This guide explains how to publish the CloudNativePG MCP server to various platforms.

## Publishing to Smithery.ai

[Smithery.ai](https://smithery.ai) is the official registry for MCP servers. Publishing here makes it easy for users to discover and install your server.

### Prerequisites

1. GitHub repository with the code
2. `smithery.json` configuration file (already created)
3. Smithery.ai account

### Steps

1. **Ensure all files are committed**:
   ```bash
   git add smithery.json setup.py README.md requirements.txt
   git commit -m "Prepare for Smithery.ai publication"
   git push origin main
   ```

2. **Visit Smithery.ai**:
   - Go to https://smithery.ai
   - Click "Submit Server" or "Add Server"
   - Provide your GitHub repository URL

3. **Smithery will validate**:
   - Checks for `smithery.json`
   - Validates the configuration
   - Verifies requirements.txt exists
   - Confirms the entrypoint is valid

4. **Once approved**, users can install with:
   ```bash
   npx @smithery/cli install cnpg-mcp-server --client claude
   ```

### What Smithery.ai Provides

- **Automatic installation**: Handles dependencies and configuration
- **Version management**: Users can update easily
- **Discovery**: Makes your server searchable
- **Documentation**: Auto-generates install instructions
- **Analytics**: Track usage and downloads

## Publishing to PyPI (Optional)

For users who prefer pip installation:

### Prerequisites

1. PyPI account (register at https://pypi.org)
2. `twine` installed: `pip install twine build`

### Steps

1. **Build the package**:
   ```bash
   python -m build
   ```

   This creates:
   - `dist/cnpg-mcp-server-1.0.0.tar.gz` (source distribution)
   - `dist/cnpg_mcp_server-1.0.0-py3-none-any.whl` (wheel)

2. **Test upload to TestPyPI** (recommended first):
   ```bash
   python -m twine upload --repository testpypi dist/*
   ```

3. **Upload to PyPI**:
   ```bash
   python -m twine upload dist/*
   ```

4. **Verify installation**:
   ```bash
   pip install cnpg-mcp-server
   cnpg-mcp-server --help
   ```

### Updating the Package

1. Update version in `setup.py` and `smithery.json`
2. Rebuild: `python -m build`
3. Upload: `python -m twine upload dist/*`

## GitHub Release

Create a GitHub release for each version:

1. **Tag the version**:
   ```bash
   git tag -a v1.0.0 -m "Release v1.0.0"
   git push origin v1.0.0
   ```

2. **Create GitHub Release**:
   - Go to repository → Releases → "Create a new release"
   - Choose the tag (v1.0.0)
   - Add release notes
   - Attach the distribution files if desired

### Release Notes Template

```markdown
## CloudNativePG MCP Server v1.0.0

### Features
- 12 comprehensive tools for PostgreSQL cluster management
- Role/user management with automatic password generation
- Database management via CloudNativePG CRDs
- Optional JSON format output
- Automatic secret cleanup on cluster deletion

### Installation

Via Smithery.ai:
\```bash
npx @smithery/cli install cnpg-mcp-server --client claude
\```

Via pip:
\```bash
pip install cnpg-mcp-server
\```

### Requirements
- Kubernetes cluster with CloudNativePG operator
- Python 3.11+
- kubectl configured

### Changes in this release
- Initial public release
- FastMCP migration complete
- JSON format support added
- Secret cleanup implemented
```

## Docker Hub (Optional)

For containerized deployments:

1. **Build the image**:
   ```bash
   docker build -t helxplatform/cnpg-mcp-server:1.0.0 .
   docker build -t helxplatform/cnpg-mcp-server:latest .
   ```

2. **Push to Docker Hub**:
   ```bash
   docker login
   docker push helxplatform/cnpg-mcp-server:1.0.0
   docker push helxplatform/cnpg-mcp-server:latest
   ```

3. **Users can run**:
   ```bash
   docker run -v ~/.kube/config:/root/.kube/config \
     helxplatform/cnpg-mcp-server:latest
   ```

## Pre-Publication Checklist

Before publishing, ensure:

- [ ] All tests pass
- [ ] README.md is up to date
- [ ] smithery.json has correct version and URLs
- [ ] setup.py has correct version
- [ ] LICENSE file is present (MIT)
- [ ] CHANGELOG.md documents changes (optional)
- [ ] requirements.txt is current
- [ ] Example files are included (example-cluster.yaml, rbac.yaml)
- [ ] Documentation is clear and comprehensive
- [ ] No sensitive information in code or configs
- [ ] .gitignore excludes build artifacts

## Post-Publication

After publishing:

1. **Update the README badge** (optional):
   ```markdown
   [![Smithery.ai](https://img.shields.io/badge/smithery.ai-available-blue)](https://smithery.ai/server/cnpg-mcp-server)
   ```

2. **Announce**:
   - Post on relevant forums/communities
   - Tweet about it
   - Update CloudNativePG community

3. **Monitor**:
   - Watch GitHub issues
   - Respond to user questions
   - Track usage metrics from Smithery

## Versioning Strategy

Follow [Semantic Versioning](https://semver.org):

- **MAJOR** (1.0.0): Breaking changes
- **MINOR** (1.1.0): New features, backward compatible
- **PATCH** (1.0.1): Bug fixes, backward compatible

Example release cycle:
- v1.0.0 - Initial release
- v1.0.1 - Bug fix for secret cleanup
- v1.1.0 - Add backup management tools
- v2.0.0 - Change tool API (breaking)

## Support and Maintenance

After publishing:

- Respond to GitHub issues within 48 hours
- Release patch versions for critical bugs
- Plan feature releases quarterly
- Keep dependencies updated
- Maintain compatibility with latest CloudNativePG

## License Compliance

This project uses MIT License:
- ✅ Commercial use allowed
- ✅ Modification allowed
- ✅ Distribution allowed
- ✅ Private use allowed
- ⚠️ Must include copyright notice
- ⚠️ Must include license text

Ensure all contributions maintain MIT compatibility.
