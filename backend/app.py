"""FastAPI 入口：托管前端静态页 + 提供下载/会员/AI 接口。"""
from __future__ import annotations

import os

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ai_service, config, downloader, membership

app = FastAPI(title="万能视频下载站")


def is_member(token: str | None) -> bool:
    return membership.verify_token(token)


# ---------- 数据模型 ----------
class ParseReq(BaseModel):
    url: str


class DownloadReq(BaseModel):
    url: str
    quality: str = "720"
    title: str | None = None


class BatchReq(BaseModel):
    urls: list[str]
    quality: str = "720"


class RedeemReq(BaseModel):
    code: str


class AIReq(BaseModel):
    url: str
    title: str | None = None
    target_lang: str | None = "中文"


# ---------- 下载相关 ----------
@app.post("/api/parse")
def api_parse(req: ParseReq):
    try:
        return downloader.parse_info(req.url.strip())
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        low = msg.lower()
        if "cookie" in low:
            raise HTTPException(
                400,
                "这个平台（如抖音/B站）需要 Cookie 才能解析。请在 .env 配置 "
                "COOKIES_FILE（浏览器导出的 cookies.txt）或 COOKIES_FROM_BROWSER=firefox 后重试。",
            )
        if "unsupported url" in low:
            raise HTTPException(400, "这个链接暂时不支持，换个视频页链接试试～")
        raise HTTPException(400, f"解析失败：{msg[:200]}")


def _guard_quality(quality: str, member: bool) -> str:
    """免费用户限制画质与音频提取。"""
    if member:
        return quality
    if quality == "audio":
        raise HTTPException(402, "提取 MP3 是会员功能，去兑换会员吧～")
    if quality == "best":
        return str(config.FREE_MAX_HEIGHT)
    try:
        if int(quality) > config.FREE_MAX_HEIGHT:
            raise HTTPException(
                402, f"免费最高 {config.FREE_MAX_HEIGHT}p，更高清请开会员"
            )
    except ValueError:
        pass
    return quality


@app.post("/api/download")
def api_download(req: DownloadReq, x_member: str | None = Header(default=None)):
    member = is_member(x_member)
    quality = _guard_quality(req.quality, member)
    job_id = downloader.create_job(req.url.strip(), quality, req.title)
    return {"job_id": job_id}


@app.post("/api/batch")
def api_batch(req: BatchReq, x_member: str | None = Header(default=None)):
    member = is_member(x_member)
    urls = [u.strip() for u in req.urls if u.strip()]
    if not urls:
        raise HTTPException(400, "没有有效链接")
    if not member and len(urls) > config.FREE_MAX_BATCH:
        raise HTTPException(
            402, f"免费一次最多 {config.FREE_MAX_BATCH} 个，批量无限请开会员"
        )
    quality = _guard_quality(req.quality, member)
    jobs = [
        {"url": u, "job_id": downloader.create_job(u, quality)} for u in urls
    ]
    return {"jobs": jobs}


@app.get("/api/progress/{job_id}")
def api_progress(job_id: str):
    job = downloader.get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在或已过期")
    return {
        "status": job["status"],
        "progress": job.get("progress", 0),
        "speed": job.get("speed"),
        "eta": job.get("eta"),
        "title": job.get("title"),
        "filename": job.get("filename"),
        "error": job.get("error"),
    }


@app.get("/api/file/{job_id}")
def api_file(job_id: str):
    job = downloader.get_job(job_id)
    if not job or job.get("status") != "done" or not job.get("filepath"):
        raise HTTPException(404, "文件还没准备好")
    path = job["filepath"]
    if not os.path.exists(path):
        raise HTTPException(410, "文件已被清理，请重新下载")
    return FileResponse(
        path, filename=job.get("filename"), media_type="application/octet-stream"
    )


# ---------- 会员 ----------
@app.post("/api/redeem")
def api_redeem(req: RedeemReq):
    ok, result = membership.redeem(req.code)
    if not ok:
        raise HTTPException(400, result)
    return {"token": result, "days": config.MEMBER_DAYS}


@app.get("/api/me")
def api_me(x_member: str | None = Header(default=None)):
    return {"member": is_member(x_member), "ai_enabled": config.ai_enabled()}


# ---------- AI ----------
@app.post("/api/summarize")
def api_summarize(req: AIReq, x_member: str | None = Header(default=None)):
    if not is_member(x_member):
        raise HTTPException(402, "AI 视频总结是会员功能")
    try:
        text = downloader.get_subtitle_text(req.url.strip())
        return {"summary": ai_service.summarize(text, req.title or "")}
    except ai_service.AINotConfigured as e:
        raise HTTPException(503, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)[:200])


@app.post("/api/translate")
def api_translate(req: AIReq, x_member: str | None = Header(default=None)):
    if not is_member(x_member):
        raise HTTPException(402, "字幕翻译是会员功能")
    try:
        text = downloader.get_subtitle_text(req.url.strip())
        translated = ai_service.translate_subtitles(text, req.target_lang or "中文")
        return {"translation": translated}
    except ai_service.AINotConfigured as e:
        raise HTTPException(503, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)[:200])


@app.on_event("startup")
def _startup():
    downloader.cleanup_expired()


# ---------- 托管前端（必须放最后，避免吃掉 /api 路由）----------
app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True), name="frontend")
