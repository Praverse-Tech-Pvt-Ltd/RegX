"""Microsoft Graph app-only email sending + Teams meeting creation.

Used by the demo-booking flow to send the rich HTML confirmation/notify
emails (with an inline logo and an .ics attachment) instead of the plain
SMTP send_mail() used for non-scheduled inquiries.

Requires three Azure AD app registration values and a licensed mailbox to
send as (application permissions: Mail.Send, OnlineMeetings.ReadWrite.All).
"""
import base64
import time

import requests
from decouple import config

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

_token_cache = {"value": None, "expires_at": 0}


class GraphNotConfigured(Exception):
    """Raised when the Azure AD app credentials are missing."""


def _get_credentials():
    tenant_id = config("AZURE_TENANT_ID", default="")
    client_id = config("AZURE_CLIENT_ID", default="")
    client_secret = config("AZURE_CLIENT_SECRET", default="")
    sender_upn = config("BOOKING_EMAIL_HOST_USER", default="")

    if not (tenant_id and client_id and client_secret and sender_upn):
        raise GraphNotConfigured(
            "AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET and "
            "BOOKING_EMAIL_HOST_USER must all be set to send booking emails "
            "via Microsoft Graph."
        )
    return tenant_id, client_id, client_secret, sender_upn


def _get_graph_token():
    if _token_cache["value"] and _token_cache["expires_at"] > time.time() + 30:
        return _token_cache["value"]

    tenant_id, client_id, client_secret, _ = _get_credentials()
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    resp = requests.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()
    _token_cache["value"] = payload["access_token"]
    _token_cache["expires_at"] = time.time() + int(payload.get("expires_in", 3600))
    return _token_cache["value"]


def send_graph_email(*, to_email, to_name, subject, html, ics_content=None, inline_images=None):
    """Send an HTML email via Graph's /sendMail, with an optional .ics
    attachment and optional inline (cid:) image attachments.

    inline_images: list of {'cid', 'name', 'content_type', 'content_bytes'}
    """
    _, _, _, sender_upn = _get_credentials()
    token = _get_graph_token()

    attachments = []
    if ics_content:
        attachments.append({
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "invite.ics",
            "contentType": "text/calendar",
            "contentBytes": base64.b64encode(ics_content.encode("utf-8")).decode("ascii"),
        })
    for img in (inline_images or []):
        attachments.append({
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": img["name"],
            "contentType": img["content_type"],
            "contentBytes": base64.b64encode(img["content_bytes"]).decode("ascii"),
            "isInline": True,
            "contentId": img["cid"],
        })

    message = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html},
            "toRecipients": [{"emailAddress": {"address": to_email, "name": to_name}}],
        },
        "saveToSentItems": "true",
    }
    if attachments:
        message["message"]["attachments"] = attachments

    resp = requests.post(
        f"{GRAPH_BASE}/users/{sender_upn}/sendMail",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=message,
        timeout=20,
    )
    resp.raise_for_status()


def create_meeting_url(subject, start_dt, end_dt):
    """Create a Teams online meeting via Graph and return its join URL.

    Falls back to a generic scheduling contact link if Graph isn't
    configured or the call fails — a booking should never hard-fail just
    because the meeting link couldn't be minted.
    """
    try:
        _, _, _, sender_upn = _get_credentials()
        token = _get_graph_token()
        resp = requests.post(
            f"{GRAPH_BASE}/users/{sender_upn}/onlineMeetings",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "startDateTime": start_dt.isoformat(),
                "endDateTime": end_dt.isoformat(),
                "subject": subject,
            },
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()["joinWebUrl"]
    except Exception:
        return "https://ipharmaai.com/ratools/requestdemo"
