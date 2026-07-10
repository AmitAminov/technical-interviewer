"""Repair UTF-8-as-cp1252 mojibake in model/CLI text.

The Claude CLI emits UTF-8; on Windows a subprocess that decodes with the OS
locale (cp1252) turns "—"/"'"/'"' into sequences like "â€"". The provider now
pins UTF-8 (see llm/provider.py), but reports generated before that fix are
stored with the garble baked in — this repairs them on read, and guards new
output as defense in depth.
"""
from __future__ import annotations

# Mojibake only ever introduces these Latin-1/CP1252 lead bytes; skip the
# (expensive-ish) round-trip entirely when none are present.
_MARKERS = ("Ã", "â", "Â", "€", "Å", "Ê")


def fix_mojibake(text: str) -> str:
    """Undo a single UTF-8→CP1252 mis-decode when the whole string round-trips.

    Safe by construction: if any character is not CP1252-encodable (e.g. Hebrew
    or an already-correct em-dash) the re-encode raises and the original text is
    returned unchanged; likewise if the bytes are not valid UTF-8. Only strings
    that are cleanly, wholly double-encoded are transformed.
    """
    if not text or not any(m in text for m in _MARKERS):
        return text
    try:
        repaired = text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    # A replacement char means the guess was wrong — keep the original.
    if "�" in repaired:
        return text
    return repaired
