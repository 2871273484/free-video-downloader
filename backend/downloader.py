"""yt-dlp 封装：解析、下载、进度、批量、仅音频 MP3、字幕抓取。

任务状态保存在内存字典 JOBS 中，前端通过 /api/progress 轮询。
下载在后台线程池里跑，避免阻塞事件循环。
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

import yt_dlp

from . import config, douyin

JOBS: dict[str, dict] = {}
_executor = ThreadPoolExecutor(max_workers=4)
_lock = threading.Lock()

# 免费用户可选的画质上限之外的高度会被过滤
COMMON_HEIGHTS = [2160, 1440, 1080, 720, 480, 360, 240]

# 判断是否装了 ffmpeg，用于合并/转码
FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None


def normalize_url(url: str) -> str:
    """把部分平台的"网页态"链接改写成 yt-dlp 认识的形式。

    典型：抖音 https://www.douyin.com/jingxuan?modal_id=123 -> /video/123
    """
    url = (url or "").strip()
    try:
        p = urlparse(url)
    except Exception:
        return url
    host = (p.netloc or "").lower()

    # 抖音：modal_id 携带真实视频 id
    if "douyin.com" in host:
        qs = parse_qs(p.query)
        mid = qs.get("modal_id", [None])[0]
        if mid and mid.isdigit():
            return f"https://www.douyin.com/video/{mid}"
    return url


def _cookie_opts() -> dict:
    """根据配置注入 Cookie（文件优先于浏览器）。"""
    opts: dict = {}
    if config.COOKIES_FILE and os.path.exists(config.COOKIES_FILE):
        opts["cookiefile"] = config.COOKIES_FILE
    elif config.COOKIES_FROM_BROWSER:
        opts["cookiesfrombrowser"] = (config.COOKIES_FROM_BROWSER,)
    return opts


def _quality_label(h: int) -> str:
    """把高度映射成用户直观的清晰度名称。"""
    if h >= 4320:
        return "8K 超清"
    if h >= 2160:
        return "4K 超清"
    if h >= 1440:
        return "2K 超清"
    if h >= 1080:
        return "1080P 高清"
    return f"{h}P"


def _human_size(num: int | None) -> str | None:
    if not num:
        return None
    for unit in ["B", "KB", "MB", "GB"]:
        if num < 1024:
            return f"{num:.1f}{unit}"
        num /= 1024
    return f"{num:.1f}TB"


def parse_info(url: str) -> dict:
    """解析视频信息，返回标题/封面/时长/可选画质等，不下载。"""
    url = normalize_url(url)
    # 抖音走专用无水印方案（yt-dlp 的抖音接口已失效）
    if douyin.is_douyin(url):
        info = douyin.fetch_info(url)
        return {k: v for k, v in info.items() if not k.startswith("_")}

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        **_cookie_opts(),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if info.get("_type") == "playlist" and info.get("entries"):
        info = next((e for e in info["entries"] if e), info)

    formats = info.get("formats") or []
    heights = sorted(
        {
            f.get("height")
            for f in formats
            if f.get("height") and f.get("vcodec") != "none"
        },
        reverse=True,
    )
    # 归拢到常见档位
    available = [h for h in COMMON_HEIGHTS if h in heights]
    if not available and heights:
        available = heights[:5]

    quality_options = []
    for h in available:
        # 找该高度大致体积
        cand = [
            f.get("filesize") or f.get("filesize_approx")
            for f in formats
            if f.get("height") == h and (f.get("filesize") or f.get("filesize_approx"))
        ]
        quality_options.append(
            {
                "id": str(h),
                "label": _quality_label(h),
                "height": h,
                "size": _human_size(max(cand)) if cand else None,
            }
        )

    has_subs = bool(info.get("subtitles") or info.get("automatic_captions"))

    return {
        "title": info.get("title") or "未命名视频",
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader") or info.get("channel") or info.get("extractor_key"),
        "extractor": info.get("extractor_key"),
        "webpage_url": info.get("webpage_url") or url,
        "qualities": quality_options,
        "has_subtitles": has_subs,
    }


def _safe_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    return name.strip()[:120] or "video"


def _build_opts(job_id: str, quality: str, outtmpl: str) -> dict:
    def hook(d):
        with _lock:
            job = JOBS.get(job_id)
            if not job:
                return
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                done = d.get("downloaded_bytes") or 0
                job["status"] = "downloading"
                job["progress"] = round(done / total * 100, 1) if total else 0
                job["speed"] = _human_size(d.get("speed")) + "/s" if d.get("speed") else None
                job["eta"] = d.get("eta")
            elif d["status"] == "finished":
                job["status"] = "processing"
                job["progress"] = 99.0

    opts: dict = {
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "progress_hooks": [hook],
        "restrictfilenames": False,
        **_cookie_opts(),
    }

    if quality == "audio":
        opts["format"] = "bestaudio/best"
        if FFMPEG_AVAILABLE:
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]
    elif quality == "best":
        opts["format"] = "bv*+ba/b" if FFMPEG_AVAILABLE else "b"
        opts["merge_output_format"] = "mp4"
    else:
        h = int(quality)
        if FFMPEG_AVAILABLE:
            opts["format"] = f"bv*[height<={h}]+ba/b[height<={h}]/b"
            opts["merge_output_format"] = "mp4"
        else:
            opts["format"] = f"b[height<={h}]/b"
    return opts


def _run_douyin_download(job_id: str, url: str, quality: str) -> None:
    job = JOBS[job_id]
    try:
        job["status"] = "downloading"
        out_dir = config.DOWNLOAD_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        info = douyin.fetch_info(url)
        title = _safe_name(info.get("title") or "douyin")
        job["title"] = info.get("title") or job.get("title")
        mp4_path = str(out_dir / f"{title}.mp4")

        streams = info.get("_streams") or {}
        direct = streams.get(quality) or info["_direct_url"]

        def cb(done, total):
            with _lock:
                job["progress"] = round(done / total * 100, 1) if total else 0
                job["status"] = "downloading"

        douyin.stream_download(direct, info["_headers"], mp4_path, cb)

        filepath = mp4_path
        if quality == "audio" and FFMPEG_AVAILABLE:
            with _lock:
                job["status"] = "processing"
                job["progress"] = 99.0
            mp3_path = str(out_dir / f"{title}.mp3")
            import subprocess

            subprocess.run(
                ["ffmpeg", "-y", "-i", mp4_path, "-vn", "-b:a", "192k", mp3_path],
                capture_output=True,
            )
            if os.path.exists(mp3_path):
                filepath = mp3_path

        with _lock:
            job["status"] = "done"
            job["progress"] = 100.0
            job["filepath"] = filepath
            job["filename"] = os.path.basename(filepath)
            job["finished_at"] = time.time()
    except Exception as e:  # noqa: BLE001
        with _lock:
            job["status"] = "error"
            job["error"] = str(e)[:300]


def _run_download(job_id: str, url: str, quality: str) -> None:
    if douyin.is_douyin(url):
        return _run_douyin_download(job_id, url, quality)
    job = JOBS[job_id]
    try:
        job["status"] = "downloading"
        out_dir = config.DOWNLOAD_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        outtmpl = str(out_dir / "%(title)s.%(ext)s")
        opts = _build_opts(job_id, quality, outtmpl)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)

        # 找到实际产出的文件（音频转码后扩展名会变）
        files = [f for f in glob.glob(str(out_dir / "*")) if os.path.isfile(f)]
        files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
        if not files:
            raise RuntimeError("下载完成但未找到文件")
        filepath = files[0]

        with _lock:
            job["status"] = "done"
            job["progress"] = 100.0
            job["filepath"] = filepath
            job["filename"] = os.path.basename(filepath)
            job["title"] = info.get("title") or job.get("title")
            job["finished_at"] = time.time()
    except Exception as e:  # noqa: BLE001
        with _lock:
            job["status"] = "error"
            job["error"] = str(e)[:300]


def create_job(url: str, quality: str, title: str | None = None) -> str:
    url = normalize_url(url)
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {
        "id": job_id,
        "url": url,
        "quality": quality,
        "status": "queued",
        "progress": 0.0,
        "title": title,
        "created_at": time.time(),
    }
    _executor.submit(_run_download, job_id, url, quality)
    return job_id


def get_job(job_id: str) -> dict | None:
    return JOBS.get(job_id)


def get_subtitle_text(url: str, langs: list[str] | None = None) -> str:
    """抓取字幕/自动字幕并转为纯文本，供 AI 总结/翻译。"""
    url = normalize_url(url)
    langs = langs or ["zh-Hans", "zh", "zh-CN", "en"]
    tmp = config.DOWNLOAD_DIR / ("sub_" + uuid.uuid4().hex[:8])
    tmp.mkdir(parents=True, exist_ok=True)
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": langs,
        "subtitlesformat": "vtt",
        "noplaylist": True,
        "outtmpl": str(tmp / "%(title)s.%(ext)s"),
        **_cookie_opts(),
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)
        vtts = glob.glob(str(tmp / "*.vtt"))
        if not vtts:
            return ""
        text = _vtt_to_text(open(vtts[0], encoding="utf-8", errors="ignore").read())
        return text
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _vtt_to_text(vtt: str) -> str:
    lines = []
    seen = set()
    for line in vtt.splitlines():
        line = line.strip()
        if not line or "-->" in line or line.upper().startswith("WEBVTT"):
            continue
        if line.isdigit():
            continue
        clean = re.sub(r"<[^>]+>", "", line)
        clean = re.sub(r"\[[^\]]*\]", "", clean).strip()
        if clean and clean not in seen:
            seen.add(clean)
            lines.append(clean)
    return "\n".join(lines)


def cleanup_expired() -> None:
    """删除超过 TTL 的下载文件与任务记录。"""
    now = time.time()
    for job_id in list(JOBS.keys()):
        job = JOBS[job_id]
        finished = job.get("finished_at") or job.get("created_at", now)
        if now - finished > config.FILE_TTL_SECONDS:
            shutil.rmtree(config.DOWNLOAD_DIR / job_id, ignore_errors=True)
            JOBS.pop(job_id, None)
