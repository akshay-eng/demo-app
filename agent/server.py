"""
Webhook server that receives Prometheus AlertManager alerts
and triggers the remediation agent.
"""

from flask import Flask, request, jsonify
from agent import RemediationAgent
import logging
import threading

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook-server")

agent = RemediationAgent()
active_remediation = {"running": False, "last_report": None}


@app.route("/webhook/alert", methods=["POST"])
def receive_alert():
    """Endpoint for Prometheus AlertManager webhook."""
    alert_data = request.json
    logger.info(f"Received alert webhook: {alert_data}")

    # Filter: only act on firing critical alerts for our namespace
    alerts = alert_data.get("alerts", [])
    actionable = [
        a for a in alerts
        if a.get("status") == "firing"
        and a.get("labels", {}).get("namespace") == "quest-diagnostics"
        and a.get("labels", {}).get("severity") == "critical"
    ]

    if not actionable:
        return jsonify({"status": "ignored", "reason": "No actionable alerts"}), 200

    if active_remediation["running"]:
        return jsonify({"status": "skipped", "reason": "Remediation already in progress"}), 200

    # Run remediation in background thread
    def run_remediation():
        active_remediation["running"] = True
        try:
            report = agent.investigate_and_remediate(alert_data)
            active_remediation["last_report"] = report
        finally:
            active_remediation["running"] = False

    thread = threading.Thread(target=run_remediation, daemon=True)
    thread.start()

    return jsonify({"status": "accepted", "message": "Remediation agent triggered"}), 202


@app.route("/trigger", methods=["POST"])
def manual_trigger():
    """Manual trigger endpoint for demo purposes."""
    if active_remediation["running"]:
        return jsonify({"status": "skipped", "reason": "Remediation already in progress"}), 200

    def run_remediation():
        active_remediation["running"] = True
        try:
            report = agent.investigate_and_remediate({"source": "manual_trigger"})
            active_remediation["last_report"] = report
        finally:
            active_remediation["running"] = False

    thread = threading.Thread(target=run_remediation, daemon=True)
    thread.start()

    return jsonify({"status": "accepted", "message": "Remediation agent triggered manually"}), 202


@app.route("/status", methods=["GET"])
def get_status():
    """Check if agent is running and get last report."""
    return jsonify({
        "running": active_remediation["running"],
        "last_report": active_remediation["last_report"],
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "service": "quest-remediation-agent"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
