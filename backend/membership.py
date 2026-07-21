"""兑换码激活会员：无数据库，纯 JSON 平文件 + HMAC 签名令牌。

- codes.json：有效兑换码清单（首次运行自动生成几个示例码）
- used_codes.json：已使用的兑换码 -> 使用时间
令牌形如 "payload_b64.signature"，payload 含到期时间戳，服务端校验签名与有效期。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

from . import config

CODES_FILE = config.DATA_DIR / "codes.json"
USED_FILE = config.DATA_DIR / "used_codes.json"


def _load(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _ensure_seed_codes() -> None:
    """首次运行生成一批示例兑换码，方便演示。"""
    if CODES_FILE.exists():
        return
    codes = ["VIP-" + secrets.token_hex(3).upper() for _ in range(5)]
    _save(CODES_FILE, codes)


_ensure_seed_codes()


def _sign(payload_b64: str) -> str:
    sig = hmac.new(
        config.SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")


def issue_token(days: int | None = None) -> str:
    days = days or config.MEMBER_DAYS
    exp = int(time.time()) + days * 86400
    payload = json.dumps({"exp": exp}, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"{payload_b64}.{_sign(payload_b64)}"


def verify_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    payload_b64, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(payload_b64)):
        return False
    try:
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded).decode())
        return int(data.get("exp", 0)) > int(time.time())
    except Exception:
        return False


def redeem(code: str) -> tuple[bool, str]:
    """校验兑换码，成功返回 (True, token)，失败返回 (False, 原因)。"""
    code = (code or "").strip().upper()
    if not code:
        return False, "请输入兑换码"
    # 万能码：多人可重复使用、永不作废，不记录 used
    if code in config.UNIVERSAL_CODES:
        return True, issue_token()
    codes = _load(CODES_FILE, [])
    used = _load(USED_FILE, {})
    if code not in codes:
        return False, "兑换码无效"
    if code in used:
        return False, "兑换码已被使用"
    used[code] = int(time.time())
    _save(USED_FILE, used)
    return True, issue_token()
