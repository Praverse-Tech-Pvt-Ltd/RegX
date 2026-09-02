"""`docs/TASK_RELIABILITY.md` describes the tasks that actually exist.

WHY THIS TEST EXISTS

Milestone 16 found two false statements in that document, both of the same
kind: the code moved and the prose did not.

  * It gave `process_document_version` a 30s retry backoff. The task declares
    `default_retry_delay=60`, and both of its retry sites call `self.retry()`
    with no `countdown`, so the real delay is 60s.
  * It said "all four dispatch sites use `transaction.on_commit`". Milestone 15
    added that to `documents/tasks.py` and then deliberately reverted it, and
    this document was not corrected.

Neither was reachable by any behavioural test, because a reliability document
is not executable. An operator reasoning about recovery timing, or a reviewer
checking whether queued work can outrun its own transaction, would have been
misled by prose that every green test agreed with.

WHAT IS ASSERTED

The two facts that drifted: the retry backoff of every task, and which dispatch
sites defer. Both are read out of the source rather than restated here, so this
test cannot itself go stale in the way the document did -- it fails when they
disagree, and it does not care which one is wrong.

It deliberately does not try to parse the whole document. A test that demanded
an exact prose shape would be broken by any honest edit, and would be deleted
the first time someone improved a sentence.
"""

import re
from pathlib import Path

import pytest

DOC = Path(__file__).resolve().parents[3] / "docs" / "TASK_RELIABILITY.md"

#: (module path, task name) for every Celery task in the project.
TASKS = (
    ("documents/tasks.py", "scan_document_version"),
    ("documents/tasks.py", "process_document_version"),
    ("external_integrations/tasks.py", "run_connector_execution"),
)

BACKEND = Path(__file__).resolve().parents[2]


def _doc_text():
    return DOC.read_text(encoding="utf-8")


def _declared_backoff(module: str, task: str) -> int:
    """The `default_retry_delay` on the decorator immediately above `task`."""
    source = (BACKEND / module).read_text(encoding="utf-8")
    match = re.search(
        r"@shared_task\((?P<args>[^)]*)\)\s*\ndef\s+" + re.escape(task) + r"\b",
        source,
    )
    assert match, f"could not find the task decorator for {task} in {module}"
    args = match.group("args")
    delay = re.search(r"default_retry_delay\s*=\s*([A-Za-z_][A-Za-z0-9_]*|\d+)", args)
    assert delay, f"{task} declares no default_retry_delay"

    value = delay.group(1)
    if value.isdigit():
        return int(value)

    # The connector task names a module constant rather than inlining a number,
    # so resolve it the same way a reader would.
    constant = re.search(rf"^{re.escape(value)}\s*=\s*(\d+)", source, re.MULTILINE)
    assert constant, f"{task} uses {value} for its backoff and it is not defined in {module}"
    return int(constant.group(1))


def _doc_backoff(task: str) -> str:
    """The Backoff cell for `task` in the document's table."""
    for line in _doc_text().splitlines():
        if line.startswith("|") and f"`documents.{task}`" in line:
            return [c.strip() for c in line.split("|")][5]
        if line.startswith("|") and f"`external_integrations.{task}`" in line:
            return [c.strip() for c in line.split("|")][5]
    raise AssertionError(f"{task} is not listed in {DOC.name}")


class TestTheDocumentMatchesTheTasks:
    def test_every_task_is_listed(self):
        text = _doc_text()
        missing = [task for _module, task in TASKS if task not in text]
        assert missing == [], (
            f"{DOC.name} does not mention: {', '.join(missing)}. "
            "A task nobody wrote down is a task nobody plans recovery for."
        )

    def test_the_document_invents_no_tasks(self):
        """The other direction: a task that was removed but is still described."""
        described = set(
            re.findall(r"`(?:documents|external_integrations)\.([a-z_]+)`", _doc_text())
        )
        actual = {task for _module, task in TASKS}
        assert described <= actual, (
            f"{DOC.name} describes task(s) that do not exist: "
            f"{', '.join(sorted(described - actual))}"
        )

    @pytest.mark.parametrize("module,task", TASKS)
    def test_the_documented_backoff_is_the_declared_backoff(self, module, task):
        """THE regression test.

        This is the exact statement that was wrong: 30s in the document, 60s in
        the decorator. Read from both sides so neither can drift silently.
        """
        declared = _declared_backoff(module, task)
        documented = _doc_backoff(task)
        assert str(declared) in documented, (
            f"{task}: the document says backoff {documented!r} but the task "
            f"declares default_retry_delay={declared}"
        )


class TestTheDocumentMatchesTheDispatchSites:
    """Which sites defer to commit, counted from the source.

    The document claimed four deferred dispatches when three do. That is not a
    cosmetic error: the whole section exists to tell a reader whether queued
    work can reach a worker before its row is committed.
    """

    def _dispatch_sites(self):
        deferred, inline = [], []
        for path in BACKEND.rglob("*.py"):
            parts = path.parts
            if ".venv" in parts or "tests" in parts or "migrations" in parts:
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if ".delay(" not in line or line.strip().startswith("#"):
                    continue
                rel = path.relative_to(BACKEND).as_posix()
                (deferred if "on_commit" in line else inline).append(rel)
        return deferred, inline

    def test_three_sites_defer_and_one_is_inline(self):
        deferred, inline = self._dispatch_sites()
        assert len(deferred) == 3, f"expected 3 deferred dispatch sites, found {deferred}"
        assert inline == ["documents/tasks.py"], (
            f"expected exactly one deliberate inline dispatch, found {inline}. "
            "A new inline dispatch may be a task queued before its row is "
            "committed -- decide, then record the decision in "
            f"{DOC.name} and at the call site."
        )

    def test_the_document_does_not_claim_every_site_defers(self):
        """The literal false sentence, kept out by name."""
        text = _doc_text().lower()
        assert "all four dispatch sites use" not in text, (
            "the document claims all four dispatch sites defer to commit; one "
            "dispatches inline on purpose"
        )

    def test_the_inline_dispatch_explains_itself_at_the_call_site(self):
        """A deliberate exception is only deliberate if it says so where it is."""
        source = (BACKEND / "documents" / "tasks.py").read_text(encoding="utf-8")
        assert "inline" in source.lower() and "deliberate" in source.lower(), (
            "documents/tasks.py dispatches inline without recording why, so the "
            "next reader cannot tell a decision from an oversight"
        )
