# 下崽儿 · 万能视频下载站 —— 项目总结（open.md）

> 一句话：粘贴链接就能下全网视频。站在 [yt-dlp](https://github.com/yt-dlp/yt-dlp)（15 万+ Star）肩膀上，用 FastAPI 糊了个轻量、无数据库、手机也能用的下载站。
>
> 仅供个人学习与备份，请尊重版权、注意平台规则与封号风险，后果自负。

---

## 一、这项目到底干了啥

现在很多人想把视频存到本地，但平台经常不给下、或者下得别扭（不能批量、限清晰度、要装 App）。这个项目就是解决这个痛点：

- 一个网页，粘贴链接 → 解析出标题/封面/时长/清晰度 → 选清晰度 → 下载到本地。
- 支持上千个站点（YouTube / B站 / 抖音 / X / Instagram …），因为下载引擎直接用 yt-dlp。
- 手机浏览器也能用，不用装任何软件。
- 额外能力：仅音频转 MP3、批量下载、视频总结、字幕翻译。
- 用「兑换码 + 会员」做了付费分级，验证商业化闭环。

核心思路不是「自己造轮子」，而是**站在巨人的肩膀上**：下载这种高风险、高复杂度的活儿交给成熟开源项目，我们只做封装、产品化和体验。

---

## 二、技术栈与架构

| 层 | 选型 | 说明 |
| --- | --- | --- |
| 后端 | Python + FastAPI | 单进程同时托管前端静态页和 API，够轻 |
| 下载引擎 | yt-dlp + ffmpeg | yt-dlp 解析/下载，ffmpeg 合并音视频、抽 MP3 |
| 前端 | 原生 HTML + Tailwind(CDN) + 原生 JS | 新粗野风 UI，无构建步骤，改完刷新即见 |
| 存储 | 无数据库 | 兑换码用 JSON 平文件 + HMAC 签名令牌，够用就好 |
| AI | OpenAI 兼容接口 | 可对接 DeepSeek / 通义 / OpenAI，默认 DeepSeek |

### 目录结构

```
backend/
  app.py           FastAPI 入口与路由，托管前端
  downloader.py    yt-dlp 封装：解析/下载/进度/批量/音频/字幕
  douyin.py        抖音无水印下载（分享页游客态，无需登录/Cookie）
  ai_service.py    OpenAI 兼容：总结/翻译，未配置时友好降级
  membership.py    兑换码校验与会员令牌（HMAC 签名）
  config.py        读取 .env 与路径
  data/            codes.json / used_codes.json（自动生成，不入库）
frontend/
  index.html  css/app.css  js/app.js
downloads/         下载临时目录（按 TTL 自动清理）
```

### 请求流程（下载）

1. `POST /api/parse`：yt-dlp 解析，返回标题、封面、时长、可选清晰度列表。
2. `POST /api/download`：按清晰度创建后台任务，返回 `job_id`（会员分级在这里拦截）。
3. `GET /api/progress/{job_id}`：轮询进度、速度、ETA、状态。
4. `GET /api/file/{job_id}`：任务完成后流式下载文件。

---

## 三、接口清单

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| POST | `/api/parse` | 解析链接，返回可选清晰度 |
| POST | `/api/download` | 单个下载任务 |
| POST | `/api/batch` | 批量下载任务 |
| GET | `/api/progress/{job_id}` | 查询任务进度 |
| GET | `/api/file/{job_id}` | 下载已完成文件 |
| POST | `/api/redeem` | 兑换码激活会员 |
| GET | `/api/me` | 查询会员状态与 AI 是否可用 |
| POST | `/api/summarize` | 视频总结（会员 + 需字幕） |
| POST | `/api/translate` | 字幕翻译（会员 + 需字幕） |

---

## 四、踩过的坑与解法（重点）

### 1. 抖音「Unsupported URL」与「需要 Cookie」

- **现象**：抖音链接（如 `douyin.com/jingxuan?modal_id=xxx`）直接丢给 yt-dlp，先报 `Unsupported URL`，规整成 `/video/{id}` 后又报「Fresh cookies needed」。
- **根因**：yt-dlp 的抖音 Web 接口已失效——抖音要求 `a_bogus` 这种 JS 签名，yt-dlp 算不出来；从浏览器抽 Cookie 又遇到浏览器锁库/加密。
- **解法**：绕开 yt-dlp，自己写 `douyin.py`，抓**分享页游客态**（`iesdouyin.com/share/video/{id}/`）里的 `_ROUTER_DATA`，直接拿到**无水印**视频直链，用 httpx 流式下载。**全程无需登录、无需用户提供 Cookie。**
- 顺带做了 URL 规整（`normalize_url`），把各种抖音链接格式统一成能识别的形式。

### 2. 清晰度选择不直观

- 把分辨率映射成人话标签（`720P` / `1080P` / `2K 超清` / `4K 超清`）。
- 下载按钮动态显示当前选择，比如「开下！· 720P」或锁态「开会员下 4K 超清」，让付费点一眼可见。
- 抖音游客态通常只有一档画质，会尽量解析 `bit_rate` 里的多档，没有就回退到「无水印原画」。

### 3. 全站中文化

- 把界面里残留的英文、以及后端报错信息都改成口语化中文，报错还带上「该怎么办」的提示。

### 4. 环境从零搭建（Windows）

- 用 winget 装了 Python 3.12 和 ffmpeg，处理了 PATH 问题。
- git 初始化后误把 `server.log` 暂存了，靠 `*.log` 进 `.gitignore` 修掉。

---

## 五、会员与商业化

- 无数据库方案：首次启动在 `backend/data/codes.json` 生成示例兑换码（形如 `VIP-XXXXXX`），一次性，用过记进 `used_codes.json` 作废。
- 兑换后签发 HMAC 令牌存浏览器本地。
- **万能兑换码**：`.env` 的 `UNIVERSAL_CODES`（默认 `VIP-FOREVER`）可多人重复使用、永不作废，兑换即得完整会员（含 AI）。适合演示/发福利，正式上线请改成别人猜不到的值。
- 分级额度（可在 `.env` 调）：

| 能力 | 免费 | 会员 |
| --- | --- | --- |
| 最高画质 | 720p | 最高（含 2K/4K） |
| 批量数量 | 3 | 不限 |
| MP3 音频 | ✗ | ✓ |
| AI 总结/翻译 | ✗ | ✓ |

---

## 六、AI 配置

`.env` 里配 OpenAI 兼容接口即可（**真实 Key 只存本地 `.env`，已被 git 忽略，不入库**）：

```
AI_BASE_URL=https://api.deepseek.com/v1
AI_API_KEY=你的key
AI_MODEL=deepseek-chat
```

- 总结/翻译依赖视频**自带字幕**，无字幕的视频 AI 没东西可处理。
- 未配置 Key 时，AI 按钮友好提示，不影响下载主流程。

---

## 七、快速开始（Windows）

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

打开 http://127.0.0.1:8000 即用。

---

## 八、安全与合规

- **敏感信息不入库**：`.env`（含 API Key）、`downloads/`、日志、`codes.json` / `used_codes.json` 都在 `.gitignore` 里；仓库只保留 `.env.example` 模板。
- 提交前已全库扫描，确认无任何真实 Key 泄漏。
- 版权与封号风险：本项目定位学习与个人备份，请自行承担使用后果。

---

## 九、这个项目想传达的开发模式

不要什么都自己写。遇到高复杂度、高风险的核心能力（比如全网视频解析），先去 GitHub 找有几万 Star 的成熟项目，**封装它、产品化它**，把精力放在体验、商业化和差异化上。这就是这个项目最想让人 get 到的思路。
