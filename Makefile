# Makefile for CloudNativePG MCP Server
# Builds and pushes container images

# Default target
.PHONY: all
all: config build

# Include auto-generated configuration from make_config.py
-include make.env

# Default values (overridden by make.env)
REGISTRY ?= ghcr.io/your-org
IMAGE_NAME ?= cnpg-mcp-server
TAG ?= latest
PLATFORM ?= linux/amd64
CONTAINER_TOOL ?= docker
HELM_RELEASE ?= cnpg-mcp
HELM_NAMESPACE ?= default

# Derived values - construct full image name from REGISTRY and IMAGE_NAME
IMAGE_FULL := $(REGISTRY)/$(IMAGE_NAME):$(TAG)

#
# Configuration targets
#

.PHONY: config
config: make.env ## Generate make.env configuration file

make.env:
	@echo "Generating make.env configuration..."
	python3 make_config.py
	@echo "Configuration generated. Edit make.env to customize settings."

.PHONY: config-show
config-show: make.env ## Show current configuration
	@echo "Current Configuration:"
	@echo "  REGISTRY:      $(REGISTRY)"
	@echo "  IMAGE_NAME:    $(IMAGE_NAME)"
	@echo "  TAG:           $(TAG)"
	@echo "  IMAGE_FULL:    $(IMAGE_FULL)"
	@echo "  PLATFORM:      $(PLATFORM)"
	@echo "  CONTAINER_TOOL: $(CONTAINER_TOOL)"
	@echo "  HELM_RELEASE:  $(HELM_RELEASE)"
	@echo "  HELM_NAMESPACE: $(HELM_NAMESPACE)"

#
# Container build targets
#

.PHONY: build
build: make.env ## Build container image
	@echo "Building container image: $(IMAGE_FULL)"
	$(CONTAINER_TOOL) build --tag $(IMAGE_FULL) --platform $(PLATFORM) --file Dockerfile .
	@echo "✓ Built: $(IMAGE_FULL)"

.PHONY: build-no-cache
build-no-cache: make.env ## Build container image without cache
	@echo "Building container image (no cache): $(IMAGE_FULL)"
	$(CONTAINER_TOOL) build \
		--no-cache \
		--tag $(IMAGE_FULL) \
		--platform $(PLATFORM) \
		--file Dockerfile \
		.
	@echo "✓ Built: $(IMAGE_FULL)"

.PHONY: push
push: make.env ## Push container image to registry
	@echo "Pushing container image: $(IMAGE_FULL)"
	$(CONTAINER_TOOL) push $(IMAGE_FULL)
	@echo "✓ Pushed: $(IMAGE_FULL)"

.PHONY: build-push
build-push: build push ## Build and push container image

.PHONY: test-image
test-image: make.env ## Test container image locally
	@echo "Testing container image: $(IMAGE_FULL)"
	@echo "Starting container in HTTP mode (insecure - no OIDC)..."
	@echo "Press Ctrl+C to stop"
	$(CONTAINER_TOOL) run --rm -it \
		-p 4204:4204 \
		--name cnpg-mcp-test \
		$(IMAGE_FULL)

#
# Helm chart targets
#

.PHONY: helm-lint
helm-lint: ## Lint Helm chart
	@echo "Linting Helm chart..."
	helm lint chart/

.PHONY: helm-template
helm-template: ## Render Helm chart templates
	@echo "Rendering Helm chart templates..."
	helm template $(HELM_RELEASE) chart/ \
		--namespace $(HELM_NAMESPACE) \
		--set image.repository=$(REGISTRY)/$(IMAGE_NAME) \
		--set image.tag=$(TAG)

.PHONY: helm-install
helm-install: make.env ## Install Helm chart
	@echo "Installing Helm chart: $(HELM_RELEASE)"
	helm upgrade --install $(HELM_RELEASE) chart/ \
		--namespace $(HELM_NAMESPACE) \
		--create-namespace \
		--set image.repository=$(REGISTRY)/$(IMAGE_NAME) \
		--set image.tag=$(TAG) \
		--wait
	@echo "✓ Installed: $(HELM_RELEASE) in namespace $(HELM_NAMESPACE)"

.PHONY: helm-upgrade
helm-upgrade: make.env ## Upgrade Helm release
	@echo "Upgrading Helm release: $(HELM_RELEASE)"
	helm upgrade $(HELM_RELEASE) chart/ \
		--namespace $(HELM_NAMESPACE) \
		--set image.repository=$(REGISTRY)/$(IMAGE_NAME) \
		--set image.tag=$(TAG) \
		--wait
	@echo "✓ Upgraded: $(HELM_RELEASE)"

.PHONY: helm-uninstall
helm-uninstall: ## Uninstall Helm release
	@echo "Uninstalling Helm release: $(HELM_RELEASE)"
	helm uninstall $(HELM_RELEASE) --namespace $(HELM_NAMESPACE)
	@echo "✓ Uninstalled: $(HELM_RELEASE)"

.PHONY: helm-status
helm-status: ## Show Helm release status
	helm status $(HELM_RELEASE) --namespace $(HELM_NAMESPACE)

.PHONY: helm-values
helm-values: ## Show Helm values
	@echo "Default values:"
	@cat chart/values.yaml
	@echo ""
	@echo "Deployed values (if installed):"
	@helm get values $(HELM_RELEASE) --namespace $(HELM_NAMESPACE) 2>/dev/null || echo "Not installed"

#
# Development targets
#

.PHONY: dev-start-http
dev-start-http: ## Start server in HTTP mode (local development)
	@echo "Starting server in HTTP mode..."
	./start-http.sh

.PHONY: dev-test-stdio
dev-test-stdio: ## Test server with stdio transport
	@echo "Testing server with stdio transport..."
	./test-inspector.sh --transport stdio

.PHONY: dev-test-http
dev-test-http: ## Test server with HTTP transport
	@echo "Testing server with HTTP transport..."
	@echo "Note: Requires server to be running (make dev-start-http)"
	./test-inspector.sh --transport http --url http://localhost:4204

#
# Kubernetes development targets
#

.PHONY: k8s-logs
k8s-logs: ## Show logs from deployed pods
	@echo "Logs from $(HELM_RELEASE):"
	kubectl logs -n $(HELM_NAMESPACE) -l app.kubernetes.io/name=cnpg-mcp --tail=100 -f

.PHONY: k8s-pods
k8s-pods: ## Show deployed pods
	kubectl get pods -n $(HELM_NAMESPACE) -l app.kubernetes.io/name=cnpg-mcp

.PHONY: k8s-describe
k8s-describe: ## Describe deployed resources
	kubectl describe deployment -n $(HELM_NAMESPACE) -l app.kubernetes.io/name=cnpg-mcp
	kubectl describe service -n $(HELM_NAMESPACE) -l app.kubernetes.io/name=cnpg-mcp

.PHONY: k8s-port-forward
k8s-port-forward: ## Port forward to deployed service
	@echo "Port forwarding to $(HELM_RELEASE) service..."
	@echo "Access at: http://localhost:4204"
	@echo "Health: http://localhost:4204/healthz"
	@echo "MCP: http://localhost:4204/mcp"
	kubectl port-forward -n $(HELM_NAMESPACE) svc/$(HELM_RELEASE)-cnpg-mcp 4204:4204

.PHONY: k8s-shell
k8s-shell: ## Open shell in deployed pod
	@POD=$$(kubectl get pods -n $(HELM_NAMESPACE) -l app.kubernetes.io/name=cnpg-mcp -o jsonpath='{.items[0].metadata.name}'); \
	echo "Opening shell in pod: $$POD"; \
	kubectl exec -it -n $(HELM_NAMESPACE) $$POD -- /bin/bash

#
# Utility targets
#

.PHONY: clean
clean: ## Clean generated files
	@echo "Cleaning generated files..."
	rm -f make.env
	@echo "✓ Cleaned"

.PHONY: help
help: ## Show this help message
	@echo "CloudNativePG MCP Server - Makefile"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Configuration:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -E '^(config|config-show):' | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Container Build:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -E '^(build|push|build-push|build-no-cache|test-image):' | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Helm Chart:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -E '^helm-' | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Development:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -E '^dev-' | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Kubernetes:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -E '^k8s-' | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Utility:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -E '^(clean|help):' | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Quick Start:"
	@echo "  1. make config          # Generate configuration"
	@echo "  2. Edit make.env        # Customize settings"
	@echo "  3. make build           # Build container image"
	@echo "  4. make push            # Push to registry"
	@echo "  5. make helm-install    # Deploy to Kubernetes"
