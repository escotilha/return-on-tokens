#!/usr/bin/env python3
"""Fixtures de git e de logs JSONL para o ROT."""

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
SCRIPTS = ROOT / "skills" / "return-on-tokens" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rotlib  # noqa: E402
import rot_report  # noqa: E402

NOW = dt.datetime(2026, 10, 23, 15, 0, tzinfo=dt.timezone.utc)
SONNET = "claude-sonnet-4-6"


def git(repo: Path, *args: str, when: str | None = None) -> None:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Dev Exemplo"
    env["GIT_AUTHOR_EMAIL"] = "dev@example.com"
    env["GIT_COMMITTER_NAME"] = "Dev Exemplo"
    env["GIT_COMMITTER_EMAIL"] = "dev@example.com"
    if when:
        env["GIT_AUTHOR_DATE"] = when
        env["GIT_COMMITTER_DATE"] = when
    subprocess.check_call(
        ["git", "-C", str(repo), *args],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def write(repo: Path, relative: str, text: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_repo(root: Path) -> Path:
    repo = root / "sample-app"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    write(repo, "src/rewrite.py", "".join(f"old {i}\n" for i in range(8)))
    write(repo, "src/trim.py", "keep 1\nkeep 2\ndrop 1\ndrop 2\ndrop 3\ndrop 4\n")
    write(repo, "src/build.py", "keep\nthis\nfile\n")
    write(repo, "README.md", "base\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "base", when="2026-08-01T12:00:00+00:00")

    git(repo, "checkout", "-b", "old-feature")
    write(repo, "src/ancient.py", "".join(f"ancient {i}\n" for i in range(9)))
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "trabalho antigo", when="2026-08-20T12:00:00+00:00")
    git(repo, "checkout", "main")
    git(
        repo, "merge", "--no-ff", "old-feature",
        "-m", "Merge pull request #9 from dev/old-feature",
        when="2026-09-01T12:00:00+00:00",
    )

    git(repo, "checkout", "-b", "feature")
    write(repo, "src/new.py", "".join(f"new {i}\n" for i in range(10)))
    write(repo, "src/rewrite.py", "".join(f"rewritten {i}\n" for i in range(8)))
    write(repo, "src/trim.py", "keep 1\nkeep 2\n")
    write(repo, "src/build.py", "keep\nthis\nchanged\n")
    write(repo, "package-lock.json", "".join(f"lock {i}\n" for i in range(100)))
    write(repo, "vendor/lib.py", "".join(f"vendor {i}\n" for i in range(50)))
    write(repo, "dist/app.min.js", "".join(f"min {i}\n" for i in range(40)))
    write(repo, "src/app.generated.ts", "".join(f"gen {i}\n" for i in range(15)))
    write(repo, "tests/__snapshots__/a.snap", "".join(f"snap {i}\n" for i in range(20)))
    write(repo, "build/output.js", "".join(f"out {i}\n" for i in range(7)))
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "entrega da feature", when="2026-10-18T12:00:00+00:00")
    git(repo, "checkout", "main")
    git(
        repo, "merge", "--no-ff", "feature",
        "-m", "Merge pull request #1 from dev/feature",
        when="2026-10-20T12:00:00+00:00",
    )

    write(repo, "src/health.py", "".join(f"ok {i}\n" for i in range(5)))
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "Adiciona healthcheck (#2)", when="2026-10-23T10:00:00+00:00")

    write(repo, "src/note.py", "nota\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "Corrige comentario", when="2026-10-23T11:00:00+00:00")

    git(repo, "checkout", "-b", "wip")
    write(repo, "src/wip.py", "".join(f"wip {i}\n" for i in range(30)))
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "ainda nao entrou", when="2026-10-22T12:00:00+00:00")
    git(repo, "checkout", "main")
    return repo


def assistant(when: str, cwd: str, model: str, usage: dict, session: str = "s1") -> str:
    return json.dumps({
        "type": "assistant",
        "timestamp": when,
        "cwd": cwd,
        "sessionId": session,
        "message": {"role": "assistant", "model": model, "usage": usage},
    }, ensure_ascii=False)


def user_line(when: str, cwd: str, text: str, session: str = "s1") -> str:
    return json.dumps({
        "type": "user",
        "timestamp": when,
        "cwd": cwd,
        "sessionId": session,
        "message": {"role": "user", "content": text},
    }, ensure_ascii=False)


class FormatTests(unittest.TestCase):
    def test_brazilian_numbers(self):
        self.assertEqual(rotlib.format_int(2100000), "2.100.000")
        self.assertEqual(rotlib.format_int(0), "0")
        self.assertEqual(rotlib.format_number(30.4375, 4), "30,4375")
        self.assertEqual(rotlib.format_usd(4.8), "US$ 4,80")
        self.assertEqual(rotlib.format_usd(0.17142857), "US$ 0,1714")
        self.assertEqual(rotlib.format_brl(115.87), "R$ 115,87")
        self.assertEqual(rotlib.format_signed_int(11), "+11")
        self.assertEqual(rotlib.format_signed_int(-4), "-4")


class PriceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = rotlib.load_config()

    def test_longest_prefix_and_context_suffix(self):
        usd, missing = rotlib.price_turn(self.cfg, "claude-opus-4-5-20251101", 1_000_000, 0, 0, 0, 0)
        self.assertIsNone(missing)
        self.assertAlmostEqual(usd, 5.0)
        usd, missing = rotlib.price_turn(self.cfg, "claude-opus-4-1-20250805", 1_000_000, 0, 0, 0, 0)
        self.assertAlmostEqual(usd, 15.0)
        usd, _ = rotlib.price_turn(self.cfg, "claude-opus-4-6[1m]", 1_000_000, 0, 0, 0, 0)
        self.assertAlmostEqual(usd, 5.0)
        usd, _ = rotlib.price_turn(self.cfg, "claude-sonnet-5-5-20261001", 0, 0, 0, 0, 1_000_000)
        self.assertAlmostEqual(usd, 0.10)
        usd, _ = rotlib.price_turn(self.cfg, "claude-sonnet-5-20260801", 0, 0, 0, 0, 1_000_000)
        self.assertAlmostEqual(usd, 0.20)

    def test_cache_split_is_not_double_counted(self):
        usage = {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_creation_input_tokens": 9999,
            "cache_creation": {
                "ephemeral_5m_input_tokens": 100,
                "ephemeral_1h_input_tokens": 50,
            },
            "cache_read_input_tokens": 7,
        }
        self.assertEqual(rotlib.cache_split(usage), (100, 50))
        self.assertEqual(rotlib.cache_split({"cache_creation_input_tokens": 4000}), (4000, 0))

    def test_unknown_model_is_not_priced_and_does_not_accumulate(self):
        first, missing = rotlib.price_turn(self.cfg, "claude-inexistente", 500, 0, 0, 0, 0)
        second, missing_again = rotlib.price_turn(self.cfg, "claude-inexistente", 500, 0, 0, 0, 0)
        self.assertEqual(first, 0.0)
        self.assertEqual(second, 0.0)
        self.assertEqual(missing, "claude-inexistente")
        self.assertEqual(missing_again, "claude-inexistente")

    def test_synthetic_is_free_without_warning(self):
        usd, missing = rotlib.price_turn(self.cfg, "<synthetic>", 10, 10, 10, 10, 10)
        self.assertEqual(usd, 0.0)
        self.assertIsNone(missing)

    def test_haiku_55_prompt_tier(self):
        low, _ = rotlib.price_turn(self.cfg, "claude-haiku-5-5", 100_000, 0, 0, 0, 0)
        high, _ = rotlib.price_turn(self.cfg, "claude-haiku-5-5", 100_001, 0, 0, 0, 0)
        crossed, _ = rotlib.price_turn(self.cfg, "claude-haiku-5-5", 10, 0, 0, 0, 100_000)
        self.assertAlmostEqual(low, 0.01)
        self.assertAlmostEqual(high, 0.0500005)
        self.assertAlmostEqual(crossed, 10 * 0.50 / 1_000_000 + 100_000 * 0.05 / 1_000_000)

    def test_sonnet_46_formula(self):
        usd, missing = rotlib.price_turn(
            self.cfg, SONNET, 1_000_000, 100_000, 0, 0, 1_000_000
        )
        self.assertIsNone(missing)
        self.assertAlmostEqual(usd, 3.0 + 1.5 + 0.30)

    def test_naive_timestamp_is_rejected(self):
        self.assertIsNone(rotlib.parse_ts("2026-10-23T10:00:00"))
        self.assertIsNotNone(rotlib.parse_ts("2026-10-23T10:00:00Z"))

    def test_proration_uses_average_month(self):
        self.assertAlmostEqual(rotlib.prorate(100, "7d", 30.4375), 700 / 30.4375)
        self.assertAlmostEqual(rotlib.prorate(100, "24h", 30.4375), 100 / 30.4375)
        self.assertAlmostEqual(rotlib.prorate(100, "30d", 30.4375), 3000 / 30.4375)

    def test_zero_loc_ratio_is_none(self):
        self.assertIsNone(rotlib.ratio(10, 0))


class ExclusionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = rotlib.load_config()

    def test_paths(self):
        reason = rotlib.exclusion_reason
        cfg = self.cfg
        self.assertEqual(reason("package-lock.json", cfg), "lockfile")
        self.assertEqual(reason("nested/yarn.lock", cfg), "lockfile")
        self.assertEqual(reason("vendor/lib.py", cfg), "vendored")
        self.assertEqual(reason("third_party/x.py", cfg), "vendored")
        self.assertEqual(reason("node_modules/a.js", cfg), "vendored")
        self.assertEqual(reason("dist/app.min.js", cfg), "generated")
        self.assertEqual(reason("src/app.generated.ts", cfg), "generated")
        self.assertEqual(reason("build/output.js", cfg), "generated")
        self.assertEqual(reason("tests/__snapshots__/a.snap", cfg), "snapshot")
        self.assertEqual(reason("foo.snapshot", cfg), "snapshot")
        self.assertIsNone(reason("src/build.py", cfg))
        self.assertIsNone(reason("src/app.py", cfg))

    def test_numstat_rename_and_binary(self):
        data = (
            b"1\t0\tplain.py\x00"
            b"1\t0\t\x00src/my dir/old file.py\x00src/my dir/new file.py\x00"
            b"-\t-\timage.png\x00"
        )
        entries = rotlib.parse_numstat_z(data)
        self.assertEqual(entries[0]["path"], "plain.py")
        self.assertEqual(entries[1]["path"], "src/my dir/new file.py")
        self.assertEqual(entries[1]["old_path"], "src/my dir/old file.py")
        self.assertTrue(entries[2]["binary"])
        stats = rotlib.loc_from_numstat(entries, self.cfg)
        self.assertEqual(stats["effective"], 2)
        self.assertEqual(stats["binary_files"], 1)


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.repo = make_repo(cls.root)
        cls.projects = cls.root / "projects"
        slug = cls.projects / "-tmp-sample-app"
        slug.mkdir(parents=True)
        priced = "\n".join([
            user_line("2026-10-19T12:00:00Z", str(cls.repo), "segue o PR", session="feature"),
            assistant(
                "2026-10-19T12:05:00Z",
                str(cls.repo),
                SONNET,
                {
                    "input_tokens": 1_000_000,
                    "output_tokens": 100_000,
                    "cache_read_input_tokens": 1_000_000,
                    "cache_creation_input_tokens": 0,
                },
                session="feature",
            ),
            assistant(
                "2026-09-01T12:00:00Z",
                str(cls.repo),
                SONNET,
                {"input_tokens": 9_000_000, "output_tokens": 9_000_000},
                session="feature",
            ),
        ])
        (slug / "feature.jsonl").write_text(priced + "\n", encoding="utf-8")
        squash = "\n".join([
            user_line("2026-10-23T10:00:00Z", str(cls.repo), "fecha o pull/2", session="squash"),
            assistant(
                "2026-10-23T10:00:00Z",
                str(cls.repo),
                SONNET,
                {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_creation": {
                        "ephemeral_5m_input_tokens": 1_000,
                        "ephemeral_1h_input_tokens": 1_000,
                    },
                    "cache_creation_input_tokens": 99_999,
                    "cache_read_input_tokens": 0,
                },
                session="squash",
            ),
        ])
        (slug / "squash.jsonl").write_text(squash + "\n", encoding="utf-8")
        other = cls.projects / "outras"
        other.mkdir()
        (other / "solta.jsonl").write_text(
            assistant(
                "2026-10-23T09:00:00Z",
                "/tmp/rot-pasta-que-nao-existe",
                "claude-inexistente",
                {"input_tokens": 500, "output_tokens": 0},
                session="solta",
            ) + "\n",
            encoding="utf-8",
        )
        naive = cls.projects / "naive"
        naive.mkdir()
        (naive / "naive.jsonl").write_text(
            assistant(
                "2026-10-23T09:30:00",
                str(cls.repo),
                SONNET,
                {"input_tokens": 50, "output_tokens": 50},
                session="naive",
            ) + "\n",
            encoding="utf-8",
        )
        cls.cfg = rotlib.load_config()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def analyze(self, period: str, plan: str = "max-5x", **kwargs):
        spec = rotlib.plan_spec(self.cfg, plan, kwargs.pop("monthly", None), kwargs.pop("label", None))
        return rotlib.analyze(
            now=NOW,
            period_id=period,
            plan=spec,
            repos=[self.repo],
            projects_dir=self.projects,
            config=self.cfg,
            use_gh=False,
            include_cwd=False,
            **kwargs,
        )

    def test_seven_days_counts_merged_work_only(self):
        report = self.analyze("7d")
        self.assertEqual(report["loc"]["effective"], 28)
        self.assertEqual(report["loc"]["additions"], 24)
        self.assertEqual(report["loc"]["deletions"], 13)
        excluded = report["loc"]["excluded"]
        self.assertEqual(excluded["lockfile"]["lines"], 100)
        self.assertEqual(excluded["vendored"]["lines"], 50)
        self.assertEqual(excluded["generated"]["lines"], 40 + 15 + 7)
        self.assertEqual(excluded["snapshot"]["lines"], 20)
        numbers = sorted(pr["number"] for pr in report["pull_requests"])
        self.assertEqual(numbers, [1, 2])
        titles = " ".join(pr["title"] for pr in report["pull_requests"])
        self.assertNotIn("Corrige comentario", titles)
        self.assertNotIn("ainda nao entrou", titles)
        self.assertNotIn("#9", titles)

    def test_windows_and_direct_commit(self):
        day = self.analyze("24h")
        self.assertEqual([pr["number"] for pr in day["pull_requests"]], [2])
        self.assertEqual(day["loc"]["effective"], 5)
        month = self.analyze("30d")
        self.assertEqual(sorted(pr["number"] for pr in month["pull_requests"]), [1, 2])
        half = self.analyze("15d")
        self.assertEqual(sorted(pr["number"] for pr in half["pull_requests"]), [1, 2])

    def test_tokens_cost_and_attribution(self):
        report = self.analyze("7d")
        tokens = report["tokens"]
        self.assertEqual(tokens["input"], 1_000_500)
        self.assertEqual(tokens["output"], 100_000)
        self.assertEqual(tokens["cache_write_5m"], 1_000)
        self.assertEqual(tokens["cache_write_1h"], 1_000)
        self.assertEqual(tokens["cache_read"], 1_000_000)
        self.assertNotIn(9_000_000, (tokens["input"], tokens["output"]))
        cache_usd = 1_000 * 3.75 / 1_000_000 + 1_000 * 6.0 / 1_000_000
        self.assertAlmostEqual(report["cost"]["api_equivalent_usd"], 4.8 + cache_usd)
        self.assertAlmostEqual(report["cost"]["subscription_prorated_usd"], 700 / 30.4375)
        self.assertEqual(report["cost"]["primary_basis"], "subscription")
        self.assertAlmostEqual(report["cost"]["primary_brl"], report["cost"]["primary_usd"] * 5.0383)
        self.assertEqual(tokens["unpriced_tokens"]["claude-inexistente"], 500)
        self.assertAlmostEqual(report["ratios"]["effective_loc_per_million_tokens"], 28 / (tokens["total"] / 1_000_000))
        by_number = {pr["number"]: pr for pr in report["pull_requests"]}
        self.assertGreater(by_number[1]["attributed_tokens"]["input"], 0)
        self.assertGreater(by_number[2]["attributed_tokens"]["cache_write_1h"], 0)
        text = rotlib.render_text(report)
        self.assertIn("Linhas efetivas", text)
        self.assertIn("US$", text)
        self.assertIn("R$", text)
        sem_real = rotlib.render_text(self.analyze("24h", exchange_rate=0.0))
        self.assertNotIn("R$", sem_real)
        self.assertNotIn("Em reais", sem_real)
        self.assertTrue(any("sem data confiável" in warning for warning in report["warnings"]))
        self.assertTrue(any("claude-inexistente" in warning for warning in report["warnings"]))

    def test_api_plan_uses_token_price_as_primary(self):
        report = self.analyze("7d", plan="api")
        self.assertEqual(report["cost"]["primary_basis"], "api")
        self.assertAlmostEqual(report["cost"]["primary_usd"], report["cost"]["api_equivalent_usd"])
        self.assertEqual(report["cost"]["subscription_prorated_usd"], 0.0)
        text = rotlib.render_text(report)
        self.assertNotIn("Assinatura proporcional", text)

    def test_zero_loc_does_not_divide(self):
        report = self.analyze("24h")
        # 24h has LOC. Build an empty projects + repo with no in-window PR by using a future now.
        future = dt.datetime(2026, 12, 1, tzinfo=dt.timezone.utc)
        spec = rotlib.plan_spec(self.cfg, "pro-monthly", None, None)
        empty = rotlib.analyze(
            now=future,
            period_id="24h",
            plan=spec,
            repos=[self.repo],
            projects_dir=self.projects,
            config=self.cfg,
            use_gh=False,
            include_cwd=False,
        )
        self.assertEqual(empty["loc"]["effective"], 0)
        self.assertIsNone(empty["ratios"]["usd_per_effective_loc"])
        self.assertIn("não se aplica", rotlib.render_text(empty))
        self.assertIn("Nenhum pull request", rotlib.render_text(empty))

    def test_rebase_pr_from_github_is_counted_once(self):
        repo = self.root / "rebase-app"
        repo.mkdir()
        git(repo, "init", "-b", "main")
        write(repo, "README.md", "base\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-m", "base", when="2026-10-18T12:00:00+00:00")
        write(repo, "src/b.py", "b1\nb2\nb3\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-m", "reword B", when="2026-10-21T12:00:00+00:00")
        first = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        write(repo, "src/c.py", "c1\nc2\nc3\nc4\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-m", "reword C", when="2026-10-22T12:00:00+00:00")
        tip = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()

        def fetcher(_repo, _branch, _start, _end):
            return [{
                "number": 5,
                "title": "Rebase da entrega",
                "merged_at": dt.datetime(2026, 10, 22, 12, 0, tzinfo=dt.timezone.utc),
                "sha": tip,
                "url": "https://example.com/pull/5",
                "commit_oids": [first, tip],
            }]

        spec = rotlib.plan_spec(self.cfg, "api", None, None)
        report = rotlib.analyze(
            now=NOW,
            period_id="7d",
            plan=spec,
            repos=[repo],
            projects_dir=self.root / "logs-vazios",
            config=self.cfg,
            use_gh=True,
            gh_fetcher=fetcher,
            include_cwd=False,
        )
        self.assertEqual(len(report["pull_requests"]), 1)
        pr = report["pull_requests"][0]
        self.assertEqual(pr["number"], 5)
        self.assertEqual(pr["loc"]["effective"], 7)
        self.assertEqual(report["loc"]["effective"], 7)
        self.assertTrue(any("logs do Claude Code" in warning for warning in report["warnings"]))

    def test_gh_failure_falls_back(self):
        def fetcher(*_args):
            return None

        spec = rotlib.plan_spec(self.cfg, "api", None, None)
        report = rotlib.analyze(
            now=NOW,
            period_id="7d",
            plan=spec,
            repos=[self.repo],
            projects_dir=self.projects,
            config=self.cfg,
            use_gh=True,
            gh_fetcher=fetcher,
            include_cwd=False,
        )
        self.assertEqual(sorted(pr["number"] for pr in report["pull_requests"]), [1, 2])
        self.assertTrue(any("só pelo git" in warning for warning in report["warnings"]))


class CliTests(unittest.TestCase):
    def test_noninteractive_asks_for_period_in_portuguese(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "rot_report.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Qual período? 24 horas, 7 dias, 15 dias ou 30 dias", result.stderr)

    def test_invalid_plan(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "rot_report.py"), "--period", "7d", "--plan", "maximo"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Plano inválido", result.stderr)

    def test_custom_requires_monthly(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "rot_report.py"), "--period", "7d", "--plan", "custom"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("mensalidade", result.stderr)

    def test_prompt_accepts_the_four_periods(self):
        answers = iter(["7 dias"])
        chosen = rotlib.prompt_period(input_fn=lambda _prompt="": next(answers), output_fn=lambda _text: None)
        self.assertEqual(chosen, "7d")
        plan_answers = iter(["6", "42", "Ferramenta X"])
        plan = rotlib.prompt_plan(
            rotlib.load_config(),
            input_fn=lambda _prompt="": next(plan_answers),
            output_fn=lambda _text: None,
        )
        self.assertEqual(plan["id"], "custom")
        self.assertEqual(plan["monthly_usd"], 42.0)
        self.assertEqual(plan["label"], "Ferramenta X")

    def test_cli_on_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_repo(root)
            projects = root / "projects"
            projects.mkdir()
            report = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "rot_report.py"),
                    "--period", "7d",
                    "--plan", "max-5x",
                    "--repo", str(repo),
                    "--projects-dir", str(projects),
                    "--now", "2026-10-23T15:00:00+00:00",
                    "--no-gh",
                    "--no-cwd",
                    "--exchange-rate", "5.0383",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(report.returncode, 0, report.stderr)
            self.assertIn("linhas efetivas", report.stdout)
            self.assertIn("28", report.stdout)
            self.assertIn("US$", report.stdout)
            self.assertIn("R$", report.stdout)
            self.assertIn("RESSALVAS", report.stdout)


class DocTests(unittest.TestCase):
    def test_readme_and_example_are_portuguese(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        example = (ROOT / "skills" / "return-on-tokens" / "examples" / "exemplo-relatorio.txt").read_text(encoding="utf-8")
        for heading in (
            "O que é Return on Tokens (ROT)",
            "Como funciona",
            "Como instalar",
            "Como usar",
            "Metodologia e limitações",
            "Exemplo de saída",
        ):
            self.assertIn(heading, readme)
        self.assertIn("Qual período? 24 horas, 7 dias, 15 dias ou 30 dias", readme)
        self.assertIn("Linhas efetivas", example)
        self.assertIn("R$ 115,87", example)
        self.assertIn("US$ 23,00", readme)
        self.assertNotIn("/tmp/", example)
        self.assertNotIn("/Users/", example)


class PrivacyTests(unittest.TestCase):
    def test_shipped_tree_has_no_private_markers(self):
        banned = [
            "contably",
            "nuvini",
            "overseer",
            "psm2",
            "gbrain",
            "qmd",
            "claude-setup",
            "ledger.jsonl",
            "/Users/",
            "Fable-tier",
            "fable-tier",
            "datavoz",
            "xurman",
            "investor",
            "one-pager",
            "alice",
        ]
        roots = [
            ROOT / "README.md",
            ROOT / "LICENSE",
            ROOT / "skills",
        ]
        blobs = []
        for item in roots:
            if item.is_file():
                blobs.append((item, item.read_text(encoding="utf-8").lower()))
            else:
                for path in item.rglob("*"):
                    if path.is_file() and "__pycache__" not in path.parts:
                        blobs.append((path, path.read_text(encoding="utf-8", errors="replace").lower()))
        for path, text in blobs:
            for marker in banned:
                self.assertNotIn(marker, text, f"{marker} em {path}")


if __name__ == "__main__":
    unittest.main()
