## syntax=docker/dockerfile:1
FROM mcr.microsoft.com/devcontainers/base:ubuntu

# Add anything you ALWAYS want baked in (keep minimal)
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl git vim net-tools gnupg bash-completion

RUN install -m 0755 -d /etc/apt/keyrings; \
  curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.30/deb/Release.key \
    | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg; \
  echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.30/deb/ /" \
    > /etc/apt/sources.list.d/kubernetes.list; \
  apt-get update && apt-get install -y --no-install-recommends kubectl; \
  kubectl completion bash > /etc/bash_completion.d/kubectl

# The base image already has user `vscode` with passwordless sudo.
USER vscode
ENV HOME=/home/vscode
ENV PATH=/home/vscode/.local/bin:/home/vscode/go/bin:$PATH
