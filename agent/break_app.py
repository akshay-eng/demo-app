"""
Demo script: Introduce a bug into the backend app to simulate a bad deployment.
This pushes a broken commit that will cause the backend pods to crash.

Usage:
    python break_app.py              # Introduce the bug
    python break_app.py --fix        # Revert the bug manually
"""

import sys
from github import Github
from config import GITHUB_TOKEN, APP_REPO

g = Github(GITHUB_TOKEN)
repo = g.get_repo(APP_REPO)

BROKEN_CODE = '''import os
import sys
from fastapi import FastAPI, HTTPException

# BUG: Intentional error - importing a module that doesn't exist
from nonexistent_module import broken_function  # <-- This will crash the app on startup

app = FastAPI(title="Quest Diagnostics Lab API", version="1.0.0")

@app.get("/health")
def health_check():
    return {"status": "healthy"}
'''


def introduce_bug():
    """Push a broken version of app.py to the repo."""
    print("Introducing bug into backend/app.py...")

    file = repo.get_contents("backend/app.py")

    # Save original content info for rollback
    print(f"Current file SHA: {file.sha}")

    repo.update_file(
        path="backend/app.py",
        message="feat: add new analytics module integration",
        content=BROKEN_CODE,
        sha=file.sha,
    )

    print("Bug introduced! The commit message looks innocent:")
    print("  'feat: add new analytics module integration'")
    print()
    print("What will happen next:")
    print("  1. GitHub Actions will build a new Docker image with the broken code")
    print("  2. The workflow will update the manifests repo with the new image tag")
    print("  3. ArgoCD will sync and deploy the broken image")
    print("  4. Pods will CrashLoopBackOff (ImportError on startup)")
    print("  5. Prometheus will fire QuestPodCrashLooping alert")
    print("  6. The remediation agent will pick it up and fix it!")


def fix_bug():
    """Restore the original app.py (manual fix, not agent-driven)."""
    print("This is handled by the agent automatically.")
    print("The agent rolls back the image tag in the manifests repo.")
    print("If you need to fix the source code too, revert the commit manually:")
    print(f"  git revert HEAD  (in the {APP_REPO} repo)")


if __name__ == "__main__":
    if "--fix" in sys.argv:
        fix_bug()
    else:
        introduce_bug()
