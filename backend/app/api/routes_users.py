"""User endpoints (DESIGN.md §3)."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.progress import build_progress
from ..database import get_db
from ..models import InterviewSession, User
from ..schemas import ProgressOut, SessionOut, UserCreate, UserOut
from .routes_sessions import session_to_out

router = APIRouter()


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        name=user.name,
        target_roles=list(user.target_roles or []),
        created_at=user.created_at,
    )


@router.post("/api/users", response_model=UserOut)
def create_user(payload: UserCreate, db: Session = Depends(get_db)) -> UserOut:
    user = User(name=payload.name.strip(), target_roles=list(payload.target_roles))
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.get("/api/users/{user_id}", response_model=UserOut)
def get_user(user_id: str, db: Session = Depends(get_db)) -> UserOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return _user_out(user)


@router.get("/api/users/{user_id}/sessions", response_model=List[SessionOut])
def list_user_sessions(user_id: str, db: Session = Depends(get_db)) -> List[SessionOut]:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    sessions = (
        db.query(InterviewSession)
        .filter(InterviewSession.user_id == user_id)
        .order_by(InterviewSession.created_at.desc())
        .all()
    )
    return [session_to_out(s) for s in sessions]


@router.get("/api/users/{user_id}/progress", response_model=ProgressOut)
def get_user_progress(user_id: str, db: Session = Depends(get_db)) -> ProgressOut:
    """Cross-session progress + personalized study curriculum (spec §16).

    Always 200 for a known user (empty history -> empty lists/dicts);
    404 only when the user does not exist.
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return build_progress(db, user_id)
