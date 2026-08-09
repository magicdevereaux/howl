"""The single writer for a user's avatar status.

GAPS-ROUND-2 #41. ``avatar_status`` and ``avatar_status_updated_at`` are one
fact -- "what state is this avatar in, and since when" -- but they were two
independent assignments, and they had drifted: the timestamp had exactly two
writers, both at *enqueue* time (``app/api/avatar.py`` and
``app/api/profile.py``), while the task that actually moves the status wrote
``avatar_status`` on success and in ``_mark_failed`` and never touched the
timestamp at all.

That timestamp is not decoration. ADR-001 names it as the mechanism for "a
worker died after accepting a task but before completing it", and
``AvatarStatusOut`` exposes it purely so the clients can apply their two-minute
staleness rule -- ``frontend/src/App.jsx`` *stops polling* once it fires and
offers "Try Again" instead. A status whose timestamp is older than the status
itself therefore makes the client give up on a generation that has already
finished, or offer a retry the server will refuse. Since #40 the server also
reads it to decide whether a charged regeneration is refundable, so a stale
timestamp is now a spend decision as well as a UI one.

So the pair is written together, always, through here. Two writers that can
drift was the bug; removing the second writer is the fix.
"""

from datetime import UTC, datetime

from app.models.user import AvatarStatus, User


def set_avatar_status(user: User, status: AvatarStatus) -> None:
    """Move *user* to *status* and stamp when that happened.

    Does not commit -- the caller decides the transaction boundary. That
    matters in ``app/tasks/avatar.py``, where the ready transition has to land
    in the same statement batch as ``animal`` to satisfy
    ``ck_users_ready_avatar_has_animal``.
    """
    user.avatar_status = status
    user.avatar_status_updated_at = datetime.now(UTC)
