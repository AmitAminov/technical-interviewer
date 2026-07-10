"""Autosaving transcript store, encrypted at rest (DESIGN.md §5, §11).

Every interviewer/candidate/system line is persisted as a
:class:`~app.models.TranscriptEntry` with Fernet-encrypted text. The
orchestrator calls :func:`add_entry` on every WS message, so the transcript
survives crashes and reconnects. Partial (interim) speech results are upserted
into a single provisional entry per session as a safety net, then finalized
when the full answer arrives.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..models import TranscriptEntry
from ..schemas import TranscriptEntryOut, TranscriptOut
from ..security.crypto import decrypt_text, encrypt_text


def add_entry(
    db: Session, session_id: str, speaker: str, text: str, commit: bool = True
) -> TranscriptEntry:
    """Append a transcript entry (encrypted). Autosaves by default."""
    entry = TranscriptEntry(
        session_id=session_id,
        speaker=speaker,
        ts=datetime.utcnow(),
        text_enc=encrypt_text(text or "") or "",
    )
    db.add(entry)
    if commit:
        db.commit()
    return entry


def update_entry(
    db: Session, entry_id: str, text: str, commit: bool = True
) -> Optional[TranscriptEntry]:
    """Overwrite the text of an existing entry (used for partial → final)."""
    entry = db.get(TranscriptEntry, entry_id)
    if entry is None:
        return None
    entry.text_enc = encrypt_text(text or "") or ""
    entry.ts = datetime.utcnow()
    if commit:
        db.commit()
    return entry


def get_transcript(db: Session, session_id: str) -> TranscriptOut:
    """Return the decrypted transcript in chronological order."""
    rows = (
        db.query(TranscriptEntry)
        .filter(TranscriptEntry.session_id == session_id)
        .order_by(TranscriptEntry.ts, TranscriptEntry.id)
        .all()
    )
    entries = [
        TranscriptEntryOut(
            id=row.id,
            session_id=row.session_id,
            ts=row.ts,
            speaker=row.speaker,  # type: ignore[arg-type]
            text=decrypt_text(row.text_enc) or "",
        )
        for row in rows
    ]
    return TranscriptOut(session_id=session_id, entries=entries)


def delete_transcript(db: Session, session_id: str, commit: bool = True) -> int:
    """Delete every transcript entry for a session. Returns rows removed."""
    count = (
        db.query(TranscriptEntry)
        .filter(TranscriptEntry.session_id == session_id)
        .delete(synchronize_session=False)
    )
    if commit:
        db.commit()
    return count
