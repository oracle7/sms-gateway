import re
from typing import Optional


def normalize_contact_phone(raw: Optional[str], default_country: str = "1") -> str:
    """
    Canonicalizes phone numbers, shortcodes, and special sender identifiers.

    Rules:
    - Empty / 'unknown' -> 'unknown'
    - Alphanumeric sender IDs (contains letters, < 3 digits) -> preserved trimmed
    - 3-6 digit US shortcodes (including legacy '+22660') -> pure digits ('22660')
    - 10-digit US NANP -> '+1XXXXXXXXXX'
    - 11-digit starting with '1' -> '+1XXXXXXXXXX'
    - '011' US international prefix -> '+<country+number>'
    - >= 7 digits -> '+<digits>'
    """
    if raw is None:
        return "unknown"

    text = str(raw).strip()
    if not text or text.lower() == "unknown":
        return "unknown"

    digits = re.sub(r"\D", "", text)
    has_letters = bool(re.search(r"[A-Za-z]", text))
    if has_letters and len(digits) < 3:
        return text

    if not digits:
        return "unknown"

    # US shortcodes (e.g. pharmacies / 2FA codes: 22660, 72833)
    if 3 <= len(digits) <= 6:
        return digits

    if not text.startswith("+") and digits.startswith("011") and len(digits) >= 10:
        return f"+{digits[3:]}"

    if len(digits) == 10:
        return f"+{default_country}{digits}"

    if len(digits) == 11 and digits.startswith(default_country):
        return f"+{digits}"

    if len(digits) >= 7:
        return f"+{digits}"

    return text


def format_phone_display(phone: Optional[str]) -> str:
    """Formats canonical US E.164 numbers for easy reading by clinic staff."""
    if not phone or phone == "unknown":
        return "Unknown Sender"
    if len(phone) == 12 and phone.startswith("+1") and phone[2:].isdigit():
        area = phone[2:5]
        mid = phone[5:8]
        last = phone[8:12]
        return f"({area}) {mid}-{last}"
    return phone
