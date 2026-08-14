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
    """Create a bare Teams online meeting (no calendar event) and return its
    join URL. Kept as the last-resort fallback behind create_calendar_event —
    prefer that one, since it also blocks calendars and adds attendees.
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


def create_calendar_event(*, subject, start_dt, end_dt, attendee_email, attendee_name, internal_attendee_emails=None, body_html=""):
    """Create a real Outlook calendar event (with a Teams meeting attached)
    on the booking mailbox, inviting the customer and internal team as real
    attendees — this is what actually blocks everyone's calendar and shows
    up as busy time, not just a bare Teams link.

    Returns {'event_id': ..., 'join_url': ...} on success. Falls back to a
    bare online meeting (or a static link) if calendar creation fails —
    a booking should never hard-fail just because the invite couldn't send.
    """
    try:
        _, _, _, sender_upn = _get_credentials()
        token = _get_graph_token()

        attendees = [{
            "emailAddress": {"address": attendee_email, "name": attendee_name},
            "type": "required",
        }]
        for email in (internal_attendee_emails or []):
            attendees.append({"emailAddress": {"address": email}, "type": "required"})

        resp = requests.post(
            f"{GRAPH_BASE}/users/{sender_upn}/events",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "subject": subject,
                "body": {"contentType": "HTML", "content": body_html},
                "start": {"dateTime": start_dt.isoformat(), "timeZone": "UTC"},
                "end": {"dateTime": end_dt.isoformat(), "timeZone": "UTC"},
                "attendees": attendees,
                "isOnlineMeeting": True,
                "onlineMeetingProvider": "teamsForBusiness",
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        join_url = (data.get("onlineMeeting") or {}).get("joinUrl") or "https://ipharmaai.com/ratools/requestdemo"
        return {"event_id": data["id"], "join_url": join_url}
    except Exception:
        return {"event_id": None, "join_url": create_meeting_url(subject, start_dt, end_dt)}


def update_calendar_event(event_id, *, start_dt, end_dt):
    """Move an existing calendar event to a new time (reschedule). No-op if
    it was never created via Graph (event_id is None, e.g. Graph wasn't
    configured at booking time)."""
    if not event_id:
        return
    try:
        _, _, _, sender_upn = _get_credentials()
        token = _get_graph_token()
        requests.patch(
            f"{GRAPH_BASE}/users/{sender_upn}/events/{event_id}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "start": {"dateTime": start_dt.isoformat(), "timeZone": "UTC"},
                "end": {"dateTime": end_dt.isoformat(), "timeZone": "UTC"},
            },
            timeout=20,
        ).raise_for_status()
    except Exception:
        pass


def cancel_calendar_event(event_id):
    """Cancel an existing calendar event (notifies attendees), freeing
    everyone's calendar. No-op if it was never created via Graph."""
    if not event_id:
        return
    try:
        _, _, _, sender_upn = _get_credentials()
        token = _get_graph_token()
        requests.post(
            f"{GRAPH_BASE}/users/{sender_upn}/events/{event_id}/cancel",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"comment": "This demo has been cancelled."},
            timeout=20,
        ).raise_for_status()
    except Exception:
        pass


def get_busy_intervals(emails, day_start_utc, day_end_utc):
    """Ask Graph's getSchedule for each internal team member's real Outlook
    free/busy for the given UTC window, folded into slot availability
    alongside our own DemoRequest bookings.

    Returns a list of (start_utc, end_utc) datetime tuples for anything
    marked busy/tentative/oof. Returns [] (fail-open) if Graph isn't
    configured, no team emails are set, or the call fails — a calendar
    outage should never take down the whole booking page.
    """
    if not emails:
        return []
    try:
        _, _, _, sender_upn = _get_credentials()
        token = _get_graph_token()
        resp = requests.post(
            f"{GRAPH_BASE}/users/{sender_upn}/calendar/getSchedule",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "schedules": emails,
                "startTime": {"dateTime": day_start_utc.isoformat(), "timeZone": "UTC"},
                "endTime": {"dateTime": day_end_utc.isoformat(), "timeZone": "UTC"},
                "availabilityViewInterval": 15,
            },
            timeout=20,
        )
        resp.raise_for_status()
        intervals = []
        for schedule in resp.json().get("value", []):
            for item in schedule.get("scheduleItems", []):
                if item.get("status") in ("busy", "tentative", "oof"):
                    from datetime import datetime
                    start = datetime.fromisoformat(item["start"]["dateTime"].replace("Z", "+00:00"))
                    end = datetime.fromisoformat(item["end"]["dateTime"].replace("Z", "+00:00"))
                    intervals.append((start, end))
        return intervals
    except Exception:
        return []
