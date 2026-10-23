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
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "retorno-sobre-tokens" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rotlib  # noqa: E402
import rot_report  # noqa: E402
import rot_equipe  # noqa: E402

NOW = dt.datetime(2026, 10, 23, 15, 0, tzinfo=dt.timezone.utc)
SONNET = "claude-sonnet-4-6"


GIT_ENV = {
    "GIT_AUTHOR_NAME": "Dev Exemplo",
    "GIT_AUTHOR_EMAIL": "dev@example.com",
    "GIT_COMMITTER_NAME": "Dev Exemplo",
    "GIT_COMMITTER_EMAIL": "dev@example.com",
}


def git(repo: Path, *args: str, when: str | None = None, author: str = "dev@example.com") -> None:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Dev Exemplo" if author == "dev@example.com" else "Colega Exemplo"
    env["GIT_AUTHOR_EMAIL"] = author
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

    # PR de uma colega, mesclado no mesmo ramo e no mesmo período: não é seu.
    git(repo, "checkout", "-b", "colega")
    write(repo, "src/colega.py", "".join(f"colega {i}\n" for i in range(6)))
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "trabalho da colega", when="2026-10-21T09:00:00+00:00", author="colega@example.com")
    git(repo, "checkout", "main")
    git(
        repo, "merge", "--no-ff", "colega",
        "-m", "Merge pull request #3 from colega/tarefa",
        when="2026-10-21T12:00:00+00:00",
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


def assistant(
    when: str,
    cwd: str,
    model: str,
    usage: dict,
    session: str = "s1",
    msg_id: str | None = None,
    request_id: str | None = None,
) -> str:
    record = {
        "type": "assistant",
        "timestamp": when,
        "cwd": cwd,
        "sessionId": session,
        "message": {"role": "assistant", "model": model, "usage": usage},
    }
    if msg_id:
        record["message"]["id"] = msg_id
    if request_id:
        record["requestId"] = request_id
    return json.dumps(record, ensure_ascii=False)


def user_line(when: str, cwd: str, text: str, session: str = "s1") -> str:
    return json.dumps({
        "type": "user",
        "timestamp": when,
        "cwd": cwd,
        "sessionId": session,
        "message": {"role": "user", "content": text},
    }, ensure_ascii=False)


def make_logs(root: Path, repo: Path) -> Path:
    """Logs JSONL de sessão, com as duplicatas que o Claude Code produz de verdade."""
    projects = root / "projects"
    slug = projects / "-tmp-sample-app"
    slug.mkdir(parents=True)
    priced = "\n".join([
        user_line("2026-10-19T12:00:00Z", str(repo), "segue o PR", session="feature"),
        assistant(
            "2026-10-19T12:05:00Z",
            str(repo),
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
            str(repo),
            SONNET,
            {"input_tokens": 9_000_000, "output_tokens": 9_000_000},
            session="feature",
        ),
    ])
    (slug / "feature.jsonl").write_text(priced + "\n", encoding="utf-8")
    squash = "\n".join([
        user_line("2026-10-23T10:00:00Z", str(repo), "fecha o pull/2", session="squash"),
        assistant(
            "2026-10-23T10:00:00Z",
            str(repo),
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
    other = projects / "outras"
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
    naive = projects / "naive"
    naive.mkdir()
    (naive / "naive.jsonl").write_text(
        assistant(
            "2026-10-23T09:30:00",
            str(repo),
            SONNET,
            {"input_tokens": 50, "output_tokens": 50},
            session="naive",
        ) + "\n",
        encoding="utf-8",
    )
    # Streaming: a mesma resposta gravada três vezes (uma por bloco), com o
    # mesmo message.id e requestId; o último registro traz o uso completo.
    parts = [
        assistant("2026-10-22T08:00:00Z", str(repo), SONNET, {"input_tokens": 20_000, "output_tokens": 1}, session="stream", msg_id="msg_01", request_id="req_01"),
        assistant("2026-10-22T08:00:01Z", str(repo), SONNET, {"input_tokens": 20_000, "output_tokens": 900}, session="stream", msg_id="msg_01", request_id="req_01"),
        assistant("2026-10-22T08:00:02Z", str(repo), SONNET, {"input_tokens": 20_000, "output_tokens": 2_000}, session="stream", msg_id="msg_01", request_id="req_01"),
    ]
    (slug / "stream.jsonl").write_text("\n".join(parts) + "\n", encoding="utf-8")
    # Sessão retomada: o arquivo novo repete a resposta antiga e acrescenta uma nova.
    resumed = [
        parts[-1],
        assistant("2026-10-22T09:00:00Z", str(repo), SONNET, {"input_tokens": 0, "output_tokens": 1_000}, session="retomada", msg_id="msg_02", request_id="req_02"),
    ]
    (slug / "retomada.jsonl").write_text("\n".join(resumed) + "\n", encoding="utf-8")
    # Sidechain: cópia idêntica de um arquivo inteiro em outra pasta.
    side = projects / "sidechain"
    side.mkdir()
    (side / "copia.jsonl").write_bytes((slug / "stream.jsonl").read_bytes())
    return projects


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

    def test_exact_match_and_date_suffix_only(self):
        usd, missing = rotlib.price_turn(self.cfg, "claude-opus-4-5", 1_000_000, 0, 0, 0, 0)
        self.assertIsNone(missing)
        self.assertAlmostEqual(usd, 5.0)
        # Sufixo de data de 8 dígitos sai só porque a tabela lista o nome base.
        usd, missing = rotlib.price_turn(self.cfg, "claude-opus-4-5-20251101", 1_000_000, 0, 0, 0, 0)
        self.assertIsNone(missing)
        self.assertAlmostEqual(usd, 5.0)
        usd, _ = rotlib.price_turn(self.cfg, "claude-opus-4-1-20250805", 1_000_000, 0, 0, 0, 0)
        self.assertAlmostEqual(usd, 15.0)
        usd, _ = rotlib.price_turn(self.cfg, "claude-sonnet-5-5-20261001", 0, 0, 0, 0, 1_000_000)
        self.assertAlmostEqual(usd, 0.10)

    def test_no_prefix_guessing(self):
        # Antes, estes casavam pelo prefixo mais longo e ganhavam preço emprestado.
        for model in (
            "claude-opus-4-6[1m]",
            "claude-sonnet-5-5-preview",
            "claude-opus-4-5-2025",
            "claude-opus-4-5-20251101-v2",
            "claude-opus-9-20260101",
            "claude-opus",
        ):
            usd, missing = rotlib.price_turn(self.cfg, model, 1_000_000, 0, 0, 0, 0)
            self.assertEqual(usd, 0.0, model)
            self.assertEqual(missing, model)

    def test_explicit_alias_is_exact(self):
        cfg = dict(self.cfg)
        cfg["model_aliases"] = {"_comment": "x", "claude-opus-4-6[1m]": "claude-opus-4-6", "quebrado": "nao-existe"}
        usd, missing = rotlib.price_turn(cfg, "claude-opus-4-6[1m]", 1_000_000, 0, 0, 0, 0)
        self.assertIsNone(missing)
        self.assertAlmostEqual(usd, 5.0)
        self.assertEqual(rotlib.price_turn(cfg, "claude-opus-4-6[1m]x", 1_000_000, 0, 0, 0, 0), (0.0, "claude-opus-4-6[1m]x"))
        self.assertEqual(rotlib.price_turn(cfg, "quebrado", 1, 0, 0, 0, 0), (0.0, "quebrado"))

    def test_cost_breakdown_by_type(self):
        parts = rotlib.price_breakdown(self.cfg, SONNET, 1_000_000, 100_000, 1_000_000, 0, 1_000_000)
        self.assertAlmostEqual(parts["input"], 3.0)
        self.assertAlmostEqual(parts["output"], 1.5)
        self.assertAlmostEqual(parts["cache_write_5m"], 3.75)
        self.assertAlmostEqual(parts["cache_read"], 0.30)
        self.assertIsNone(rotlib.price_breakdown(self.cfg, "claude-inexistente", 1, 1, 1, 1, 1))

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
        cls.projects = make_logs(cls.root, cls.repo)
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
            **{"authors": ["dev@example.com"], **kwargs},
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
        self.assertEqual(tokens["input"], 1_020_500)
        self.assertEqual(tokens["output"], 103_000)
        self.assertEqual(tokens["cache_write_5m"], 1_000)
        self.assertEqual(tokens["cache_write_1h"], 1_000)
        self.assertEqual(tokens["cache_read"], 1_000_000)
        self.assertNotIn(9_000_000, (tokens["input"], tokens["output"]))
        cache_usd = 1_000 * 3.75 / 1_000_000 + 1_000 * 6.0 / 1_000_000
        stream_usd = 20_000 * 3.0 / 1_000_000 + 3_000 * 15.0 / 1_000_000
        self.assertAlmostEqual(report["cost"]["api_equivalent_usd"], 4.8 + cache_usd + stream_usd)
        self.assertAlmostEqual(sum(tokens["cost_by_type_usd"].values()), report["cost"]["api_equivalent_usd"])
        self.assertEqual(tokens["unpriced_total"], 500)
        self.assertEqual(tokens["unpriced_by_type"]["input"], 500)
        self.assertAlmostEqual(report["cost"]["subscription_prorated_usd"], 700 / 30.4375)
        self.assertEqual(report["cost"]["primary_basis"], "subscription")
        self.assertAlmostEqual(report["cost"]["primary_brl"], report["cost"]["primary_usd"] * 5.0383)
        self.assertEqual(tokens["unpriced_tokens"]["claude-inexistente"], 500)
        self.assertAlmostEqual(report["ratios"]["effective_loc_per_million_output_tokens"], 28 / 0.103)
        self.assertNotIn("effective_loc_per_million_tokens", report["ratios"])
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
        self.assertTrue(any("claude-inexistente" in warning and "SEM PREÇO" in warning for warning in report["warnings"]))
        self.assertIn("Sem preço (fora do custo)", text)
        self.assertIn("Linhas efetivas por milhão de tokens de SAÍDA", text)
        self.assertNotIn("Idem, só repositórios", text)
        self.assertIn("% do custo", text)

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
            authors=["dev@example.com"],
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
            authors=["dev@example.com"],
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
            authors=["dev@example.com"],
        )
        self.assertEqual(sorted(pr["number"] for pr in report["pull_requests"]), [1, 2])
        self.assertTrue(any("só pelo git" in warning for warning in report["warnings"]))



class DedupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = rotlib.load_config()
        self.start = NOW - dt.timedelta(days=7)

    def tearDown(self):
        self.tmp.cleanup()

    def scan(self):
        return rotlib.scan_projects(self.root, self.cfg, self.start, NOW)

    def test_streaming_rewrites_count_once_with_final_usage(self):
        lines = [
            assistant("2026-10-22T08:00:00Z", "/x", SONNET, {"input_tokens": 1_000, "output_tokens": 5}, msg_id="m1", request_id="r1"),
            assistant("2026-10-22T08:00:01Z", "/x", SONNET, {"input_tokens": 1_000, "output_tokens": 300}, msg_id="m1", request_id="r1"),
            assistant("2026-10-22T08:00:02Z", "/x", SONNET, {"input_tokens": 1_000, "output_tokens": 120}, msg_id="m1", request_id="r1"),
            assistant("2026-10-22T08:01:00Z", "/x", SONNET, {"input_tokens": 10, "output_tokens": 10}, msg_id="m2", request_id="r2"),
        ]
        (self.root / "a.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        sessions, _warnings, stats = self.scan()
        bucket = rotlib.sum_sessions(sessions)
        self.assertEqual(bucket["input"], 1_010)
        self.assertEqual(bucket["output"], 310)
        self.assertEqual(stats["records"], 4)
        self.assertEqual(stats["unique"], 2)
        self.assertEqual(stats["duplicates"], 2)

    def test_resumed_session_and_identical_file_across_folders(self):
        first = assistant("2026-10-22T08:00:00Z", "/x", SONNET, {"input_tokens": 500, "output_tokens": 50}, session="s1", msg_id="m1", request_id="r1")
        second = assistant("2026-10-22T09:00:00Z", "/x", SONNET, {"input_tokens": 7, "output_tokens": 3}, session="s2", msg_id="m9", request_id="r9")
        (self.root / "p1").mkdir()
        (self.root / "p2").mkdir()
        (self.root / "p1" / "s1.jsonl").write_text(first + "\n", encoding="utf-8")
        (self.root / "p1" / "s2.jsonl").write_text(first + "\n" + second + "\n", encoding="utf-8")
        (self.root / "p2" / "copia.jsonl").write_text(first + "\n", encoding="utf-8")
        sessions, _warnings, stats = self.scan()
        bucket = rotlib.sum_sessions(sessions)
        self.assertEqual(bucket["input"], 507)
        self.assertEqual(bucket["output"], 53)
        self.assertEqual(stats["duplicate_files"], 1)
        self.assertEqual(stats["duplicates"], 1)

    def test_same_message_id_different_request_is_not_merged(self):
        lines = [
            assistant("2026-10-22T08:00:00Z", "/x", SONNET, {"input_tokens": 100}, msg_id="m1", request_id="r1"),
            assistant("2026-10-22T08:00:00Z", "/x", SONNET, {"input_tokens": 100}, msg_id="m1", request_id="r2"),
        ]
        (self.root / "a.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        sessions, _warnings, _stats = self.scan()
        self.assertEqual(rotlib.sum_sessions(sessions)["input"], 200)

    def test_records_without_ids_still_count(self):
        lines = [
            assistant("2026-10-22T08:00:00Z", "/x", SONNET, {"input_tokens": 100}),
            assistant("2026-10-22T08:00:00Z", "/x", SONNET, {"input_tokens": 100}),
        ]
        (self.root / "a.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        sessions, _warnings, _stats = self.scan()
        self.assertEqual(rotlib.sum_sessions(sessions)["input"], 200)

    def test_end_to_end_fixture_reports_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_repo(root)
            projects = make_logs(root, repo)
            report = rotlib.analyze(
                now=NOW, period_id="7d", plan=rotlib.plan_spec(self.cfg, "api", None, None),
                repos=[repo], projects_dir=projects, config=self.cfg, use_gh=False, authors=["dev@example.com"],
            )
            self.assertEqual(report["tokens"]["output"], 103_000)
            self.assertEqual(report["dedup"]["duplicates"], 3)
            self.assertEqual(report["dedup"]["duplicate_files"], 1)
            self.assertIn("Duplicatas descartadas", rotlib.render_text(report))


class AuthorshipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.repo = make_repo(cls.root)
        cls.cfg = rotlib.load_config()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_with(self, **kwargs):
        return rotlib.analyze(
            now=NOW, period_id="7d", plan=rotlib.plan_spec(self.cfg, "api", None, None),
            repos=[self.repo], projects_dir=self.root / "sem-logs", config=self.cfg,
            include_cwd=False, **{"use_gh": False, **kwargs},
        )

    def test_other_author_pr_is_excluded_and_reported(self):
        report = self.run_with(authors=["dev@example.com"])
        self.assertEqual(sorted(pr["number"] for pr in report["pull_requests"]), [1, 2])
        self.assertEqual(report["other_authors"]["pull_requests"], 1)
        self.assertEqual(report["other_authors"]["effective"], 6)
        text = rotlib.render_text(report)
        self.assertIn("PRs de outros autores fora da conta: 1 (6 linhas efetivas, 1 autor)", text)

    def test_colleague_sees_only_her_pr(self):
        report = self.run_with(authors=["colega@example.com"])
        self.assertEqual([pr["number"] for pr in report["pull_requests"]], [3])
        self.assertEqual(report["loc"]["effective"], 6)
        self.assertEqual(report["other_authors"]["pull_requests"], 2)

    def test_gh_author_login_wins_over_email(self):
        def fetcher(repo, _branch, _start, _end):
            items = []
            for number in (1, 3):
                sha = subprocess.check_output(
                    ["git", "-C", str(repo), "log", "--format=%H", "--grep", f"#{number} from", "main"], text=True
                ).split()[0]
                items.append({
                    "number": number, "title": f"PR {number}", "sha": sha,
                    "merged_at": NOW, "url": f"https://github.com/org/app/pull/{number}",
                    "commit_oids": None, "author_login": "colega-gh" if number == 1 else "eu-gh",
                })
            return items

        report = self.run_with(use_gh=True, gh_fetcher=fetcher, authors=["eu-gh"])
        # PR #1 tem commits com o meu e-mail, mas o GitHub diz que a autora é a colega.
        self.assertEqual([pr["number"] for pr in report["pull_requests"]], [3])
        self.assertEqual(report["other_authors"]["pull_requests"], 2)

    def test_identity_resolution_order(self):
        cfg = dict(self.cfg)
        cfg["autores"] = {"logins": ["Config-Login"], "emails": []}
        ident = rotlib.resolve_identity(cfg, ["Eu@Example.com", "meu-login"], True, [], login_fetcher=lambda: "gh")
        self.assertEqual(ident, {"logins": ["meu-login"], "emails": ["eu@example.com"], "sources": ["--autor"]})
        ident = rotlib.resolve_identity(cfg, None, True, [self.repo], login_fetcher=lambda: "gh")
        self.assertEqual(ident["logins"], ["config-login"])
        ident = rotlib.resolve_identity(self.cfg, None, True, [self.repo], login_fetcher=lambda: "Do-GH")
        self.assertEqual(ident["logins"], ["do-gh"])
        self.assertIn("gh api user", ident["sources"])

    def test_noreply_email_matches_login(self):
        pr = {"author_login": None, "author_email": "123+fulana@users.noreply.github.com"}
        self.assertTrue(rotlib.pr_is_mine(pr, {"logins": ["fulana"], "emails": []}))
        self.assertFalse(rotlib.pr_is_mine(pr, {"logins": ["outra"], "emails": []}))

    def test_without_identity_nothing_counts(self):
        report = self.run_with(identity={"logins": [], "emails": [], "sources": []})
        self.assertEqual(report["pull_requests"], [])
        self.assertTrue(any("Não sei quem é você" in warning for warning in report["warnings"]))

    def test_require_session_overlap(self):
        projects = self.root / "logs-sessao"
        (projects / "p").mkdir(parents=True, exist_ok=True)
        (projects / "p" / "s.jsonl").write_text(
            assistant("2026-10-23T09:59:00Z", str(self.repo), SONNET, {"input_tokens": 1}, msg_id="m", request_id="r") + "\n",
            encoding="utf-8",
        )
        report = rotlib.analyze(
            now=NOW, period_id="7d", plan=rotlib.plan_spec(self.cfg, "api", None, None),
            repos=[self.repo], projects_dir=projects, config=self.cfg, use_gh=False,
            authors=["dev@example.com"], require_session=True,
        )
        self.assertEqual([pr["number"] for pr in report["pull_requests"]], [2])
        self.assertEqual(report["without_session"]["pull_requests"], 1)


def team_env() -> dict:
    env = os.environ.copy()
    env.update(GIT_ENV)
    return env


class TeamTests(unittest.TestCase):
    """Ciclo completo com um repositório git bare local fazendo papel de central."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_repo(self.root)
        self.projects = make_logs(self.root, self.repo)
        self.bare = self.root / "rot-equipe.git"
        subprocess.check_call(["git", "init", "--quiet", "--bare", "-b", "main", str(self.bare)])
        self.cfg = rotlib.load_config()
        self.env_patch = unittest.mock.patch.dict(os.environ, GIT_ENV)
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.tmp.cleanup()

    def central(self, who: str):
        return rot_equipe.Central(str(self.bare), "main", self.root / f"cache-{who}")

    def remote_file(self, relative: str) -> str:
        return subprocess.check_output(["git", "-C", str(self.bare), "show", f"main:{relative}"], text=True)

    def open(self, **kwargs):
        args = {
            "central": self.central("cto"), "config": self.cfg, "period_id": "7d", "now": NOW,
            "round_id": None, "roster": ["dev-a", "dev-b", "dev-c"], "plan_default": "max-5x", "opened_by": None,
        }
        args.update(kwargs)
        return rot_equipe.open_round(**args)

    def send(self, login: str, email: str = "dev@example.com", rodada: str = "2026-10-23_7d"):
        return rot_equipe.submit(
            central=self.central(login), config=self.cfg, rodada=rodada, login=login,
            plan_id=None, monthly_usd=None, plan_label=None, stdin_is_tty=False,
            analyze_kwargs={
                "repos": [self.repo], "projects_dir": self.projects, "use_gh": False, "include_cwd": False,
                "identity": {"logins": [login], "emails": [email], "sources": ["teste"]},
            },
        )

    def test_open_send_close_cycle(self):
        meta = self.open()
        self.assertEqual(meta["rodada"], "2026-10-23_7d")
        readme = self.remote_file("2026-10-23_7d/README.md")
        self.assertIn("enviar --rodada 2026-10-23_7d --repo-central", readme)
        self.assertIn("roda o ROT da rodada 2026-10-23_7d", readme)
        stored = json.loads(self.remote_file("2026-10-23_7d/rodada.json"))
        self.assertEqual(stored["period"]["start"], "2026-10-16T15:00:00+00:00")
        self.assertEqual(stored["roster"], ["dev-a", "dev-b", "dev-c"])
        with self.assertRaises(rot_equipe.TeamError):
            self.open()

        payload, _meta, _link = self.send("dev-a")
        self.assertEqual(payload["loc"]["effective"], 28)
        self.assertEqual(payload["plan"]["id"], "max-5x")
        self.assertEqual(payload["period"]["end"], "2026-10-23T15:00:00+00:00")
        self.assertEqual(payload["other_authors_excluded"]["pull_requests"], 1)
        raw = self.remote_file("2026-10-23_7d/dev-a.json")
        self.assertNotIn(str(self.root), raw)
        self.assertNotIn("segue o PR", raw)
        self.assertNotIn("repo_path", raw)
        self.assertNotIn("@example.com", raw)
        for key in ("schema_version", "tool_version", "generated_at"):
            self.assertIn(key, json.loads(raw))
        # dev-b mede o mesmo repositório: os mesmos PRs contam uma vez no total.
        self.send("dev-b")

        cto = self.central("cto")
        with self.assertRaises(rot_equipe.TeamError) as caught:
            rot_equipe.close_round(central=cto, config=self.cfg, rodada="2026-10-23_7d",
                                   generate_anyway=False, stdin_is_tty=False, output_fn=lambda _t: None)
        self.assertIn("Faltam dev-c. Gerar o total assim mesmo (s) ou esperar (n)?", str(caught.exception))
        asked = []
        waited = rot_equipe.close_round(
            central=cto, config=self.cfg, rodada="2026-10-23_7d", generate_anyway=False, stdin_is_tty=True,
            input_fn=lambda prompt: asked.append(prompt) or "n", output_fn=lambda _t: None,
        )
        self.assertIsNone(waited)
        self.assertEqual(asked[0].strip(), "Faltam dev-c. Gerar o total assim mesmo (s) ou esperar (n)?")
        summary = rot_equipe.close_round(
            central=cto, config=self.cfg, rodada="2026-10-23_7d", generate_anyway=False, stdin_is_tty=True,
            input_fn=lambda _p: "s", output_fn=lambda _t: None,
        )
        self.assertEqual(summary["sent"], ["dev-a", "dev-b"])
        self.assertEqual(summary["missing"], ["dev-c"])
        self.assertEqual(summary["total"]["effective"], 28)
        self.assertEqual(summary["total"]["pull_requests"], 2)
        self.assertEqual(summary["total"]["shared_pull_requests"], 2)
        self.assertEqual(summary["total"]["tokens"]["output"], 2 * 103_000)
        self.assertAlmostEqual(summary["total"]["primary_usd"], 2 * 700 / 30.4375)
        text = rot_equipe.render_team(summary, 5.0383)
        self.assertLess(text.index("TOTAL DA EQUIPE"), text.index("POR DESENVOLVEDOR"))
        self.assertIn("dev-c", text.split("POR DESENVOLVEDOR")[1])
        self.assertIn("não enviou", text)
        link = rot_equipe.publish_summary(cto, "2026-10-23_7d", text)
        self.assertIn("resumo.md", link)
        self.assertIn("TOTAL DA EQUIPE", self.remote_file("2026-10-23_7d/resumo.md"))

    def test_mismatched_period_is_flagged(self):
        self.open(roster=["dev-a", "dev-b"])
        self.send("dev-a")
        payload, _meta, _link = self.send("dev-b")
        payload["period"]["start"] = "2026-10-01T15:00:00+00:00"
        self.central("dev-b").publish(
            {"2026-10-23_7d/dev-b.json": json.dumps(payload)}, "periodo trocado"
        )
        summary = rot_equipe.close_round(
            central=self.central("cto"), config=self.cfg, rodada="2026-10-23_7d",
            generate_anyway=True, stdin_is_tty=False, output_fn=lambda _t: None,
        )
        self.assertEqual(summary["mismatched_period"], ["dev-b"])
        self.assertIn("!! Período diferente do da rodada: dev-b", rot_equipe.render_team(summary))

    def test_unknown_round_and_link_parsing(self):
        with self.assertRaises(rot_equipe.TeamError):
            self.send("dev-a", rodada="nao-existe")
        self.assertEqual(
            rot_equipe.round_id_from_link("https://github.com/org/rot-equipe/blob/main/2026-10-23_7d/README.md"),
            "2026-10-23_7d",
        )
        self.assertEqual(
            rot_equipe.Central("git@github.com:org/rot-equipe.git", "main", self.root).link("r/README.md"),
            "https://github.com/org/rot-equipe/blob/main/r/README.md",
        )
        with self.assertRaises(rot_equipe.TeamError):
            rot_equipe.check_round_id("../fora")
        self.assertEqual(
            rot_equipe.central_from_link("https://github.com/org/rot-equipe/blob/main/2026-10-23_7d/README.md"),
            ("https://github.com/org/rot-equipe.git", "main"),
        )
        args = unittest.mock.Mock(repo_central=None, ramo=None, cache_dir=str(self.root / "c"),
                                  rodada="https://github.com/org/rot-equipe/blob/main/2026-10-23_7d/README.md")
        central = rot_equipe.central_from(args, self.cfg)
        self.assertEqual((central.target, central.branch), ("https://github.com/org/rot-equipe.git", "main"))

    def test_local_folder_central(self):
        folder = self.root / "pasta-central"
        central = rot_equipe.Central(str(folder), "main", None)
        self.assertFalse(central.is_git)
        rot_equipe.open_round(central=central, config=self.cfg, period_id="24h", now=NOW, round_id="teste",
                              roster=["dev-a"], plan_default="api", opened_by=None)
        rot_equipe.submit(
            central=central, config=self.cfg, rodada="teste", login="dev-a", plan_id=None, monthly_usd=None,
            plan_label=None, stdin_is_tty=False,
            analyze_kwargs={"repos": [self.repo], "projects_dir": self.projects, "use_gh": False,
                            "include_cwd": False, "identity": {"logins": [], "emails": ["dev@example.com"], "sources": []}},
        )
        self.assertTrue((folder / "teste" / "dev-a.json").is_file())
        summary = rot_equipe.close_round(central=central, config=self.cfg, rodada="teste",
                                         generate_anyway=False, stdin_is_tty=False, output_fn=lambda _t: None)
        self.assertEqual(summary["total"]["effective"], 5)

    def test_cli_cycle(self):
        script = str(SCRIPTS / "rot_report.py")
        common = ["--repo-central", str(self.bare)]
        env = team_env()

        def run(*args, who="cto"):
            return subprocess.run(
                [sys.executable, script, *args, *common, "--cache-dir", str(self.root / f"cli-{who}")],
                capture_output=True, text=True, check=False, env=env, stdin=subprocess.DEVNULL,
            )

        opened = run("abrir-rodada", "--periodo", "7d", "--now", "2026-10-23T15:00:00+00:00", "--devs", "dev-a,dev-b", "--plano-padrao", "max-5x")
        self.assertEqual(opened.returncode, 0, opened.stderr)
        self.assertIn("Mande este link para os devs", opened.stdout)
        dev_args = (
            "--rodada", "2026-10-23_7d", "--login", "dev-a", "--autor", "dev@example.com",
            "--no-gh", "--no-cwd", "--repo", str(self.repo), "--projects-dir", str(self.projects),
        )
        unconfirmed = run("enviar", *dev_args, who="a")
        self.assertEqual(unconfirmed.returncode, 2)
        self.assertIn("Vou enviar como dev-a, contando só PRs de: dev@example.com. Confirma? (s/n)", unconfirmed.stderr)
        preview = run("exportar", *dev_args, who="a")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(json.loads(preview.stdout)["login"], "dev-a")
        self.assertNotIn(str(self.root), preview.stdout)
        sent = run("enviar", *dev_args, "--sim", who="a")
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertIn("28 linhas efetivas", sent.stdout)
        refused = run("fechar-rodada", "--rodada", "2026-10-23_7d")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("Faltam dev-b. Gerar o total assim mesmo (s) ou esperar (n)?", refused.stderr)
        closed = run("equipe", "--rodada", "2026-10-23_7d", "--gerar-mesmo-assim", "--gravar-resumo")
        self.assertEqual(closed.returncode, 0, closed.stderr)
        self.assertIn("TOTAL DA EQUIPE", closed.stdout)
        self.assertIn("dev-a", closed.stdout)
        self.assertIn("resumo.md", closed.stderr)


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
                    "--autor", "dev@example.com",
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


EXAMPLE = ROOT / "skills" / "retorno-sobre-tokens" / "examples" / "exemplo-relatorio.txt"


def example_text() -> str:
    """Roda o relatório de verdade sobre a fixture e troca os caminhos temporários.

    É daqui que sai examples/exemplo-relatorio.txt:
    python3 tests/test_rot.py --gerar-exemplo
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        repo = make_repo(root)
        projects = make_logs(root, repo)
        result = subprocess.run(
            [
                sys.executable, str(SCRIPTS / "rot_report.py"),
                "--period", "7d", "--plan", "max-5x",
                "--repo", str(repo), "--projects-dir", str(projects),
                "--now", "2026-10-23T15:00:00+00:00",
                "--no-gh", "--no-cwd", "--exchange-rate", "5.0383",
                "--autor", "dev@example.com",
            ],
            capture_output=True, text=True, check=True,
        )
        text = result.stdout
        text = text.replace(str(projects), "~/.claude/projects")
        text = text.replace(str(root), "~/codigo")
        text = text.replace(tmp, "~/codigo")
        return text


class DocTests(unittest.TestCase):
    def test_example_matches_a_real_run(self):
        self.assertEqual(
            EXAMPLE.read_text(encoding="utf-8"), example_text(),
            "Exemplo desatualizado. Rode: python3 tests/test_rot.py --gerar-exemplo",
        )


    def test_readme_and_example_are_portuguese(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        example = (ROOT / "skills" / "retorno-sobre-tokens" / "examples" / "exemplo-relatorio.txt").read_text(encoding="utf-8")
        for heading in (
            "O que é Retorno sobre Tokens (ROT)",
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
    if "--gerar-exemplo" in sys.argv:
        EXAMPLE.write_text(example_text(), encoding="utf-8")
        print(f"Gravado: {EXAMPLE.relative_to(ROOT)}")
    else:
        unittest.main()
