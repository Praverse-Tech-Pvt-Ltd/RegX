"""Minimal .ics (iCalendar) builder for the demo-booking confirmation email.

No external dependency — just formats a VCALENDAR/VEVENT block per RFC 5545.
"""
from dataclasses import dataclass
from datetime import datetime


def _fold(line):
    # RFC 5545 §3.1: lines over 75 octets should be folded, but our lines
    # are short (names/emails/urls) so this is a no-op safety net.
    return line


def _escape(text):
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _fmt_dt(dt: datetime) -> str:
    # dt must be timezone-aware UTC.
    return dt.strftime("%Y%m%dT%H%M%SZ")


@dataclass
class IcsInput:
    uid: str
    start: datetime
    end: datetime
    summary: str
    description: str
    location: str
    organizer_email: str
    attendee_email: str
    attendee_name: str


def build_ics(data: IcsInput) -> str:
    now = _fmt_dt(datetime.utcnow().replace(tzinfo=data.start.tzinfo))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//iPharmaAI//Booking//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:REQUEST",
        "BEGIN:VEVENT",
        f"UID:{_escape(data.uid)}",
        f"DTSTAMP:{now}",
        f"DTSTART:{_fmt_dt(data.start)}",
        f"DTEND:{_fmt_dt(data.end)}",
        f"SUMMARY:{_escape(data.summary)}",
        f"DESCRIPTION:{_escape(data.description)}",
        f"LOCATION:{_escape(data.location)}",
        f"ORGANIZER;CN=iPharmaAI Team:mailto:{data.organizer_email}",
        f"ATTENDEE;CN={_escape(data.attendee_name)};RSVP=TRUE:mailto:{data.attendee_email}",
        "STATUS:CONFIRMED",
        "SEQUENCE:0",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"
