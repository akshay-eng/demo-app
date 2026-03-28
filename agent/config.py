import os

# GitHub
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
MANIFESTS_REPO = os.getenv("MANIFESTS_REPO", "akshay-eng/demo-app-manifests")
APP_REPO = os.getenv("APP_REPO", "akshay-eng/demo-app")

# ArgoCD
ARGOCD_SERVER = os.getenv("ARGOCD_SERVER", "https://argocd.local")
ARGOCD_TOKEN = os.getenv("ARGOCD_TOKEN")
ARGOCD_APP_NAME = os.getenv("ARGOCD_APP_NAME", "quest-diagnostics")

# Kubernetes
NAMESPACE = os.getenv("K8S_NAMESPACE", "quest-diagnostics")

# Docker
DOCKERHUB_USERNAME = os.getenv("DOCKERHUB_USERNAME", "ak3hay")
