"""集中读取环境变量与路径配置，全项目只在这里碰 .env。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

FRONTEND_DIR = BASE_DIR / "frontend"
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", BASE_DIR / "downloads"))
DATA_DIR = BASE_DIR / "backend" / "data"

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 下载文件保留时长（秒），超时后启动清理
FILE_TTL_SECONDS = int(os.getenv("FILE_TTL_SECONDS", "3600"))

# AI（OpenAI 兼容接口）
AI_BASE_URL = os.getenv("AI_BASE_URL", "").strip()
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini").strip()

# 会员令牌签名密钥
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-please-a-long-random-string")

# Cookie（抖音/B站等平台可能需要）：二选一
# COOKIES_FILE：Netscape 格式 cookies.txt 的绝对路径（浏览器插件可导出）
# COOKIES_FROM_BROWSER：从本机浏览器读取，如 firefox / chrome / edge / chromium
COOKIES_FILE = os.getenv("COOKIES_FILE", "").strip()
COOKIES_FROM_BROWSER = os.getenv("COOKIES_FROM_BROWSER", "").strip()

# 免费额度限制
FREE_MAX_HEIGHT = int(os.getenv("FREE_MAX_HEIGHT", "720"))
FREE_MAX_BATCH = int(os.getenv("FREE_MAX_BATCH", "3"))

# 会员有效期（天）
MEMBER_DAYS = int(os.getenv("MEMBER_DAYS", "365"))


def ai_enabled() -> bool:
    return bool(AI_API_KEY and AI_BASE_URL)
