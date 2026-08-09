"""Tests for /health and /health/live.

The suite runs against SQLite in-memory with no guaranteed Redis, and
``app.main`` builds its own Postgres engine from ``settings.database_url``
independently of the ``get_db`` override the ``client`` fixture installs — so
these tests can't just rely on the test database being reachable through
``app.main._check_database``. Instead they patch the check functions
themselves, which is the seam GAPS #54 asks for: real dependency behaviour is
exercised at the unit level below, and the endpoint's status-code/shape
contract is exercised through the patched seam.
"""

from app.main import _check_database, _check_redis, _r2_configured

# ---------------------------------------------------------------------------
# /health — endpoint contract, dependencies patched at the seam
# ---------------------------------------------------------------------------

def test_health_ok_when_both_dependencies_up(client, monkeypatch):
    monkeypatch.setattr("app.main._check_database", lambda: True)
    monkeypatch.setattr("app.main._check_redis", lambda: True)

    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["redis"] == "ok"


def test_health_503_when_database_down(client, monkeypatch):
    monkeypatch.setattr("app.main._check_database", lambda: False)
    monkeypatch.setattr("app.main._check_redis", lambda: True)

    res = client.get("/health")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "unhealthy"
    assert body["checks"]["database"] == "unreachable"
    assert body["checks"]["redis"] == "ok"


def test_health_503_when_redis_down(client, monkeypatch):
    monkeypatch.setattr("app.main._check_database", lambda: True)
    monkeypatch.setattr("app.main._check_redis", lambda: False)

    res = client.get("/health")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "unhealthy"
    assert body["checks"]["redis"] == "unreachable"


def test_health_503_when_both_down(client, monkeypatch):
    monkeypatch.setattr("app.main._check_database", lambda: False)
    monkeypatch.setattr("app.main._check_redis", lambda: False)

    res = client.get("/health")
    assert res.status_code == 503


def test_health_reports_r2_configured_state(client, monkeypatch):
    monkeypatch.setattr("app.main._check_database", lambda: True)
    monkeypatch.setattr("app.main._check_redis", lambda: True)
    monkeypatch.setattr("app.main._r2_configured", lambda: True)

    res = client.get("/health")
    assert res.json()["checks"]["r2"] == "configured"

    monkeypatch.setattr("app.main._r2_configured", lambda: False)
    res = client.get("/health")
    assert res.json()["checks"]["r2"] == "unconfigured"


# ---------------------------------------------------------------------------
# /health/live — always 200, never touches dependencies
# ---------------------------------------------------------------------------

def test_liveness_always_ok(client, monkeypatch):
    """Even with both dependencies down, /health/live stays 200."""
    monkeypatch.setattr("app.main._check_database", lambda: False)
    monkeypatch.setattr("app.main._check_redis", lambda: False)

    res = client.get("/health/live")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# _check_database / _check_redis — unit tests of the real probes
# ---------------------------------------------------------------------------

def test_check_database_true_when_probe_succeeds(monkeypatch):
    """Exercises the real ``_check_database`` body (not the patched seam used
    elsewhere in this file) against a fake engine, so it stays hermetic
    regardless of whether a real Postgres is reachable from this environment."""
    import app.main as main_module

    class _OkConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, *_a, **_kw):
            return None

    class _OkEngine:
        def connect(self):
            return _OkConn()

    monkeypatch.setattr(main_module, "engine", _OkEngine())
    assert _check_database() is True


def test_check_database_false_when_engine_raises(monkeypatch):
    import app.main as main_module

    class _ExplodingEngine:
        def connect(self):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(main_module, "engine", _ExplodingEngine())
    assert _check_database() is False


def test_check_database_false_on_timeout(monkeypatch):
    """A probe that hangs past the timeout is reported unreachable, not left
    to block the health check indefinitely."""
    import time

    import app.main as main_module

    class _SlowConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, *_a, **_kw):
            time.sleep(5)

    class _SlowEngine:
        def connect(self):
            return _SlowConn()

    monkeypatch.setattr(main_module, "engine", _SlowEngine())
    assert _check_database(timeout=0.05) is False


def test_check_redis_false_when_unreachable(monkeypatch):
    """Point at a port nothing is listening on; the connect timeout should
    make this fail fast and return False rather than raise."""
    from app.config import settings

    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1/0")
    assert _check_redis(timeout=0.2) is False


def test_r2_configured_reflects_settings(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "r2_endpoint_url", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setattr(settings, "r2_access_key_id", "key")
    monkeypatch.setattr(settings, "r2_secret_access_key", "secret")
    monkeypatch.setattr(settings, "r2_bucket_name", "bucket")
    assert _r2_configured() is True

    monkeypatch.setattr(settings, "r2_bucket_name", None)
    assert _r2_configured() is False
