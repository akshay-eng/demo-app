"""
Quest Diagnostics SDLC Remediation Agent.

This agent receives Prometheus alerts when pods are crash-looping,
investigates the root cause, and automatically remediates by rolling
back to the last known good deployment.

Flow:
  1. Receive alert (Prometheus webhook or manual trigger)
  2. Check K8s pods → identify which pods are failing
  3. Get pod logs → understand the error
  4. Check ArgoCD history → was there a recent deployment?
  5. Check GitHub commits → what changed?
  6. Determine root cause → app bug from recent deployment
  7. Get previous good image tag from manifests history
  8. Update manifests repo with the good image tag
  9. Trigger ArgoCD sync
  10. Verify pods are healthy
  11. Notify user with full incident summary
"""

import json
import time
import logging
from datetime import datetime

from tools import (
    k8s_get_pods,
    k8s_get_pod_logs,
    k8s_get_events,
    k8s_get_deployment_info,
    argocd_get_app_status,
    argocd_get_app_history,
    argocd_sync_app,
    github_get_recent_commits,
    github_get_manifest_image_tag,
    github_update_manifest_image,
    github_get_commit_diff,
    github_get_previous_image_tag,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("remediation-agent")


class RemediationAgent:
    def __init__(self):
        self.incident_log = []
        self.start_time = None

    def log_step(self, step, action, result, tool_used=None):
        entry = {
            "step": step,
            "action": action,
            "tool_used": tool_used,
            "result_summary": result,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self.incident_log.append(entry)
        logger.info(f"Step {step}: {action}")
        logger.info(f"  Tool: {tool_used or 'N/A'}")
        logger.info(f"  Result: {result}")

    def investigate_and_remediate(self, alert_data=None):
        """Main agent loop: investigate the issue and fix it."""
        self.start_time = datetime.utcnow()
        self.incident_log = []

        logger.info("=" * 60)
        logger.info("REMEDIATION AGENT ACTIVATED")
        logger.info("=" * 60)

        if alert_data:
            logger.info(f"Alert received: {json.dumps(alert_data, indent=2)}")

        # ---- Step 1: Check pod status ----
        self.log_step(1, "Checking pod status in quest-diagnostics namespace", "", "k8s_get_pods")
        pods = k8s_get_pods()

        crashing_pods = []
        healthy_pods = []
        for pod in pods:
            for container in pod.get("containers", []):
                if container.get("restart_count", 0) > 2 or container.get("status", {}).get("state") == "waiting":
                    crashing_pods.append(pod)
                    break
            else:
                if pod["phase"] == "Running":
                    healthy_pods.append(pod)

        if not crashing_pods:
            self.log_step(1, "No crashing pods found", "All pods are healthy. No action needed.")
            return self.generate_report("no_action")

        crash_summary = ", ".join([p["name"] for p in crashing_pods])
        self.log_step(1, "Identified crashing pods", f"Crashing: {crash_summary}", "k8s_get_pods")

        # ---- Step 2: Get logs from crashing pod ----
        crash_pod_name = crashing_pods[0]["name"]
        self.log_step(2, f"Getting logs from crashing pod: {crash_pod_name}", "", "k8s_get_pod_logs")
        logs = k8s_get_pod_logs(crash_pod_name)
        error_snippet = logs[-500:] if len(logs) > 500 else logs
        self.log_step(2, "Retrieved pod logs", f"Error: {error_snippet[:200]}...", "k8s_get_pod_logs")

        # ---- Step 3: Get K8s events ----
        self.log_step(3, "Checking Kubernetes events for context", "", "k8s_get_events")
        events = k8s_get_events()
        warning_events = [e for e in events if e["type"] == "Warning"]
        self.log_step(3, "Retrieved events", f"Found {len(warning_events)} warning events", "k8s_get_events")

        # ---- Step 4: Identify which deployment is affected ----
        # Determine from pod name which deployment it belongs to
        deployment_name = None
        if "backend" in crash_pod_name:
            deployment_name = "quest-lab-backend"
            deployment_file = "base/backend-deployment.yaml"
        elif "frontend" in crash_pod_name:
            deployment_name = "quest-lab-frontend"
            deployment_file = "base/frontend-deployment.yaml"
        else:
            deployment_name = crash_pod_name.rsplit("-", 2)[0]
            deployment_file = f"base/{deployment_name}-deployment.yaml"

        self.log_step(4, f"Checking deployment: {deployment_name}", "", "k8s_get_deployment_info")
        dep_info = k8s_get_deployment_info(deployment_name)
        current_image = dep_info["containers"][0]["image"] if dep_info["containers"] else "unknown"
        self.log_step(
            4, "Got deployment info",
            f"Image: {current_image}, Ready: {dep_info['ready_replicas']}/{dep_info['replicas']}",
            "k8s_get_deployment_info",
        )

        # ---- Step 5: Check ArgoCD for recent deployments ----
        self.log_step(5, "Checking ArgoCD for recent deployment history", "", "argocd_get_app_history")
        try:
            argo_history = argocd_get_app_history()
            argo_status = argocd_get_app_status()
            self.log_step(
                5, "ArgoCD status retrieved",
                f"Health: {argo_status.get('health_status')}, Sync: {argo_status.get('sync_status')}",
                "argocd_get_app_status",
            )
        except Exception as e:
            self.log_step(5, "ArgoCD check failed (continuing)", str(e), "argocd_get_app_history")
            argo_history = []

        # ---- Step 6: Check recent commits for the breaking change ----
        self.log_step(6, "Checking recent commits in app repository", "", "github_get_recent_commits")
        try:
            recent_commits = github_get_recent_commits()
            if recent_commits:
                latest_commit = recent_commits[0]
                self.log_step(
                    6, "Found recent commits",
                    f"Latest: [{latest_commit['sha']}] {latest_commit['message']}",
                    "github_get_recent_commits",
                )

                # Check what changed in the latest commit
                diff = github_get_commit_diff(latest_commit["full_sha"])
                changed_files = [f["filename"] for f in diff.get("files", [])]
                self.log_step(
                    6, "Analyzed commit diff",
                    f"Files changed: {', '.join(changed_files)}",
                    "github_get_commit_diff",
                )
        except Exception as e:
            self.log_step(6, "GitHub check failed (continuing)", str(e), "github_get_recent_commits")

        # ---- Step 7: Root cause determination ----
        root_cause = (
            f"Recent deployment of {deployment_name} with image {current_image} "
            f"is causing CrashLoopBackOff. Pod logs indicate: {error_snippet[:200]}"
        )
        self.log_step(7, "Root cause determined", root_cause, "analysis")

        # ---- Step 8: Get the previous good image tag ----
        self.log_step(8, "Looking up last known good image tag", "", "github_get_previous_image_tag")
        previous_tag = github_get_previous_image_tag(deployment_file)

        if not previous_tag:
            self.log_step(8, "Could not find previous image tag", "Manual intervention required", None)
            return self.generate_report("manual_intervention_needed")

        self.log_step(8, f"Found previous stable tag: {previous_tag}", "", "github_get_previous_image_tag")

        # ---- Step 9: Update manifests repo with the good tag ----
        self.log_step(
            9, f"Rolling back {deployment_file} to image tag: {previous_tag}",
            "", "github_update_manifest_image",
        )
        update_result = github_update_manifest_image(
            deployment_file=deployment_file,
            new_image_tag=previous_tag,
            commit_message=f"Auto-rollback: revert {deployment_name} to {previous_tag} due to CrashLoopBackOff",
        )
        self.log_step(9, "Manifests repo updated", json.dumps(update_result), "github_update_manifest_image")

        # ---- Step 10: Trigger ArgoCD sync ----
        self.log_step(10, "Triggering ArgoCD sync to deploy rollback", "", "argocd_sync_app")
        try:
            sync_result = argocd_sync_app()
            self.log_step(10, "ArgoCD sync triggered", json.dumps(sync_result), "argocd_sync_app")
        except Exception as e:
            self.log_step(10, "ArgoCD sync failed — ArgoCD auto-sync will pick up the change", str(e), "argocd_sync_app")

        # ---- Step 11: Wait and verify ----
        self.log_step(11, "Waiting 30s for rollback to complete...", "", "wait")
        time.sleep(30)

        pods_after = k8s_get_pods()
        crashing_after = [
            p for p in pods_after
            for c in p.get("containers", [])
            if c.get("restart_count", 0) > 2 or c.get("status", {}).get("state") == "waiting"
        ]

        if not crashing_after:
            self.log_step(11, "VERIFICATION: All pods are now healthy!", "Remediation successful", "k8s_get_pods")
            return self.generate_report("resolved")
        else:
            self.log_step(11, "VERIFICATION: Some pods still crashing", "May need more time or manual intervention", "k8s_get_pods")
            return self.generate_report("partial")

    def generate_report(self, outcome):
        """Generate a full incident report."""
        duration = (datetime.utcnow() - self.start_time).total_seconds() if self.start_time else 0

        report = {
            "incident_id": f"INC-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            "outcome": outcome,
            "duration_seconds": round(duration, 1),
            "timestamp": datetime.utcnow().isoformat(),
            "steps_taken": len(self.incident_log),
            "log": self.incident_log,
        }

        logger.info("=" * 60)
        logger.info(f"INCIDENT REPORT: {report['incident_id']}")
        logger.info(f"Outcome: {outcome}")
        logger.info(f"Duration: {duration:.1f}s")
        logger.info(f"Steps: {len(self.incident_log)}")
        logger.info("=" * 60)

        for entry in self.incident_log:
            logger.info(f"  [{entry['step']}] {entry['action']}")
            if entry.get("tool_used"):
                logger.info(f"       Tool: {entry['tool_used']}")
            logger.info(f"       Result: {entry['result_summary'][:150]}")

        return report
