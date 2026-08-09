import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# `manager` owns the live sockets; chat.py does not import this module, so the
# dependency runs one way only.
from app.api.chat import manager
from app.db import get_db
from app.dependencies import get_current_user
from app.models.block import Block
from app.models.match import Match
from app.models.swipe import Swipe
from app.models.user import User
from app.schemas.block import BlockedUserOut, BlockIn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/blocks", tags=["blocks"])


def _remove_relationship(blocker_id: int, other_id: int, db: Session) -> int | None:
    """Delete any match, messages (via cascade), and mutual swipes between two users.

    Returns the id of the match it removed, if there was one, so the caller can
    close the live WebSockets that were serving it once the delete commits.
    """
    u1, u2 = min(blocker_id, other_id), max(blocker_id, other_id)
    match = db.query(Match).filter(Match.user1_id == u1, Match.user2_id == u2).first()
    removed_match_id: int | None = None
    if match:
        removed_match_id = match.id  # read before the delete detaches it
        db.delete(match)  # messages cascade

    # Remove swipes in both directions so neither user reappears in discover
    db.query(Swipe).filter(
        ((Swipe.user_id == blocker_id) & (Swipe.target_user_id == other_id)) |
        ((Swipe.user_id == other_id) & (Swipe.target_user_id == blocker_id))
    ).delete(synchronize_session=False)

    return removed_match_id


@router.post("", status_code=201)
def block_user(
    body: BlockIn,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Block a user. Removes any existing match and swipe records.

    Also closes any WebSocket still serving that match. Blocking used to
    broadcast nothing and close nothing, so the blocked user's client carried on
    showing the conversation, and the server believed access was revoked while
    the socket kept delivering the blocker's incoming messages (GAPS #60).
    """
    if body.blocked_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot block yourself.")

    target = db.query(User).filter(User.id == body.blocked_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")

    closed_match_id = _remove_relationship(current_user.id, body.blocked_id, db)

    try:
        db.add(Block(blocker_id=current_user.id, blocked_id=body.blocked_id))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="User is already blocked.")

    logger.info("blocks: user %d blocked user %d", current_user.id, body.blocked_id)
    # Only after the commit: the 409 path rolls the match delete back with it,
    # and closing sockets for a match that still exists would be a lie.
    if closed_match_id is not None:
        background_tasks.add_task(manager.close_match, closed_match_id, "blocked")
    return {"detail": "User blocked."}


@router.delete("/{blocked_id}", status_code=204)
def unblock_user(
    blocked_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Unblock a user. Restores their discoverability but not any prior conversation."""
    record = (
        db.query(Block)
        .filter(Block.blocker_id == current_user.id, Block.blocked_id == blocked_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Block not found.")

    db.delete(record)
    db.commit()
    logger.info("blocks: user %d unblocked user %d", current_user.id, blocked_id)


@router.get("", response_model=list[BlockedUserOut])
def list_blocks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[BlockedUserOut]:
    """List all users blocked by the current user in a single query.

    Replaces the previous N+1 loop (one ``db.get(User, ...)`` per block) with a
    hand-written join, the same approach as `list_matches` in
    `app/api/users.py`.  The join is inner, which reproduces the old
    ``if user:`` skip — and `blocks.blocked_id` is ``ON DELETE CASCADE``, so a
    block can never outlive its user anyway.  Only the five columns the response
    schema exposes are selected, so no `password_hash` or `email` is hydrated.
    """
    rows = (
        db.query(
            Block.blocked_id,
            Block.created_at,
            User.name,
            User.animal,
            User.avatar_url,
        )
        .join(User, User.id == Block.blocked_id)
        .filter(Block.blocker_id == current_user.id)
        .order_by(Block.created_at.desc())
        .all()
    )
    return [
        BlockedUserOut(
            id=r.blocked_id,
            name=r.name,
            animal=r.animal,
            avatar_url=r.avatar_url,
            blocked_at=r.created_at,
        )
        for r in rows
    ]
