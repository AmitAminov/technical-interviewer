"""WebSocket endpoint ``/ws/interview/{session_id}`` (DESIGN.md §4).

JSON in / JSON out. The orchestrator (sync, DB-bound, possibly LLM-blocking
up to the provider timeout) runs in a thread-pool executor so the event loop
stays responsive. Each incoming message gets its own DB session; exceptions
are caught per-message and surfaced as ``{"type":"error"}`` without killing
the connection. When the orchestrator flags ``report_pending``, report
generation runs as a background task and ``{"type":"report_ready"}`` is sent
when it finishes.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..core.orchestrator import InterviewOrchestrator
from ..database import SessionLocal
from ..models import InterviewSession

logger = logging.getLogger(__name__)

router = APIRouter()


async def _generate_report_and_notify(websocket: WebSocket, session_id: str) -> None:
    loop = asyncio.get_event_loop()
    try:
        from ..core.report_generator import generate_and_store

        await loop.run_in_executor(None, generate_and_store, session_id)
        await websocket.send_json({"type": "report_ready", "session_id": session_id})
    except Exception:  # noqa: BLE001
        logger.exception("Background report generation failed for %s", session_id)
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "Report generation failed; you can retry via "
                    "POST /api/sessions/{0}/report/regenerate".format(session_id),
                }
            )
        except Exception:  # noqa: BLE001 - socket may already be gone
            pass


@router.websocket("/ws/interview/{session_id}")
async def interview_ws(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()

    db = SessionLocal()
    try:
        exists = db.get(InterviewSession, session_id) is not None
    finally:
        db.close()
    if not exists:
        await websocket.send_json({"type": "error", "message": "session not found"})
        await websocket.close(code=4404)
        return

    orch = InterviewOrchestrator(session_id)
    loop = asyncio.get_event_loop()
    report_task = None

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError("message must be a JSON object")
            except (ValueError, TypeError):
                await websocket.send_json(
                    {"type": "error", "message": "invalid JSON message"}
                )
                continue

            db = SessionLocal()
            try:
                messages = await loop.run_in_executor(None, orch.handle, db, data)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Orchestrator error for session %s handling %r",
                    session_id,
                    data.get("type"),
                )
                messages = [
                    {
                        "type": "error",
                        "message": "internal error handling '{0}'".format(
                            data.get("type")
                        ),
                    }
                ]
            finally:
                db.close()

            for msg in messages:
                await websocket.send_json(msg)

            if orch.report_pending:
                orch.report_pending = False
                report_task = asyncio.ensure_future(
                    _generate_report_and_notify(websocket, session_id)
                )
    except WebSocketDisconnect:
        logger.info("WS disconnected for session %s", session_id)
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected WS failure for session %s", session_id)
    finally:
        # Let an in-flight report finish writing to the DB (client can still
        # poll GET /report), but stop waiting on the socket.
        if report_task is not None and not report_task.done():
            report_task.cancel()
        db = SessionLocal()
        try:
            orch.on_disconnect(db)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to persist state on disconnect")
        finally:
            db.close()
