"""
normalize.py
------------
Field-level cleaning helpers shared by the merge pipeline and the audio app.
Kept deliberately small and pure so each rule is easy to defend line-by-line.

Every function returns a *normalized-for-matching* value AND we always keep the
original raw value elsewhere, so cleaning never destroys the source of truth.
"""

import re

# Common email-domain typos we are willing to auto-correct. This is a
# judgment call: correcting typos improves matching but could in theory merge
# two different addresses. We only fix well-known, unambiguous ones.
DOMAIN_TYPOS = {
    "gmial.com": "gmail.com",
    "gmai.com": "gmail.com",
    "gnail.com": "gmail.com",
    "hotmial.com": "hotmail.com",
    "outlok.com": "outlook.com",
}

# Titles / honorifics stripped from names before matching.
TITLES = {"dr", "dr.", "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "prof", "prof."}


def clean_text(value):
    """Trim whitespace (incl. tabs/newlines) and collapse internal runs."""
    if value is None:
        return ""
    # Strip Excel's text-guard leading apostrophe and stray control chars.
    value = value.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    value = value.strip().lstrip("'").strip()
    return re.sub(r"\s+", " ", value)


def normalize_email(raw):
    """Lowercase, trim, and fix well-known domain typos. Returns '' if empty."""
    e = clean_text(raw).lower()
    if not e or "@" not in e:
        return ""
    local, _, domain = e.partition("@")
    domain = DOMAIN_TYPOS.get(domain, domain)
    return f"{local}@{domain}"


def normalize_phone(raw):
    """
    Reduce any Indian phone format to its 10-digit subscriber number.

    Handles: +91, 91, leading 0, spaces, dashes, parentheses, an Excel
    text-guard apostrophe, and trailing 'ext 5' noise. Returns '' when we
    cannot recover a clean 10-digit number (too short / junk) so that broken
    numbers never create false matches.
    """
    if not raw:
        return ""
    digits = re.sub(r"\D", "", str(raw))
    # Drop country code / trunk prefixes.
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    elif len(digits) > 10:
        # e.g. number with an extension appended -> keep the leading 10.
        digits = digits[:10]
    return digits if len(digits) == 10 else ""


def phone_is_valid(raw):
    return normalize_phone(raw) != ""


def normalize_name(raw):
    """
    Return a canonical, order-independent name key.

    Handles 'Last, First', honorific prefixes, casing, backtick/curly
    apostrophes, and first/last swaps (by sorting the tokens). We return both a
    display-friendly cleaned name and a set of comparison tokens.
    """
    n = clean_text(raw)
    if not n:
        return "", set()

    # "Verma, Rohan" -> "Rohan Verma"
    if "," in n:
        last, _, first = n.partition(",")
        n = f"{first.strip()} {last.strip()}".strip()

    # Unify apostrophe variants so D'Souza == D`Souza.
    n = n.replace("`", "'").replace("’", "'")

    tokens = [t for t in re.split(r"[ ]+", n) if t]
    tokens = [t for t in tokens if t.lower().strip(".") not in {x.strip(".") for x in TITLES}]

    display = " ".join(w.capitalize() for w in tokens)
    # Order-independent token set (lowercased, apostrophes/dots removed) so a
    # swapped first/last name still matches.
    compare = {re.sub(r"[.']", "", t.lower()) for t in tokens if t}
    return display, compare


def name_tokens_overlap(tokens_a, tokens_b):
    """True if two name-token sets share at least one meaningful token."""
    return bool(tokens_a & tokens_b)
