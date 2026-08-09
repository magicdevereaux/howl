"""Tests for GET /api/users/discover pagination (GAPS #58).

Contract under test (see the docstring on `discover_users` in
app/api/users.py for the full rationale):
  - Query params: `limit` (int, default 30, min 1, max 50) and `cursor`
    (opaque string, omit for page 1).
  - Response body: unchanged bare JSON array of DiscoverUserOut, capped at
    `limit` items, shuffled within the page.
  - Pagination metadata rides in headers: `X-Has-More` ("true"/"false") and,
    when true, `X-Next-Cursor` to pass back as `cursor` for the next page.
"""

from app.models.user import AvatarStatus, User
from app.security import hash_password


def _make_user(db, *, email: str, **kwargs) -> User:
    kwargs.setdefault("animal", "wolf")
    user = User(
        email=email,
        password_hash=hash_password("testpass1"),
        avatar_status=AvatarStatus.ready,
        **kwargs,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_many(db, n: int, prefix: str) -> list[User]:
    return [_make_user(db, email=f"{prefix}{i}@howl.app") for i in range(n)]


# ---------------------------------------------------------------------------
# Backwards compatibility: bare array body, capped default page
# ---------------------------------------------------------------------------

def test_discover_response_body_is_still_a_bare_array(client, db, auth_headers):
    _make_many(db, 3, "bc")
    res = client.get("/api/users/discover", headers=auth_headers)
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_discover_default_page_is_capped(client, db, auth_headers):
    _make_many(db, 35, "cap")
    res = client.get("/api/users/discover", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()) == 30
    assert res.headers["X-Has-More"] == "true"
    assert "X-Next-Cursor" in res.headers


def test_discover_query_itself_is_bounded_by_a_sql_limit(client, db, auth_headers):
    """The point of #58: the *database* must never be asked for every eligible
    row. Truncating in Python after fetching everything would look identical
    to a client but still cost a full table scan on every call, at any table
    size -- so this checks the SQL itself, not just the response body."""
    from sqlalchemy import event

    _make_many(db, 40, "sqllimit")

    statements: list[str] = []

    def before_cursor_execute(conn, cursor, statement, params, context, executemany):
        if "FROM users" in statement and "SELECT" in statement.upper():
            statements.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        res = client.get("/api/users/discover?limit=10", headers=auth_headers)
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)

    assert res.status_code == 200
    assert len(res.json()) == 10
    discover_queries = [s for s in statements if "swiped" not in s.lower()]
    assert discover_queries, "expected at least one query against users"
    assert any("LIMIT" in s.upper() for s in discover_queries), (
        "discover's user query must carry a SQL LIMIT, not just a Python-side "
        "truncation of an unbounded result set:\n" + "\n---\n".join(discover_queries)
    )


def test_discover_under_a_page_has_no_more(client, db, auth_headers):
    _make_many(db, 3, "small")
    res = client.get("/api/users/discover", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()) == 3
    assert res.headers["X-Has-More"] == "false"
    assert "X-Next-Cursor" not in res.headers


def test_discover_old_client_advances_naturally_by_swiping(client, db, auth_headers, test_user):
    """An old client that never reads cursor/X-Next-Cursor still gets fresh
    profiles: each swipe removes that user from the underlying query, so
    calling with no params again surfaces the next batch."""
    _make_many(db, 3, "natural")

    first = client.get("/api/users/discover", headers=auth_headers).json()
    assert len(first) == 3

    client.post(
        "/api/swipes", headers=auth_headers,
        json={"target_user_id": first[0]["id"], "direction": "pass"},
    )

    second = client.get("/api/users/discover", headers=auth_headers).json()
    assert len(second) == 2
    assert first[0]["id"] not in [u["id"] for u in second]


# ---------------------------------------------------------------------------
# `limit` query param
# ---------------------------------------------------------------------------

def test_discover_respects_custom_limit(client, db, auth_headers):
    _make_many(db, 5, "lim")
    res = client.get("/api/users/discover?limit=2", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()) == 2
    assert res.headers["X-Has-More"] == "true"


def test_discover_limit_at_max_is_accepted(client, db, auth_headers):
    _make_many(db, 2, "maxlim")
    res = client.get("/api/users/discover?limit=50", headers=auth_headers)
    assert res.status_code == 200


def test_discover_limit_over_max_is_rejected(client, auth_headers):
    res = client.get("/api/users/discover?limit=51", headers=auth_headers)
    assert res.status_code == 422


def test_discover_limit_zero_is_rejected(client, auth_headers):
    res = client.get("/api/users/discover?limit=0", headers=auth_headers)
    assert res.status_code == 422


def test_discover_negative_limit_is_rejected(client, auth_headers):
    res = client.get("/api/users/discover?limit=-1", headers=auth_headers)
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# `cursor` query param
# ---------------------------------------------------------------------------

def test_discover_cursor_pages_through_without_overlap_or_gaps(client, db, auth_headers):
    users = _make_many(db, 7, "page")
    all_ids = {u.id for u in users}

    seen: list[int] = []
    cursor = None
    for _ in range(10):  # generous upper bound on iterations
        url = "/api/users/discover?limit=3"
        if cursor:
            url += f"&cursor={cursor}"
        res = client.get(url, headers=auth_headers)
        assert res.status_code == 200
        batch = res.json()
        seen.extend(u["id"] for u in batch)
        if res.headers["X-Has-More"] == "false":
            break
        cursor = res.headers["X-Next-Cursor"]
    else:
        raise AssertionError("did not terminate — pagination looped")

    assert len(seen) == len(set(seen)), "cursor pagination must not repeat a user"
    assert set(seen) == all_ids, "cursor pagination must not skip a user"


def test_discover_invalid_cursor_returns_400(client, auth_headers):
    res = client.get("/api/users/discover?cursor=not-valid-base64!!", headers=auth_headers)
    assert res.status_code == 400


def test_discover_cursor_from_one_user_is_generic_and_reusable(client, db, auth_headers):
    """The cursor only encodes a (created_at, id) boundary, not who asked for
    it -- confirms it's a plain pagination token, not a per-request secret."""
    _make_many(db, 4, "reuse")
    first = client.get("/api/users/discover?limit=2", headers=auth_headers)
    cursor = first.headers["X-Next-Cursor"]

    res = client.get(f"/api/users/discover?limit=2&cursor={cursor}", headers=auth_headers)
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# Randomisation within the page
# ---------------------------------------------------------------------------

def test_discover_page_is_shuffled(client, db, auth_headers, monkeypatch):
    """Confirms the shuffle step actually runs in the request path, without
    asserting a specific order (which would be flaky)."""
    import app.api.users as users_module

    calls = []
    original_shuffle = users_module.random.shuffle

    def spy_shuffle(seq):
        calls.append(list(seq))
        original_shuffle(seq)

    monkeypatch.setattr(users_module.random, "shuffle", spy_shuffle)

    _make_many(db, 4, "shuf")
    res = client.get("/api/users/discover", headers=auth_headers)
    assert res.status_code == 200
    assert len(calls) == 1
    assert len(calls[0]) == 4
