#!/usr/bin/env python3
"""Home Assistant Git Deployer.

Pulls one branch of a git repository into the add-on's OWN data folder and copies a fixed allow-list
of files into /config:

    automations.yaml, scripts.yaml, scenes.yaml, dashboards/*.yaml
    configuration.yaml   (only when deploy_configuration is switched on; never restarts Home Assistant)

Nothing else in /config is ever read, written or deleted. Every overwritten file is backed up first,
Home Assistant's configuration check runs afterwards, and a failed check restores the old files.

Settings come from environment variables (set by run.sh from the add-on options):
    DEPLOY_REPO_URL, DEPLOY_USERNAME, DEPLOY_PASSWORD, DEPLOY_BRANCH
    DEPLOY_DRY_RUN (true/false), DEPLOY_POLL_INTERVAL (seconds, 0 = run once)
    DEPLOY_RELOAD (true/false), DEPLOY_KEEP_BACKUPS, DEPLOY_CONFIGURATION (true/false)
    CONFIG_DIR (default /config), DATA_DIR (default /data)
    SUPERVISOR_URL (default http://supervisor/core/api), SUPERVISOR_TOKEN
"""
import datetime
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import yaml

FIXED_FILES = ("automations.yaml", "scripts.yaml", "scenes.yaml")
CONFIG_FILE = "configuration.yaml"
DASHBOARD_DIR = "dashboards"
DASHBOARD_NAME = re.compile(r"^[A-Za-z0-9_.-]+\.ya?ml$")
RELOAD_SERVICES = ("automation/reload", "script/reload", "scene/reload")


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


class Settings:
    def __init__(self):
        e = os.environ
        self.repo_url = e.get("DEPLOY_REPO_URL", "")
        self.username = e.get("DEPLOY_USERNAME", "")
        self.password = e.get("DEPLOY_PASSWORD", "")
        self.branch = e.get("DEPLOY_BRANCH", "deploy") or "deploy"
        self.dry_run = env_bool("DEPLOY_DRY_RUN", True)
        self.poll = int(e.get("DEPLOY_POLL_INTERVAL", "0") or 0)
        self.reload = env_bool("DEPLOY_RELOAD", True)
        self.keep = int(e.get("DEPLOY_KEEP_BACKUPS", "20") or 20)
        self.deploy_configuration = env_bool("DEPLOY_CONFIGURATION", False)
        self.config_dir = e.get("CONFIG_DIR", "/config")
        self.data_dir = e.get("DATA_DIR", "/data")
        self.api = e.get("SUPERVISOR_URL", "http://supervisor/core/api").rstrip("/")
        self.token = e.get("SUPERVISOR_TOKEN", "")


def log(level, message):
    stamp = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {level}: {message}", flush=True)


# ---------------------------------------------------------------------------------------- git

def git(settings, args, cwd=None):
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    askpass = os.path.join(settings.data_dir, "askpass.sh")
    with open(askpass, "w", encoding="utf-8") as handle:
        handle.write('#!/bin/sh\ncase "$1" in\n  Username*) printf "%s\\n" "$GIT_DEPLOY_USERNAME" ;;\n  *) printf "%s\\n" "$GIT_DEPLOY_PASSWORD" ;;\nesac\n')
    os.chmod(askpass, stat.S_IRWXU)
    env["GIT_ASKPASS"] = askpass
    env["GIT_DEPLOY_USERNAME"] = settings.username
    env["GIT_DEPLOY_PASSWORD"] = settings.password
    result = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        # never echo the password
        message = (result.stderr or result.stdout).replace(settings.password, "***") if settings.password else (result.stderr or result.stdout)
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {message.strip()}")
    return result.stdout.strip()


def sync_repo(settings):
    """Clone or update the working copy under DATA_DIR and return (directory, commit sha)."""
    repo = os.path.join(settings.data_dir, "repo")
    if not os.path.isdir(os.path.join(repo, ".git")):
        if os.path.isdir(repo):
            shutil.rmtree(repo)
        git(settings, ["clone", "--quiet", "--depth", "1", "--branch", settings.branch, "--single-branch", settings.repo_url, repo])
    else:
        git(settings, ["remote", "set-url", "origin", settings.repo_url], cwd=repo)
        git(settings, ["fetch", "--quiet", "--depth", "1", "origin", settings.branch], cwd=repo)
        git(settings, ["reset", "--quiet", "--hard", "FETCH_HEAD"], cwd=repo)
    return repo, git(settings, ["rev-parse", "HEAD"], cwd=repo)


# ---------------------------------------------------------------------------------- validation

class Loader(yaml.SafeLoader):
    pass


Loader.add_multi_constructor("!", lambda loader, suffix, node: None)


def candidates(repo, include_configuration=False):
    """The allow-listed files that exist in the repo, as relative POSIX paths."""
    found = []
    names = FIXED_FILES + ((CONFIG_FILE,) if include_configuration else ())
    for name in names:
        path = os.path.join(repo, name)
        if os.path.isfile(path) and not os.path.islink(path):
            found.append(name)
    d = os.path.join(repo, DASHBOARD_DIR)
    if os.path.isdir(d) and not os.path.islink(d):
        for name in sorted(os.listdir(d)):
            path = os.path.join(d, name)
            if DASHBOARD_NAME.match(name) and os.path.isfile(path) and not os.path.islink(path):
                found.append(f"{DASHBOARD_DIR}/{name}")
    return found


def validate(repo, files, config_dir=None):
    """Return a list of blocking problems for the files that would be deployed."""
    problems = []
    for rel in files:
        try:
            with open(os.path.join(repo, rel), encoding="utf-8") as handle:
                data = yaml.load(handle, Loader=Loader)  # noqa: S506 - SafeLoader subclass
        except (yaml.YAMLError, UnicodeDecodeError) as exc:
            problems.append(f"{rel} is not valid YAML: {exc}")
            continue
        if rel == "automations.yaml":
            if not isinstance(data, list) or not data:
                problems.append("automations.yaml must be a non-empty list")
            else:
                ids = [a.get("id") for a in data if isinstance(a, dict)]
                if any(not isinstance(a, dict) or not a.get("id") or not a.get("alias") for a in data):
                    problems.append("every automation needs an id and an alias")
                if len(set(ids)) != len(ids):
                    problems.append("automation ids are not unique")
        elif rel == CONFIG_FILE:
            if not isinstance(data, dict) or "default_config" not in data:
                problems.append("configuration.yaml must be a mapping that still contains 'default_config'")
            elif config_dir:
                current = os.path.join(config_dir, CONFIG_FILE)
                if os.path.isfile(current):
                    old, new = os.path.getsize(current), os.path.getsize(os.path.join(repo, rel))
                    if old > 0 and new < old * 0.5:
                        problems.append(f"configuration.yaml would shrink from {old} to {new} bytes (more than half); "
                                        "refusing in case it was truncated")
        elif rel == "scripts.yaml":
            if not isinstance(data, dict):
                problems.append("scripts.yaml must be a mapping")
        elif rel == "scenes.yaml":
            if not isinstance(data, list):
                problems.append("scenes.yaml must be a list")
        elif rel.startswith(DASHBOARD_DIR + "/"):
            if not isinstance(data, dict) or not data.get("views"):
                problems.append(f"{rel} needs a top-level 'views' list")
    return problems


def plan(repo, files, config_dir):
    changes = []
    for rel in files:
        with open(os.path.join(repo, rel), "rb") as handle:
            new = handle.read()
        target = os.path.join(config_dir, rel)
        if not os.path.isfile(target):
            changes.append((rel, "new"))
        else:
            with open(target, "rb") as handle:
                if handle.read() != new:
                    changes.append((rel, "changed"))
    return changes


# ---------------------------------------------------------------------------------------- apply

def read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def write_atomic(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".deploy-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def apply_changes(settings, repo, changes):
    """Back up and replace the changed files. Returns (backup_dir, [(rel, previous_bytes_or_None)])."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = os.path.join(settings.data_dir, "backups", stamp)
    previous = []
    for rel, _kind in changes:
        target = os.path.join(settings.config_dir, rel)
        old = read_bytes(target) if os.path.isfile(target) else None
        if old is not None:
            write_atomic(os.path.join(backup_dir, rel), old)
        previous.append((rel, old))
    done = []
    try:
        for rel, old in previous:
            write_atomic(os.path.join(settings.config_dir, rel), read_bytes(os.path.join(repo, rel)))
            done.append((rel, old))
    except BaseException:
        rollback(settings, done)
        raise
    return backup_dir, previous


def rollback(settings, previous):
    for rel, old in previous:
        target = os.path.join(settings.config_dir, rel)
        if old is None:
            if os.path.isfile(target):
                os.unlink(target)
        else:
            write_atomic(target, old)


def prune_backups(settings):
    root = os.path.join(settings.data_dir, "backups")
    if not os.path.isdir(root):
        return
    for name in sorted(os.listdir(root))[: -max(settings.keep, 1)]:
        shutil.rmtree(os.path.join(root, name), ignore_errors=True)


# ------------------------------------------------------------------------------------------ API

def api(settings, method, path, body=None):
    request = urllib.request.Request(
        f"{settings.api}{path}",
        data=json.dumps(body if body is not None else {}).encode() if method == "POST" else None,
        method=method,
        headers={"Authorization": f"Bearer {settings.token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed supervisor URL
        raw = response.read().decode() or "null"
    return json.loads(raw)


def check_config(settings):
    """Ask Home Assistant to validate /config. Returns (ok, message)."""
    try:
        result = api(settings, "POST", "/config/core/check_config")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, f"could not reach the Home Assistant API: {exc}"
    if isinstance(result, dict) and result.get("result") == "valid":
        return True, "valid"
    return False, str((result or {}).get("errors") if isinstance(result, dict) else result)


def reload_all(settings):
    for service in RELOAD_SERVICES:
        try:
            api(settings, "POST", f"/services/{service}")
            log("INFO", f"reloaded {service.split('/')[0]}")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            log("WARNING", f"could not reload {service.split('/')[0]}: {exc}")


def notify(settings, title, message, notification_id="git_deployer"):
    try:
        api(settings, "POST", "/services/persistent_notification/create",
            {"title": title, "message": message, "notification_id": notification_id})
    except (urllib.error.URLError, OSError, ValueError):
        pass


# ------------------------------------------------------------------------------------------ main

def state_path(settings):
    return os.path.join(settings.data_dir, "state.json")


def load_state(settings):
    try:
        with open(state_path(settings), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def save_state(settings, state):
    with open(state_path(settings), "w", encoding="utf-8") as handle:
        json.dump(state, handle)


def run_once(settings):
    """One deploy attempt. Returns a short status string (used by tests)."""
    os.makedirs(settings.data_dir, exist_ok=True)
    repo, sha = sync_repo(settings)
    state = load_state(settings)
    files = candidates(repo, settings.deploy_configuration)
    if not files:
        log("WARNING", f"branch '{settings.branch}' has none of the deployable files; nothing to do")
        return "empty"

    problems = validate(repo, files, settings.config_dir)
    if problems:
        for problem in problems:
            log("ERROR", problem)
        log("ERROR", f"commit {sha[:7]} is NOT deployed: it failed validation. Home Assistant is unchanged.")
        notify(settings, "Git Deployer: not deployed", f"Commit {sha[:7]} failed validation:\n- " + "\n- ".join(problems))
        return "invalid"

    changes = plan(repo, files, settings.config_dir)
    if not changes:
        log("INFO", f"commit {sha[:7]}: /config already matches, nothing to copy")
        if not settings.dry_run:
            state["deployed_sha"] = sha
            save_state(settings, state)
        return "unchanged"

    summary = ", ".join(f"{rel} ({kind})" for rel, kind in changes)
    if settings.dry_run:
        log("INFO", f"DRY RUN: commit {sha[:7]} would copy {len(changes)} file(s): {summary}")
        log("INFO", "Nothing was changed. Set dry_run to false to deploy.")
        return "dry-run"

    log("INFO", f"commit {sha[:7]}: copying {len(changes)} file(s): {summary}")
    backup_dir, previous = apply_changes(settings, repo, changes)
    ok, message = check_config(settings)
    if not ok:
        rollback(settings, previous)
        log("ERROR", f"Home Assistant rejected the new files ({message}). The previous files were restored.")
        notify(settings, "Git Deployer: rolled back", f"Commit {sha[:7]} failed the configuration check and was rolled back.\n{message}")
        return "rolled-back"

    if settings.reload:
        reload_all(settings)
    state["deployed_sha"] = sha
    save_state(settings, state)
    prune_backups(settings)
    log("INFO", f"deployed commit {sha[:7]}. Previous versions are in {backup_dir}")
    notify(settings, "Git Deployer", f"Deployed commit {sha[:7]}: {summary}")
    if any(rel == CONFIG_FILE for rel, _kind in changes):
        # Most changes to configuration.yaml only take effect after a restart. Never restart automatically.
        log("WARNING", "configuration.yaml changed and passed the configuration check. "
                       "Restart Home Assistant when you are ready to apply it.")
        notify(settings, "Git Deployer: restart needed",
               f"configuration.yaml was updated from commit {sha[:7]} and passed the configuration check. "
               "Restart Home Assistant to apply it. The previous file is in the add-on's backups.",
               notification_id="git_deployer_restart")
    return "deployed"


def main():
    settings = Settings()
    if not settings.repo_url:
        log("ERROR", "repository.url is not set")
        return 1
    log("INFO", f"watching branch '{settings.branch}' ({'dry run' if settings.dry_run else 'live'})")
    while True:
        try:
            run_once(settings)
        except Exception as exc:  # noqa: BLE001 - one bad cycle must not stop the loop
            log("ERROR", str(exc))
            if settings.poll <= 0:
                return 1
        if settings.poll <= 0:
            return 0
        time.sleep(settings.poll)


if __name__ == "__main__":
    sys.exit(main())
