"""
Agent Tools for Quest Diagnostics SDLC Remediation Agent.
Each tool is a function the agent can invoke to investigate and fix deployment issues.
"""

import json
import re
import yaml
import requests
from datetime import datetime
from kubernetes import client, config as k8s_config
from github import Github
from config import (
    GITHUB_TOKEN, MANIFESTS_REPO, APP_REPO,
    ARGOCD_SERVER, ARGOCD_TOKEN, ARGOCD_APP_NAME,
    NAMESPACE, DOCKERHUB_USERNAME,
)

# ---------- Kubernetes Tools ----------

def k8s_get_pods():
    """Get all pods in the quest-diagnostics namespace with their status."""
    try:
        k8s_config.load_incluster_config()
    except Exception:
        k8s_config.load_kube_config()

    v1 = client.CoreV1Api()
    pods = v1.list_namespaced_pod(namespace=NAMESPACE)

    result = []
    for pod in pods.items:
        container_statuses = []
        if pod.status.container_statuses:
            for cs in pod.status.container_statuses:
                status_detail = {}
                if cs.state.waiting:
                    status_detail = {
                        "state": "waiting",
                        "reason": cs.state.waiting.reason,
                        "message": cs.state.waiting.message,
                    }
                elif cs.state.running:
                    status_detail = {"state": "running"}
                elif cs.state.terminated:
                    status_detail = {
                        "state": "terminated",
                        "reason": cs.state.terminated.reason,
                        "exit_code": cs.state.terminated.exit_code,
                    }

                container_statuses.append({
                    "name": cs.name,
                    "ready": cs.ready,
                    "restart_count": cs.restart_count,
                    "image": cs.image,
                    "status": status_detail,
                })

        result.append({
            "name": pod.metadata.name,
            "phase": pod.status.phase,
            "containers": container_statuses,
        })

    return result


def k8s_get_pod_logs(pod_name, tail_lines=50):
    """Get logs from a specific pod."""
    try:
        k8s_config.load_incluster_config()
    except Exception:
        k8s_config.load_kube_config()

    v1 = client.CoreV1Api()
    try:
        logs = v1.read_namespaced_pod_log(
            name=pod_name,
            namespace=NAMESPACE,
            tail_lines=tail_lines,
        )
        return logs
    except client.exceptions.ApiException as e:
        # If current container has no logs, try previous container
        if "waiting to start" in str(e) or "ContainerCreating" in str(e):
            return "Container is still starting up."
        try:
            logs = v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=NAMESPACE,
                tail_lines=tail_lines,
                previous=True,
            )
            return f"[Previous container logs]\n{logs}"
        except Exception:
            return f"Could not retrieve logs: {str(e)}"


def k8s_get_events():
    """Get recent events in the namespace to understand what's happening."""
    try:
        k8s_config.load_incluster_config()
    except Exception:
        k8s_config.load_kube_config()

    v1 = client.CoreV1Api()
    events = v1.list_namespaced_event(namespace=NAMESPACE)

    result = []
    for event in sorted(events.items, key=lambda e: e.last_timestamp or datetime.min, reverse=True)[:20]:
        result.append({
            "type": event.type,
            "reason": event.reason,
            "message": event.message,
            "object": event.involved_object.name,
            "timestamp": str(event.last_timestamp),
            "count": event.count,
        })

    return result


def k8s_get_deployment_info(deployment_name):
    """Get deployment details including current image and replica status."""
    try:
        k8s_config.load_incluster_config()
    except Exception:
        k8s_config.load_kube_config()

    apps_v1 = client.AppsV1Api()
    dep = apps_v1.read_namespaced_deployment(name=deployment_name, namespace=NAMESPACE)

    containers = []
    for c in dep.spec.template.spec.containers:
        containers.append({"name": c.name, "image": c.image})

    return {
        "name": dep.metadata.name,
        "replicas": dep.spec.replicas,
        "ready_replicas": dep.status.ready_replicas or 0,
        "updated_replicas": dep.status.updated_replicas or 0,
        "available_replicas": dep.status.available_replicas or 0,
        "containers": containers,
        "conditions": [
            {"type": c.type, "status": c.status, "reason": c.reason, "message": c.message}
            for c in (dep.status.conditions or [])
        ],
    }


# ---------- ArgoCD Tools ----------

def argocd_get_app_status():
    """Get the current ArgoCD application status and sync info."""
    headers = {"Authorization": f"Bearer {ARGOCD_TOKEN}"}
    url = f"{ARGOCD_SERVER}/api/v1/applications/{ARGOCD_APP_NAME}"

    try:
        resp = requests.get(url, headers=headers, verify=False, timeout=10)
        resp.raise_for_status()
        app = resp.json()

        return {
            "name": app["metadata"]["name"],
            "sync_status": app["status"]["sync"]["status"],
            "health_status": app["status"]["health"]["status"],
            "revision": app["status"]["sync"].get("revision", "unknown"),
            "source_repo": app["spec"]["source"]["repoURL"],
            "source_path": app["spec"]["source"]["path"],
            "target_revision": app["spec"]["source"]["targetRevision"],
        }
    except Exception as e:
        return {"error": str(e)}


def argocd_get_app_history():
    """Get deployment history from ArgoCD to find recent deployments."""
    headers = {"Authorization": f"Bearer {ARGOCD_TOKEN}"}
    url = f"{ARGOCD_SERVER}/api/v1/applications/{ARGOCD_APP_NAME}"

    try:
        resp = requests.get(url, headers=headers, verify=False, timeout=10)
        resp.raise_for_status()
        app = resp.json()

        history = []
        for entry in app.get("status", {}).get("history", [])[-5:]:
            history.append({
                "id": entry.get("id"),
                "revision": entry.get("revision"),
                "deployed_at": entry.get("deployedAt"),
                "source": entry.get("source", {}).get("repoURL"),
            })

        return history
    except Exception as e:
        return {"error": str(e)}


def argocd_sync_app():
    """Trigger an ArgoCD sync to redeploy the application."""
    headers = {
        "Authorization": f"Bearer {ARGOCD_TOKEN}",
        "Content-Type": "application/json",
    }
    url = f"{ARGOCD_SERVER}/api/v1/applications/{ARGOCD_APP_NAME}/sync"

    try:
        resp = requests.post(url, headers=headers, verify=False, timeout=30, json={})
        resp.raise_for_status()
        return {"status": "sync triggered", "message": "ArgoCD sync initiated successfully"}
    except Exception as e:
        return {"error": str(e)}


# ---------- GitHub Tools ----------

def github_get_recent_commits(repo_name=None, count=5):
    """Get recent commits from a GitHub repository."""
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(repo_name or APP_REPO)
    commits = repo.get_commits()[:count]

    result = []
    for c in commits:
        result.append({
            "sha": c.sha[:8],
            "full_sha": c.sha,
            "message": c.commit.message,
            "author": c.commit.author.name,
            "date": str(c.commit.author.date),
            "files_changed": [f.filename for f in c.files] if c.files else [],
        })

    return result


def github_get_file_content(file_path, repo_name=None):
    """Read a file from the GitHub repository."""
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(repo_name or MANIFESTS_REPO)
    file = repo.get_contents(file_path)
    return file.decoded_content.decode("utf-8")


def github_get_manifest_image_tag(deployment_file="base/backend-deployment.yaml"):
    """Get the current image tag from a K8s deployment manifest in the manifests repo."""
    content = github_get_file_content(deployment_file, MANIFESTS_REPO)
    match = re.search(r"image:\s*(\S+)", content)
    if match:
        return match.group(1)
    return None


def github_update_manifest_image(deployment_file, new_image_tag, commit_message=None):
    """Update the image tag in a K8s manifest file in the manifests repo."""
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(MANIFESTS_REPO)
    file = repo.get_contents(deployment_file)
    content = file.decoded_content.decode("utf-8")

    # Replace the image line
    updated_content = re.sub(
        r"(image:\s*\S+/\S+:)\S+",
        f"\\g<1>{new_image_tag}",
        content,
    )

    if content == updated_content:
        return {"status": "no_change", "message": "Image tag is already set to the target value"}

    if not commit_message:
        commit_message = f"Rollback: revert image tag to {new_image_tag} (auto-remediation)"

    repo.update_file(
        path=deployment_file,
        message=commit_message,
        content=updated_content,
        sha=file.sha,
    )

    return {"status": "updated", "file": deployment_file, "new_tag": new_image_tag}


def github_get_commit_diff(commit_sha, repo_name=None):
    """Get the diff/changes for a specific commit."""
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(repo_name or APP_REPO)
    commit = repo.get_commit(commit_sha)

    files = []
    for f in commit.files:
        files.append({
            "filename": f.filename,
            "status": f.status,
            "additions": f.additions,
            "deletions": f.deletions,
            "patch": f.patch[:500] if f.patch else None,
        })

    return {
        "sha": commit.sha[:8],
        "message": commit.commit.message,
        "files": files,
    }


def github_get_previous_image_tag(deployment_file="base/backend-deployment.yaml"):
    """Get the previous image tag from git history of the manifests repo."""
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(MANIFESTS_REPO)
    commits = repo.get_commits(path=deployment_file)

    # Skip the latest commit (current broken one), get the one before
    commit_list = list(commits[:3])
    if len(commit_list) < 2:
        return None

    previous_commit = commit_list[1]
    file = repo.get_contents(deployment_file, ref=previous_commit.sha)
    content = file.decoded_content.decode("utf-8")

    match = re.search(r"image:\s*(\S+)", content)
    if match:
        full_image = match.group(1)
        tag = full_image.split(":")[-1] if ":" in full_image else "latest"
        return tag

    return None


# ---------- Tool Registry ----------
# This maps tool names to functions for the agent to call

TOOL_REGISTRY = {
    "k8s_get_pods": {
        "function": k8s_get_pods,
        "description": "List all pods in quest-diagnostics namespace with their status, restart counts, and images",
    },
    "k8s_get_pod_logs": {
        "function": k8s_get_pod_logs,
        "description": "Get logs from a specific pod to understand why it's failing",
        "params": ["pod_name"],
    },
    "k8s_get_events": {
        "function": k8s_get_events,
        "description": "Get recent Kubernetes events to understand cluster-level issues",
    },
    "k8s_get_deployment_info": {
        "function": k8s_get_deployment_info,
        "description": "Get deployment details including current image and replica status",
        "params": ["deployment_name"],
    },
    "argocd_get_app_status": {
        "function": argocd_get_app_status,
        "description": "Get current ArgoCD application sync and health status",
    },
    "argocd_get_app_history": {
        "function": argocd_get_app_history,
        "description": "Get ArgoCD deployment history to check for recent deployments",
    },
    "argocd_sync_app": {
        "function": argocd_sync_app,
        "description": "Trigger ArgoCD to re-sync the application after a fix",
    },
    "github_get_recent_commits": {
        "function": github_get_recent_commits,
        "description": "Get recent commits from the app source code repository",
    },
    "github_get_manifest_image_tag": {
        "function": github_get_manifest_image_tag,
        "description": "Get the current image tag from the K8s deployment manifest",
    },
    "github_update_manifest_image": {
        "function": github_update_manifest_image,
        "description": "Update the image tag in the manifests repo to rollback or fix",
        "params": ["deployment_file", "new_image_tag"],
    },
    "github_get_commit_diff": {
        "function": github_get_commit_diff,
        "description": "Get the code changes in a specific commit to identify the bug",
        "params": ["commit_sha"],
    },
    "github_get_previous_image_tag": {
        "function": github_get_previous_image_tag,
        "description": "Get the last known good image tag from manifests git history",
    },
}
