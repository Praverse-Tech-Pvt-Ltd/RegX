"""The exception the governed managers and `save()` overrides raise.

Its own module so `models` can import it without a cycle, matching
`submission_dossiers.governance` and `dossier_upgrades.governance`.
"""


class PackageMutationForbidden(Exception):
    """Raised when a governed package row is mutated outside the service layer."""
