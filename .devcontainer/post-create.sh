#!/bin/bash
set -e

echo "Running post-create setup..."

echo "Fixing npm cache ownership..."
mkdir -p "$HOME/.npm" "$HOME/.cache" "$HOME/.config" "$HOME/.npm-global/bin"
sudo chown -R "$(id -u)":"$(id -g)" "$HOME/.npm" "$HOME/.cache" "$HOME/.config" "$HOME/.npm-global"


# Install Claude Code
echo "Installing Claude Code..."
npm install -g @anthropic-ai/claude-code

# Add other setup commands here as needed
# pip install -r requirements.txt
# go mod download

echo "Post-create setup complete!"
