import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import auth
import main

client = TestClient(main.app)


@pytest.fixture()
def _token(monkeypatch):
    """设置 auth.get_expected_token 的返回值，默认无口令。"""
    def _set(value):
        monkeypatch.setattr(auth, "get_expected_token", lambda: value)
        return value
    yield _set
    monkeypatch.setattr(auth, "get_expected_token", lambda: "")


def test_no_token_allows_all(_token):
    _token("")
    with TestClient(main.app) as c:
        r = c.get("/api/info")
        assert r.status_code == 200
        r = c.get("/api/config")
        assert r.status_code == 200


def test_info_exempt_and_reports_auth_required(_token):
    _token("secret123")
    with TestClient(main.app) as c:
        r = c.get("/api/info")
        assert r.status_code == 200
        assert r.json()["name"] == "Talk With Anyone"
        assert r.json()["auth_required"] is True


def test_api_requires_token_when_set(_token):
    _token("secret123")
    with TestClient(main.app) as c:
        r = c.get("/api/config")
        assert r.status_code == 401
        r = c.get("/api/config", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401
        r = c.get("/api/config", headers={"Authorization": "Bearer secret123"})
        assert r.status_code == 200


def test_ws_requires_token_when_set(_token):
    _token("secret123")
    with TestClient(main.app) as c:
        closed = False
        with c.websocket_connect("/ws/tts-stream") as ws:
            try:
                msg = ws.receive()
                closed = msg.get("type") == "websocket.close" and msg.get("code") == 1008
            except WebSocketDisconnect as e:
                closed = e.code == 1008
        assert closed
        with c.websocket_connect("/ws/tts-stream?token=secret123") as ws:
            pass


def test_ws_allowed_without_token_when_disabled(_token):
    _token("")
    with TestClient(main.app) as c:
        with c.websocket_connect("/ws/tts-stream") as ws:
            pass
