docker run -d \
  --name cnpg-mcp-manual \
  -v "$(pwd):/workspaces/cnpg-mcp" \
  -v "$HOME/.vscode-projects/cnpg-mcp/claude/.claude:/home/vscode/.claude" \
  -v "$HOME/.vscode-projects/cnpg-mcp/codex:/home/vscode/.codex" \
  -v "$HOME/.vscode-projects/cnpg-mcp/kube-config:/home/vscode/.kube/config" \
  -v "$HOME/.vscode-projects/cnpg-mcp/kube-cache:/home/vscode/.kube/cache" \
  -w /workspaces/cnpg-mcp \
  --user vscode \
  -p 8000:8000 \
  vsc-cnpg-mcp-a104d4c86fa42d9fba27d3ea4d983a19655bf9d8f42d700e1ab7d3dc67b41714 \
  sleep infinity

docker exec cnpg-mcp-manual bash /workspaces/cnpg-mcp/.devcontainer/post-create.sh

