"""Regression coverage for team-round filenames and generated commands."""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "retorno-sobre-tokens" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rot_equipe  # noqa: E402
import rotlib  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
import test_rot  # noqa: E402


NOW = dt.datetime(2026, 10, 23, 15, 0, tzinfo=dt.timezone.utc)


class TeamRoundSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.central = rot_equipe.Central(str(self.root / "central"))
        self.config = rotlib.load_config()
        self.repo = test_rot.make_repo(self.root)
        self.projects = test_rot.make_logs(self.root, self.repo)
        self.meta = rot_equipe.open_round(
            central=self.central,
            config=self.config,
            period_id="7d",
            now=NOW,
            round_id="audit",
            roster=[],
            plan_default="api",
            opened_by=None,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_reserved_metadata_login_is_rejected_case_insensitively(self):
        analyze_kwargs = {
            "repos": [self.repo],
            "projects_dir": self.projects,
            "use_gh": False,
            "include_cwd": False,
            "identity": {"logins": [], "emails": ["dev@example.com"], "sources": []},
        }
        for login in ("rodada", "RODADA"):
            with self.subTest(login=login), self.assertRaisesRegex(rot_equipe.TeamError, "reservado"):
                rot_equipe.submit(
                    central=self.central,
                    config=self.config,
                    rodada="audit",
                    login=login,
                    plan_id=None,
                    monthly_usd=None,
                    plan_label=None,
                    stdin_is_tty=False,
                    analyze_kwargs=analyze_kwargs,
                )
        loaded = rot_equipe.load_round(self.central, "audit")
        self.assertEqual(loaded, {key: value for key, value in self.meta.items() if key != "link"})
        rot_equipe.submit(
            central=self.central,
            config=self.config,
            rodada="audit",
            login="dev-a",
            plan_id=None,
            monthly_usd=None,
            plan_label=None,
            stdin_is_tty=False,
            analyze_kwargs=analyze_kwargs,
        )
        self.assertTrue((self.central.root / "audit" / "dev-a.json").is_file())
        self.assertIsNotNone(rot_equipe.load_round(self.central, "audit"))

    def test_readme_command_reaches_round_on_custom_branch(self):
        bare = self.root / "central.git"
        subprocess.check_call(["git", "init", "--quiet", "--bare", "-b", "metrics", str(bare)])
        central = rot_equipe.Central(str(bare), "metrics", self.root / "cache-cto")
        meta = rot_equipe.open_round(
            central=central,
            config=self.config,
            period_id="7d",
            now=NOW,
            round_id="metrics-audit",
            roster=["dev-a"],
            plan_default="api",
            opened_by=None,
        )
        readme = central.read_text("metrics-audit/README.md")
        self.assertIsNotNone(readme)
        command = next(line for line in readme.splitlines() if line.startswith("python3 "))
        self.assertIn("--ramo metrics", command)
        args = command.split()
        args[:2] = [sys.executable, str(SCRIPTS / "rot_report.py")]
        sent = subprocess.run(
            [*args, "--cache-dir", str(self.root / "cache-dev"), "--login", "dev-a", "--autor", "dev@example.com",
             "--no-gh", "--no-cwd", "--repo", str(self.repo), "--projects-dir", str(self.projects), "--sim"],
            cwd=self.repo,
            env={**os.environ, **test_rot.GIT_ENV},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(sent.returncode, 0, sent.stderr)
        stored = subprocess.check_output(
            ["git", "-C", str(bare), "show", "metrics:metrics-audit/dev-a.json"], text=True
        )
        self.assertEqual(json.loads(stored)["login"], "dev-a")

