# 下崽儿 · 万能视频下载站

粘贴链接就能下全网视频。基于 [yt-dlp](https://github.com/yt-dlp/yt-dlp)（15 万+ Star）+ FastAPI 打造，轻量、无数据库、手机也能用。

> 仅供个人学习与备份，请尊重版权、注意平台规则与封号风险，后果自负。

## 功能

- 粘贴链接解析：标题、封面、时长、可选清晰度（支持上千站点：YouTube / B站 / 抖音 / X / Instagram …）
- 抖音专用无水印下载：**无需登录、无需用户提供 Cookie**（走分享页游客态方案，绕过 yt-dlp 已失效的抖音接口）
- 下载：按清晰度下载，自动用 ffmpeg 合并音视频；支持批量、下载进度、手机保存
- 仅音频：一键提取 MP3
- 会员：兑换码激活，解锁高清、批量不限、MP3、AI
- AI（可选）：视频总结、字幕翻译（OpenAI 兼容接口）

## 技术栈

- 后端：Python + FastAPI（单进程同时托管前端与 API）
- 下载引擎：yt-dlp + ffmpeg
- 前端：原生 HTML + Tailwind(CDN) + 原生 JS（新粗野风 UI）
- 存储：无数据库，兑换码用 JSON 平文件 + HMAC 签名令牌

## 目录结构

```
backend/
  app.py           FastAPI 入口与路由，托管前端
  downloader.py    yt-dlp 封装：解析/下载/进度/批量/音频/字幕
  douyin.py        抖音无水印下载（分享页游客态，无需登录/Cookie）
  ai_service.py    OpenAI 兼容：总结/翻译
  membership.py    兑换码校验与会员令牌
  config.py        读取 .env 与路径
  data/            codes.json / used_codes.json（自动生成）
frontend/
  index.html  css/app.css  js/app.js
downloads/         下载临时目录（自动清理）
```

## 快速开始（Windows）

前置：已安装 Python 3.12 与 ffmpeg（本项目已装好）。

```powershell
# 1. 建虚拟环境并装依赖
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# 2. 配置（可选，AI 才需要）
Copy-Item .env.example .env
# 编辑 .env 填 AI_BASE_URL / AI_API_KEY / AI_MODEL

# 3. 启动
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000 即可使用。

## 会员兑换码

> 抖音无需任何 Cookie 配置即可下载（`backend/douyin.py` 走分享页游客态方案）。
> `.env` 里的 `COOKIES_FILE` / `COOKIES_FROM_BROWSER` 仅用于其它需要登录态的平台（如 B站高清、会员内容）。

## 会员兑换码

首次启动会在 `backend/data/codes.json` 自动生成 5 个示例码（形如 `VIP-XXXXXX`），这类码**一次性**，用过即记入 `used_codes.json` 作废。
在网页右上角「兑换码」输入即可激活会员，令牌存在浏览器本地。

**万能兑换码 `VIP-FOREVER`**：可多人重复使用、永不作废，兑换即得完整会员（2K/4K、无限批量、MP3、AI 总结/翻译）。
可在 `.env` 用 `UNIVERSAL_CODES` 配置（逗号分隔多个）。正式上线请务必改成别人猜不到的值。

## AI 配置说明

`.env` 里的 AI 兼容 OpenAI 接口，可对接 DeepSeek / 通义 / OpenAI 等：

```
AI_BASE_URL=https://api.deepseek.com/v1
AI_API_KEY=你的key
AI_MODEL=deepseek-chat
```

未配置时，AI 相关按钮会友好提示，不影响下载主流程。

## 免费 / 会员额度（可在 .env 调整）

| 能力 | 免费 | 会员 |
| --- | --- | --- |
| 最高画质 | 720p | 最高（含 4K） |
| 批量数量 | 3 | 不限 |
| MP3 音频 | ✗ | ✓ |
| AI 总结/翻译 | ✗ | ✓ |
