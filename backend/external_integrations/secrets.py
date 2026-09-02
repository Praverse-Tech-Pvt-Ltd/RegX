"""Resolving a credential reference to a secret, without ever storing one.

RegX stores the *name* of a secret, never a secret. `ConnectorCredentialReference`
is a label saying "this connector authenticates with a bearer token, and the
deployment knows it as REGX_CONNECTOR_<public-id>_TOKEN". The value lives in the
process environment, put there by whatever the deployment uses for secrets.

WHAT THIS IS NOT
----------------
This is not a secret manager. It has no rotation, no versioning, no access log
of its own, no envelope encryption and no per-tenant key separation. It reads an
environment variable. Saying so plainly is the point: a module named `secrets`
that quietly implied more would be worse than one that implies nothing.

The consequence, documented rather than hidden: a retry after a rotation
resolves the *current* value, because nothing anywhere records which value was
used. Pinning a credential version is secret-manager work and is out of scope.

RULES THAT DO NOT BEND
----------------------
No default. No development fallback. No hard-coded value. A missing secret is a
loud, enumerated failure and never an empty string that produces an
unauthenticated request nobody notices. The value is never logged, never
returned through the API, never written to audit, and never put in an exception
message -- `SecretUnavailable` names the *reference*, which is not secret,
because it is the thing an operator needs in order to fix the problem.
"""

from __future__ import annotations

import os

#: The environment variable a reference resolves to, when a deployment has not
#: named one explicitly. Keyed on the connector's public id, so two connectors
#: in two tenants can hold the same kind of credential without colliding.
ENV_TEMPLATE = "REGX_CONNECTOR_{public_id}_{suffix}"

_SUFFIX_BY_TYPE = {
    "bearer_token": "TOKEN",
    "api_key": "API_KEY",
    "basic_auth": "BASIC",
}


class SecretUnavailable(Exception):
    """The named credential is not present in this environment."""

    code = "CREDENTIAL_UNAVAILABLE"


def environment_variable_name(connector, credential_reference) -> str:
    """The variable this reference reads, derived or explicit.

    Deterministic and safe to display: an operator setting up a connector needs
    to be told exactly what to export, and the *name* of a secret is not a
    secret. Only the value is.
    """
    explicit = (credential_reference.reference_name or "").strip()
    if explicit:
        return explicit
    suffix = _SUFFIX_BY_TYPE.get(credential_reference.credential_type, "SECRET")
    return ENV_TEMPLATE.format(
        public_id=str(connector.public_id).replace("-", "_").upper(), suffix=suffix
    )


def resolve_connector_secret(connector, credential_reference) -> str:
    """The secret value, or raise. Never returns a default.

    The caller is `transport`, which puts the value straight into a header and
    holds no other reference to it. Nothing else in the codebase calls this, and
    nothing should: every additional call site is another place a secret can end
    up in a log line.
    """
    if credential_reference is None:
        raise SecretUnavailable("This connector has no credential reference.")

    name = environment_variable_name(connector, credential_reference)
    value = os.environ.get(name)
    if value is None or value == "":
        # The variable name, never a value, and never a hint about what a
        # correct value would look like.
        raise SecretUnavailable(f"The environment does not provide '{name}'.")
    return value


def auth_headers(connector, credential_reference) -> dict:
    """The authentication header for this credential type.

    The credential adapter owns the auth header, which is why `Authorization`
    is not a configurable static header: a tenant that could set it could set it
    to a value the tenant chose, and this is the only code allowed to decide
    what goes there.
    """
    value = resolve_connector_secret(connector, credential_reference)
    credential_type = credential_reference.credential_type

    if credential_type == "bearer_token":
        return {"Authorization": f"Bearer {value}"}
    if credential_type == "api_key":
        return {"X-API-Key": value}
    if credential_type == "basic_auth":
        # The environment supplies the already-encoded `user:pass` pair. Splitting
        # a combined value here would mean parsing a secret, and a parser that
        # touches a secret is a parser that can put one in a traceback.
        return {"Authorization": f"Basic {value}"}

    raise SecretUnavailable("That credential type cannot be resolved.")
