"""Tests for deploy.py. Run with: python3 -m unittest discover -s git-deployer/tests -v

Everything runs against a temporary bare git repo, a temporary fake /config and a fake Home Assistant API.
"""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "root"))
import deploy  # noqa: E402

AUTOMATIONS = "- id: '1'\n  alias: Test\n  triggers: []\n  actions:\n  - action: light.turn_on\n    target:\n      entity_id: light.x\n"
SCRIPTS = "demo:\n  sequence: []\n"
SCENES = "- id: '1'\n  name: S\n  entities: {}\n"
DASH = "views:\n- title: Office\n  cards: []\n"
OLD_AUTOMATIONS = "- id: 'old'\n  alias: Old\n  triggers: []\n  actions: []\n"


class FakeApi(http.server.BaseHTTPRequestHandler):
    calls = []
    check_result = {"result": "valid", "errors": None}

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        FakeApi.calls.append(self.path)
        body = json.dumps(FakeApi.check_result if self.path.endswith("check_config") else []).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence
        pass


def sh(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


class DeployTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), FakeApi)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        FakeApi.calls = []
        FakeApi.check_result = {"result": "valid", "errors": None}
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.config = os.path.join(t, "config")
        self.data = os.path.join(t, "data")
        os.makedirs(os.path.join(self.config, "dashboards"))
        os.makedirs(self.data)
        self.remote = os.path.join(t, "remote.git")
        sh("git", "init", "-q", "--bare", "-b", "deploy", self.remote)
        self.work = os.path.join(t, "work")
        sh("git", "clone", "-q", self.remote, self.work)
        sh("git", "config", "user.name", "t", cwd=self.work)
        sh("git", "config", "user.email", "t@t", cwd=self.work)
        # live /config before the first deploy
        self.write(self.config, "automations.yaml", OLD_AUTOMATIONS)
        self.write(self.config, "secrets.yaml", "api: REAL-SECRET\n")
        self.write(self.config, "configuration.yaml", "default_config:\n")
        self.publish({"automations.yaml": AUTOMATIONS, "scripts.yaml": SCRIPTS, "scenes.yaml": SCENES,
                      "dashboards/office.yaml": DASH})
        env = {
            "DEPLOY_REPO_URL": "file://" + self.remote, "DEPLOY_USERNAME": "u", "DEPLOY_PASSWORD": "hunter2-secret",
            "DEPLOY_BRANCH": "deploy", "DEPLOY_DRY_RUN": "false", "DEPLOY_POLL_INTERVAL": "0",
            "DEPLOY_RELOAD": "true", "DEPLOY_KEEP_BACKUPS": "20", "CONFIG_DIR": self.config, "DATA_DIR": self.data,
            "SUPERVISOR_URL": f"http://127.0.0.1:{self.server.server_address[1]}", "SUPERVISOR_TOKEN": "tok",
        }
        self.env_backup = dict(os.environ)
        os.environ.update(env)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env_backup)
        self.tmp.cleanup()

    # helpers
    def write(self, base, rel, text):
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def read(self, base, rel):
        with open(os.path.join(base, rel), encoding="utf-8") as handle:
            return handle.read()

    def publish(self, files, remove=()):
        for rel in remove:
            os.unlink(os.path.join(self.work, rel))
        for rel, text in files.items():
            self.write(self.work, rel, text)
        sh("git", "add", "-A", cwd=self.work)
        sh("git", "commit", "-q", "--allow-empty", "-m", "deploy", cwd=self.work)
        sh("git", "push", "-q", "origin", "deploy", cwd=self.work)

    def run_once(self):
        return deploy.run_once(deploy.Settings())

    # tests
    def test_dry_run_changes_nothing(self):
        os.environ["DEPLOY_DRY_RUN"] = "true"
        self.assertEqual(self.run_once(), "dry-run")
        self.assertEqual(self.read(self.config, "automations.yaml"), OLD_AUTOMATIONS)
        self.assertFalse(os.path.exists(os.path.join(self.config, "scripts.yaml")))
        self.assertFalse(os.path.exists(os.path.join(self.data, "backups")))
        self.assertEqual(FakeApi.calls, [])

    def test_deploy_copies_backs_up_checks_and_reloads(self):
        self.assertEqual(self.run_once(), "deployed")
        self.assertEqual(self.read(self.config, "automations.yaml"), AUTOMATIONS)
        self.assertEqual(self.read(self.config, "dashboards/office.yaml"), DASH)
        backups = os.path.join(self.data, "backups")
        stamp = os.listdir(backups)[0]
        self.assertEqual(self.read(os.path.join(backups, stamp), "automations.yaml"), OLD_AUTOMATIONS)
        self.assertTrue(any(c.endswith("check_config") for c in FakeApi.calls))
        for svc in ("automation/reload", "script/reload", "scene/reload"):
            self.assertIn("/services/" + svc, FakeApi.calls)

    def test_second_run_is_a_noop(self):
        self.run_once()
        FakeApi.calls = []
        self.assertEqual(self.run_once(), "unchanged")
        self.assertEqual(FakeApi.calls, [])

    def test_only_allowlisted_files_are_ever_copied(self):
        self.publish({
            "secrets.yaml": "api: FROM-REPO\n", "configuration.yaml": "evil: true\n",
            "custom_components/x/__init__.py": "print('x')\n", "dashboards/notes.txt": "no\n",
            "dashboards/sub/deep.yaml": DASH, "tools/run.sh": "rm -rf /\n",
        })
        self.assertEqual(self.run_once(), "deployed")
        self.assertEqual(self.read(self.config, "secrets.yaml"), "api: REAL-SECRET\n")
        self.assertEqual(self.read(self.config, "configuration.yaml"), "default_config:\n")
        self.assertFalse(os.path.exists(os.path.join(self.config, "custom_components")))
        self.assertFalse(os.path.exists(os.path.join(self.config, "tools")))
        self.assertFalse(os.path.exists(os.path.join(self.config, "dashboards", "notes.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.config, "dashboards", "sub")))

    def test_symlinks_in_the_repo_are_ignored(self):
        os.symlink("/etc/passwd", os.path.join(self.work, "scenes.yaml.link"))
        os.unlink(os.path.join(self.work, "scenes.yaml"))
        os.symlink("/etc/passwd", os.path.join(self.work, "scenes.yaml"))
        sh("git", "add", "-A", cwd=self.work)
        sh("git", "commit", "-q", "-m", "link", cwd=self.work)
        sh("git", "push", "-q", "origin", "deploy", cwd=self.work)
        self.assertEqual(self.run_once(), "deployed")
        self.assertFalse(os.path.exists(os.path.join(self.config, "scenes.yaml")))

    def test_invalid_yaml_blocks_everything(self):
        self.publish({"automations.yaml": "- id: [unclosed\n"})
        self.assertEqual(self.run_once(), "invalid")
        self.assertEqual(self.read(self.config, "automations.yaml"), OLD_AUTOMATIONS)
        self.assertFalse(os.path.exists(os.path.join(self.config, "scripts.yaml")))
        self.assertFalse(any(c.endswith("check_config") for c in FakeApi.calls))

    def test_empty_or_duplicate_automations_are_rejected(self):
        self.publish({"automations.yaml": "[]\n"})
        self.assertEqual(self.run_once(), "invalid")
        self.publish({"automations.yaml": AUTOMATIONS + AUTOMATIONS})
        self.assertEqual(self.run_once(), "invalid")
        self.assertEqual(self.read(self.config, "automations.yaml"), OLD_AUTOMATIONS)

    def test_failed_config_check_restores_everything(self):
        FakeApi.check_result = {"result": "invalid", "errors": "Integration 'x' not found"}
        self.assertEqual(self.run_once(), "rolled-back")
        self.assertEqual(self.read(self.config, "automations.yaml"), OLD_AUTOMATIONS)
        for rel in ("scripts.yaml", "scenes.yaml", "dashboards/office.yaml"):
            self.assertFalse(os.path.exists(os.path.join(self.config, rel)), rel + " should have been removed")
        self.assertEqual(self.read(self.config, "secrets.yaml"), "api: REAL-SECRET\n")
        self.assertNotIn("/services/automation/reload", FakeApi.calls)

    def test_unreachable_api_counts_as_failed_check(self):
        os.environ["SUPERVISOR_URL"] = "http://127.0.0.1:9"
        self.assertEqual(self.run_once(), "rolled-back")
        self.assertEqual(self.read(self.config, "automations.yaml"), OLD_AUTOMATIONS)

    def test_password_is_never_logged(self):
        os.environ["DEPLOY_REPO_URL"] = "file:///does/not/exist.git"
        with self.assertRaises(RuntimeError) as ctx:
            self.run_once()
        self.assertNotIn("hunter2-secret", str(ctx.exception))

    def test_backups_are_pruned(self):
        os.environ["DEPLOY_KEEP_BACKUPS"] = "2"
        for i in range(4):
            self.publish({"scenes.yaml": SCENES + f"- id: '{i + 10}'\n  name: n{i}\n  entities: {{}}\n"})
            self.assertEqual(self.run_once(), "deployed")
            # backups are named by second; make each one unique
            backups = os.path.join(self.data, "backups")
            newest = sorted(os.listdir(backups))[-1]
            os.rename(os.path.join(backups, newest), os.path.join(backups, f"2026010{i}-000000"))
        self.assertLessEqual(len(os.listdir(os.path.join(self.data, "backups"))), 3)


if __name__ == "__main__":
    unittest.main()
