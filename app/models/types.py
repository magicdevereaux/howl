"""Column types shared across the models.

``UtcDateTime`` exists to close GAPS #22. Every timestamp in this app is
``DateTime(timezone=True)`` with a Python-side default, and under SQLite -- which
is the *entire* test suite -- such a column reads back **naive**. So any code
comparing a stored timestamp against ``datetime.now(UTC)`` had to remember to
write::

    dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

That normalisation was scattered across six call sites and *missing* from four
others. Fixing them one at a time was never going to hold: the next nullable
timestamp added to a model starts the cycle over, and the failure mode is a
``TypeError: can't subtract offset-naive and offset-aware datetimes`` that only
appears once real data flows through the branch. A ``TypeDecorator`` on the
column moves the guarantee to the one place that cannot be forgotten -- if the
column is ``UtcDateTime``, the value is aware, full stop.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator[datetime]):
    """A ``DateTime(timezone=True)`` that always hands Python a UTC-aware value.

    Identical DDL
        ``impl`` is ``DateTime(timezone=True)`` and nothing here touches
        ``load_dialect_impl``, so the emitted DDL is byte-for-byte what the
        existing migrations created (``TIMESTAMP WITH TIME ZONE`` on
        PostgreSQL, ``DATETIME`` on SQLite). This type therefore needs **no
        Alembic migration** -- it is a Python-side coercion only. Alembic's
        ``compare_type`` resolves a ``TypeDecorator`` through to its ``impl``,
        so autogenerate stays empty against a clean head (see GAPS #21).

    Inbound naive means "assume UTC", not "programmer error"
        The stricter policy is tempting: a naive datetime is genuinely ambiguous
        and raising would catch the bug at the write rather than letting a
        wrong instant into the database. It is rejected here for two reasons.

        First, this codebase already has naive values legitimately in flight.
        ``scripts/seed_demo_users.py`` builds its timestamps from
        ``datetime.now(UTC)`` (aware), but Alembic backfills, raw-SQL inserts in
        tests, and SQLite's own round-tripping all produce naive values, and a
        read path that raises is strictly worse than one that normalises -- a
        row already stored cannot be un-stored by refusing to load it.

        Second, and decisively: the app's convention is that naive *always*
        means UTC. Every writer uses ``datetime.now(UTC)``, and the existing
        ``replace(tzinfo=utc)`` normalisation this type replaces made exactly
        that assumption. Encoding the convention is honest; raising would
        pretend the ambiguity is real when the codebase has already resolved it.

        The one thing assume-UTC must not do is silently *convert* an aware
        value, so an aware non-UTC input is converted to UTC (preserving the
        instant) rather than having its offset stripped.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    # Both hooks are annotated `-> Any` rather than `-> datetime | None` because
    # of the non-datetime pass-through below: narrowing the return type would be
    # a lie about a branch that deliberately forwards whatever it was handed.
    # `Any` is also what TypeDecorator itself declares.

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        """On the way in: naive is assumed UTC; aware is converted to UTC."""
        if value is None:
            return None
        if not isinstance(value, datetime):
            # Not our job to validate — forward it and let SQLAlchemy or the
            # driver raise the error it would have raised anyway, which names
            # the offending type far more clearly than anything we could.
            return value
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        """On the way out: the whole point -- never hand back a naive value.

        SQLite returns naive datetimes for a ``timezone=True`` column, and even
        PostgreSQL returns naive if a column was ever written as
        ``timestamp without time zone``. Both are normalised here.
        """
        if value is None:
            return None
        if not isinstance(value, datetime):
            return value
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
