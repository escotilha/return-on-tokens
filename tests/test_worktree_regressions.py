import tempfile
import unittest
from pathlib import Path

from test_rot import NOW, SONNET, assistant, git, make_repo, rotlib


class WorktreeRegressionTests(unittest.TestCase):
    def test_worktrees_count_code_once_and_keep_all_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = make_repo(root)
            worktree = root / "worktree"
            git(repo, "worktree", "add", "-b", "audit", str(worktree))
            logs = root / "logs"
            logs.mkdir()
            for index, path in enumerate((repo, worktree)):
                (logs / f"{index}.jsonl").write_text(assistant(
                    "2026-10-23T10:00:00+00:00", str(path), SONNET,
                    {"input_tokens": 100, "output_tokens": 50},
                    session=f"session-{index}", msg_id=f"message-{index}",
                ))
            config = rotlib.load_config()
            for paths in ([repo, worktree], [worktree, repo], []):
                with self.subTest(paths=paths):
                    report = rotlib.analyze(
                        now=NOW, period_id="7d",
                        plan=rotlib.plan_spec(config, "api", None, None),
                        repos=paths, projects_dir=logs, config=config,
                        use_gh=False, authors=["dev@example.com"],
                    )
                    self.assertEqual(report["loc"]["effective"], 28)
                    self.assertEqual(len(report["pull_requests"]), 2)
                    self.assertEqual(len(report["by_repo"]), 1)
                    self.assertEqual(report["by_repo"][0]["tokens"], 300)
                    self.assertEqual(report["shipping_tokens"]["total"], 300)

    def test_distinct_repositories_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "first").mkdir()
            (root / "second").mkdir()
            first = make_repo(root / "first")
            second = make_repo(root / "second")
            self.assertEqual(rotlib._repo_list([first, second]), [first.resolve(), second.resolve()])
