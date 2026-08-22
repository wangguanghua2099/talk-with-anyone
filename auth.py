"""可选访问口令。

config.json 中设置 access_token（非空）后：
- HTTP API 需要请求头 Authorization: Bearer <token>
- WebSocket 需要查询参数 ?token=<token>
- GET /api/info 豁免（用于 App 探测服务器与是否需口令）

access_token 为空（默认）时所有请求放行，行为与之前完全一致。
"""
import hmac

from state import load_config


def get_expected_token() -> str:
    return (load_config().get("access_token") or "").strip()


def token_matches(expected: str, provided: str) -> bool:
    if not expected:
        return True
    if not provided:
        return False
    return hmac.compare_digest(expected, provided)


def extract_bearer(authorization: str) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""
