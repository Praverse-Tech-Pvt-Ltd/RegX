"""The exception the governed manager and service layer raise.

Its own module so `models` can import it without a cycle, matching
`submission_packages.governance` and the dossier apps before it.
"""


class IntegrationMutationForbidden(Exception):
    """Raised when a governed integration row is mutated outside the services."""
