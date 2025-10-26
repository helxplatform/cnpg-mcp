## syntax=docker/dockerfile:1
FROM mcr.microsoft.com/devcontainers/base:ubuntu

# Add anything you ALWAYS want baked in (keep minimal)
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl git vim net-tools

# The base image already has user `vscode` with passwordless sudo.
USER vscode
ENV HOME=/home/vscode
ENV PATH=/home/vscode/.local/bin:/home/vscode/go/bin:$PATH
