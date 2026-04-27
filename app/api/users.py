from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models.match import Match
from app.models.message import Message
from app.models.swipe import Swipe
from app.models.user import AvatarStatus, User
from app.schemas.browse import BrowseUserOut
from app.schemas.swipe import DiscoverUserOut, LastMessageOut, MatchOut, MatchedProfileOut

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/browse", response_model=list[BrowseUserOut])
def browse_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[User]:
    """Return all users with a ready avatar, excluding the current user."""
    users = (
        db.query(User)
        .filter(
            User.id != current_user.id,
            User.avatar_status == AvatarStatus.ready,
        )
        .order_by(User.created_at.desc())
        .all()
    )
    return users


@router.get("/discover", response_model=list[DiscoverUserOut])
def discover_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[User]:
    """Return ready users the current user hasn't swiped on yet."""
    swiped = (
        db.query(Swipe.target_user_id)
        .filter(Swipe.user_id == current_user.id)
        .scalar_subquery()
    )
    users = (
        db.query(User)
        .filter(
            User.id != current_user.id,
            User.avatar_status == AvatarStatus.ready,
            User.id.notin_(swiped),
        )
        .order_by(User.created_at.desc())
        .all()
    )
    return users


@router.get("/matches", response_model=list[MatchOut])
def list_matches(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MatchOut]:
    """Return all matches with unread count and last message preview."""
    matches = (
        db.query(Match)
        .filter(
            or_(
                Match.user1_id == current_user.id,
                Match.user2_id == current_user.id,
            )
        )
        .order_by(Match.matched_at.desc())
        .all()
    )
    result = []
    for m in matches:
        other_id = m.user2_id if m.user1_id == current_user.id else m.user1_id
        other = db.query(User).filter(User.id == other_id).first()
        if not other:
            continue

        unread = (
            db.query(Message)
            .filter(
                Message.match_id == m.id,
                Message.sender_id != current_user.id,
                Message.read_at.is_(None),
            )
            .count()
        )

        last_msg = (
            db.query(Message)
            .filter(Message.match_id == m.id)
            .order_by(Message.created_at.desc())
            .first()
        )
        last_message_out = (
            LastMessageOut(
                sender_id=last_msg.sender_id,
                content=last_msg.content,
                created_at=last_msg.created_at,
            )
            if last_msg else None
        )

        result.append(
            MatchOut(
                id=m.id,
                matched_at=m.matched_at,
                other_user=MatchedProfileOut.model_validate(other),
                unread_count=unread,
                last_message=last_message_out,
            )
        )
    return result
