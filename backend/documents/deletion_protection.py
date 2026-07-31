"""Process-wide deletion-blocker registry for DocumentVersion.

Dependent apps register a checker callable from their AppConfig.ready();
the documents app consults every registered checker before permitting a
DocumentVersion delete. This keeps the dependency direction one-way:
documents never imports iig_checklist or any other dependent app.

New Milestone 4D-2 infrastructure -- not present in earlier milestones.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from documents.models import DocumentVersion


class DocumentVersionDeleteForbidden(Exception):
    """Raised when a registered checker blocks DocumentVersion deletion."""


class DeletionProtectionRegistry:
    """Process-wide registry of deletion-blocker checkers for DocumentVersion.

    Register a checker from AppConfig.ready(); registration is idempotent.
    Check before any delete; fail-closed on checker exception.
    Checker iteration order is sorted by key for determinism.
    """

    _checkers: dict[str, Callable] = {}

    @classmethod
    def register(cls, key: str, checker: Callable) -> None:
        """Idempotent: registering the same key replaces the prior checker."""
        cls._checkers[key] = checker

    @classmethod
    def unregister(cls, key: str) -> None:
        cls._checkers.pop(key, None)

    @classmethod
    def check(cls, document_version: "DocumentVersion") -> list[str]:
        """Returns a list of blocking reason keys (empty if unblocked).

        Iterates checkers in sorted-key order for deterministic behaviour.
        Fail-closed: a checker that raises is treated as blocking.
        """
        blocking_reasons: list[str] = []
        for key in sorted(cls._checkers):
            checker = cls._checkers[key]
            try:
                if checker(document_version):
                    blocking_reasons.append(key)
            except Exception:
                blocking_reasons.append(f"{key}_check_failed")
        return blocking_reasons

    @classmethod
    @contextmanager
    def _isolated(cls):
        """Test-only context manager: snapshot and restore _checkers.

        Usage:
            with DeletionProtectionRegistry._isolated():
                # _checkers is reset to empty inside this block
                ...
            # _checkers restored to prior state on exit

        Never call from production code.
        """
        saved = dict(cls._checkers)
        cls._checkers.clear()
        try:
            yield
        finally:
            cls._checkers.clear()
            cls._checkers.update(saved)
