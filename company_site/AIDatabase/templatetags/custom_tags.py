from datetime import datetime
import re

from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    if isinstance(dictionary, dict):
        return dictionary.get(key, "")
    return ""


@register.filter
def card_initials(value):
    words = [part[:1].upper() for part in str(value or "").split() if part]
    initials = "".join(words[:2])
    return initials or "NA"


@register.filter
def eudra_status_class(value):
    normalized = str(value or "").strip().upper()
    if normalized == "GMPDA":
        return "deficiency"
    if normalized == "GMPNC":
        return "noncompliant"
    if normalized == "GMPC":
        return "compliant"
    return "neutral"


@register.filter
def eudra_status_badge(value):
    mapping = {
        "GMPDA": "GMPDA - Deficiency",
        "GMPNC": "GMPNC - Non-compliant",
        "GMPC": "GMPC - Compliant",
    }
    normalized = str(value or "").strip().upper()
    return mapping.get(normalized, value or "NA")


@register.filter
def eudra_document_label(value):
    mapping = {
        "GMPDA": "GMPDA - Deficiency action taken",
        "GMPNC": "GMPNC - Non-compliance report",
        "GMPC": "GMPC - Good Manufacturing Practice Certificate",
    }
    normalized = str(value or "").strip().upper()
    return mapping.get(normalized, value or "NA")


@register.filter
def pretty_card_date(value):
    text = str(value or "").strip()
    if not text or text == "NA":
        return "NA"
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%d %b %Y")
        except ValueError:
            continue
    return text


def _smart_case_text(value):
    text = str(value or "").strip()
    if not text or text == "NA":
        return "NA"

    def normalize_word(match):
        word = match.group(0)
        if any(char.isdigit() for char in word):
            return word.upper()
        if len(word) <= 2 and word.isupper():
            return word.upper()
        return word.capitalize()

    return re.sub(r"[A-Za-z0-9']+", normalize_word, text)


@register.filter
def smart_case(value):
    return _smart_case_text(value)


@register.filter
def mhra_status_class(value):
    normalized = str(value or "").strip().upper()
    if normalized == "GMPC":
        return "compliant"
    if "NON" in normalized:
        return "noncompliant"
    return "neutral"


@register.filter
def mhra_status_badge(value):
    normalized = str(value or "").strip().upper()
    if normalized == "GMPC":
        return "GMPC - Compliant"
    if "NON" in normalized:
        return "GMPC - Non-compliant"
    return value or "NA"


@register.filter
def mhra_document_label(value):
    normalized = str(value or "").strip().upper()
    if normalized == "GMPC":
        return "GMPC - Good Manufacturing Practice Certificate"
    if "NON" in normalized:
        return "GMPC - Non-compliance report"
    return value or "NA"
