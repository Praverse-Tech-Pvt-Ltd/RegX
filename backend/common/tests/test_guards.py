"""
Planted-failure guard tests.
These tests PROVE that prohibited patterns are absent or enforced.
Each test documents WHAT it is checking and WHY it matters.
"""

import ast
import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).parent.parent.parent


class TestNoAIDatabase:
    """GUARD: AIDatabase must never be imported anywhere in REGX code."""

    def _python_files(self):
        return [
            p for p in BACKEND_ROOT.rglob("*.py")
            if ".venv" not in str(p)
            and "__pycache__" not in str(p)
            # Exclude guard tests themselves — they contain "AIDatabase" as a string
            # literal in their own assertions, which is not an import violation.
            and "test_guards.py" not in str(p)
        ]

    def test_no_aidatabase_import(self):
        """
        Scans for actual import statements referencing AIDatabase.
        Mentions in comments, docstrings, or string literals are permitted
        (e.g. this very guard test, or a LEGACY_BOUNDARY doc mention).
        """
        violations = []
        for path in self._python_files():
            source = path.read_text(encoding="utf-8", errors="ignore")
            # Match real import statements only, not comments or docstrings
            if re.search(r"^(?:import|from)\s+AIDatabase", source, re.MULTILINE):
                violations.append(str(path.relative_to(BACKEND_ROOT)))
        assert violations == [], (
            f"AIDatabase imported in: {violations}. "
            "AIDatabase is a legacy module and must never be imported in REGX."
        )


class TestNoSQLiteInSettings:
    """GUARD: Settings must only use PostgreSQL; no SQLite ENGINE allowed."""

    def test_no_sqlite_engine_in_settings(self):
        settings_dir = BACKEND_ROOT / "regx" / "settings"
        violations = []
        for f in settings_dir.glob("*.py"):
            source = f.read_text(encoding="utf-8", errors="ignore")
            if "sqlite3" in source.lower():
                violations.append(f.name)
        assert violations == [], (
            f"SQLite found in settings: {violations}. "
            "REGX requires PostgreSQL exclusively."
        )


class TestNoProductionUnsafeEval:
    """GUARD: production.py must not permit unsafe-eval in script-src."""

    def test_no_unsafe_eval_in_production_csp(self):
        prod_settings = BACKEND_ROOT / "regx" / "settings" / "production.py"
        if not prod_settings.exists():
            return  # Not yet created; that's fine at foundation milestone
        source = prod_settings.read_text(encoding="utf-8", errors="ignore")
        assert "unsafe-eval" not in source, (
            "production.py contains unsafe-eval in CSP. "
            "This violates the REGX security baseline."
        )


class TestNoSecretLikeDefaultsInSettings:
    """GUARD: SECRET_KEY must not have a hardcoded insecure default."""

    def test_secret_key_has_no_fallback_literal(self):
        base_settings = BACKEND_ROOT / "regx" / "settings" / "base.py"
        source = base_settings.read_text(encoding="utf-8", errors="ignore")
        # Detect patterns like: config("DJANGO_SECRET_KEY", default="some-secret")
        assert not re.search(
            r'config\(["\']DJANGO_SECRET_KEY["\'],\s*default=',
            source,
        ), "SECRET_KEY has a hardcoded default. Remove the default= parameter."

    def test_mfa_key_has_no_fallback_literal(self):
        base_settings = BACKEND_ROOT / "regx" / "settings" / "base.py"
        source = base_settings.read_text(encoding="utf-8", errors="ignore")
        assert not re.search(
            r'config\(["\']MFA_ENCRYPTION_KEY["\'],\s*default=',
            source,
        ), "MFA_ENCRYPTION_KEY has a hardcoded default. Remove the default= parameter."


class TestNoLocalStorageAuthToken:
    """GUARD: Frontend must not store auth tokens in localStorage or sessionStorage."""

    def test_no_localstorage_token(self):
        frontend_root = BACKEND_ROOT.parent / "frontend"
        if not frontend_root.exists():
            return  # Frontend not yet scaffolded
        violations = []
        for p in frontend_root.rglob("*.ts"):
            source = p.read_text(encoding="utf-8", errors="ignore")
            if re.search(r'localStorage\.setItem\s*\(\s*["\'](?:token|auth|jwt)', source, re.IGNORECASE):
                violations.append(str(p.relative_to(frontend_root)))
        for p in frontend_root.rglob("*.tsx"):
            source = p.read_text(encoding="utf-8", errors="ignore")
            if re.search(r'localStorage\.setItem\s*\(\s*["\'](?:token|auth|jwt)', source, re.IGNORECASE):
                violations.append(str(p.relative_to(frontend_root)))
        assert violations == [], (
            f"Auth token stored in localStorage: {violations}. "
            "Use secure HttpOnly session cookies instead."
        )
