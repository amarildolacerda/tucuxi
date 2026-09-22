"""OTA Update Manager — checks GitHub for newer releases and applies updates."""

import os
import logging
import shutil
import subprocess
import time
from datetime import datetime, timezone

import requests

from .config import APP_VERSION, GITHUB_REPO_SLUG

logger = logging.getLogger("update")

GITHUB_API_BASE = "https://api.github.com"
CHECK_INTERVAL = 24 * 60 * 60  # 24 hours
RATE_LIMIT_SECONDS = 5 * 60    # 5 minutes between apply attempts


def parse_version(version_str):
    """Parse 'v1.2.3' or '1.2.3' into tuple (1, 2, 3)."""
    v = version_str.lstrip("v")
    parts = v.split(".")
    return tuple(int(p) for p in parts)


class UpdateManager:
    def __init__(self, project_dir=None):
        self.project_dir = project_dir or os.getcwd()
        self.current_version = APP_VERSION
        self.update_available = False
        self.latest_version = None
        self.latest_tag = None
        self.last_check = None
        self.last_error = None
        self.updating = False
        self.update_log = []
        self._last_apply_time = 0.0

    def get_status(self):
        """Return current update status as dict."""
        return {
            "current_version": self.current_version,
            "update_available": self.update_available,
            "latest_version": self.latest_version,
            "latest_tag": self.latest_tag,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "last_error": self.last_error,
            "updating": self.updating,
            "update_log": self.update_log,
        }

    def detect_deploy_mode(self):
        """Detect if project uses Docker Compose or bare metal."""
        compose_files = [
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        ]
        for f in compose_files:
            if os.path.exists(os.path.join(self.project_dir, f)):
                return "docker"
        return "bare_metal"

    def parse_version(self, version_str):
        """Parse 'v1.2.3' or '1.2.3' into tuple (1, 2, 3)."""
        v = version_str.lstrip("v")
        parts = v.split(".")
        return tuple(int(p) for p in parts)

    def check_for_update(self):
        """Check GitHub API for latest tag on main branch."""
        try:
            url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO_SLUG}/git/refs/tags"
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            tags = resp.json()

            if not tags:
                self.last_error = "No tags found"
                return

            # Extract version numbers from tags
            versions = []
            for tag in tags:
                ref = tag.get("ref", "")
                if ref.startswith("refs/tags/"):
                    tag_name = ref.replace("refs/tags/", "")
                    try:
                        ver = self.parse_version(tag_name)
                        versions.append((ver, tag_name))
                    except (ValueError, IndexError):
                        continue

            if not versions:
                self.last_error = "No valid version tags found"
                return

            # Get highest version
            versions.sort(key=lambda x: x[0], reverse=True)
            latest_ver, latest_tag = versions[0]
            current_ver = self.parse_version(self.current_version)

            self.latest_version = latest_tag.lstrip("v")
            self.latest_tag = latest_tag
            self.update_available = latest_ver > current_ver
            self.last_check = datetime.now(timezone.utc)
            self.last_error = None

            logger.info(
                "Update check: current=%s latest=%s available=%s",
                self.current_version, self.latest_version, self.update_available,
            )

        except Exception as e:
            self.last_error = str(e)
            logger.error("Update check failed: %s", e)

    def apply_update(self, tag):
        """Apply update: git checkout tag + rebuild. Returns (success, log)."""
        if self.updating:
            return False, ["Update already in progress"]

        now = time.time()
        if now - self._last_apply_time < RATE_LIMIT_SECONDS:
            remaining = int(RATE_LIMIT_SECONDS - (now - self._last_apply_time))
            return False, [f"Rate limited. Try again in {remaining}s"]

        self.updating = True
        self.update_log = []
        self._last_apply_time = now

        try:
            self._log(f"Starting update to {tag}")

            # Backup .env
            self._backup_env()

            # Git fetch + checkout
            self._run_cmd(["git", "fetch", "origin", "main"])
            self._run_cmd(["git", "checkout", tag])

            # Detect mode and rebuild
            mode = self.detect_deploy_mode()
            self._log(f"Deploy mode: {mode}")

            if mode == "docker":
                self._run_cmd(["docker", "compose", "pull"])
                self._run_cmd(["docker", "compose", "up", "-d"])
            else:
                self._run_cmd(["pip", "install", "-e", "."])
                # Try to restart systemd service
                self._run_cmd(["sudo", "systemctl", "restart", "tucuxi"], allow_fail=True)

            self._log("Update completed successfully")
            return True, self.update_log

        except Exception as e:
            self._log(f"ERROR: {e}")
            self._rollback()
            return False, self.update_log

        finally:
            self.updating = False

    def _backup_env(self):
        """Backup .env file before update."""
        env_path = os.path.join(self.project_dir, ".env")
        if os.path.exists(env_path):
            backup_path = env_path + ".backup"
            shutil.copy2(env_path, backup_path)
            self._log("Backed up .env to .env.backup")

    def _rollback(self):
        """Rollback to previous commit on error."""
        try:
            self._log("Rolling back to previous commit...")
            self._run_cmd(["git", "checkout", "-"])
            self._log("Rollback completed")
        except Exception as e:
            self._log(f"Rollback failed: {e}")

    def _run_cmd(self, cmd, allow_fail=False):
        """Run a shell command and log output."""
        self._log(f"$ {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.stdout:
                self._log(result.stdout.strip())
            if result.returncode != 0:
                msg = f"Command failed (exit {result.returncode}): {result.stderr.strip()}"
                if allow_fail:
                    self._log(f"WARNING: {msg}")
                else:
                    raise RuntimeError(msg)
        except subprocess.TimeoutExpired:
            if allow_fail:
                self._log("WARNING: Command timed out")
            else:
                raise RuntimeError("Command timed out after 300s")

    def _log(self, message):
        """Append to update log."""
        self.update_log.append(message)
        logger.info("UPDATE: %s", message)
