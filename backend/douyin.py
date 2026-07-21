"""抖音下载：绕开 yt-dlp 已失效的 web 接口（需要 a_bogus 签名），
改用「分享页 _ROUTER_DATA」方案——游客态、无需登录、无需 Cookie。

原理：
1. 任意抖音链接 -> 解析出 aweme_id（支持 modal_id / /video/ / /note/ / v.douyin.com 短链）
2. 请求 https://www.iesdouyin.com/share/video/{id}/ ，解析页面内嵌 JSON
3. 取到 play_addr 的 playwm 链接，改写 playwm -> play 即为无水印直链
4. 直链是标准 mp4，跟随重定向即可流式下载
"""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse

import httpx

DOUYIN_HOSTS = ("douyin.com", "iesdouyin.com", "douyinvod.com")

UA_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1"
)
UA_PC = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

DOWNLOAD_HEADERS = {"User-Agent": UA_PC, "Referer": "https://www.douyin.com/"}


def is_douyin(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    return any(h in host for h in DOUYIN_HOSTS)


def _extract_id_from_url(url: str) -> str | None:
    qs = parse_qs(urlparse(url).query)
    if qs.get("modal_id", [None])[0] and qs["modal_id"][0].isdigit():
        return qs["modal_id"][0]
    m = re.search(r"/(?:video|note|share/video|share/note)/(\d+)", url)
    if m:
        return m.group(1)
    m = re.search(r"(\d{15,})", url)
    return m.group(1) if m else None


def resolve_aweme_id(url: str) -> str:
    """把任意抖音链接解析成 aweme_id，短链会跟随重定向。"""
    url = url.strip()
    aid = _extract_id_from_url(url)
    if aid:
        return aid
    # v.douyin.com 短链：跟随重定向拿到真实地址
    with httpx.Client(follow_redirects=True, timeout=20, headers={"User-Agent": UA_MOBILE}) as c:
        r = c.get(url)
        final = str(r.url)
        aid = _extract_id_from_url(final)
    if not aid:
        raise ValueError("没能从这个抖音链接里认出视频 ID")
    return aid


def _parse_router_data(html: str) -> dict:
    m = re.search(r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>", html, re.S)
    if not m:
        m = re.search(r"_ROUTER_DATA\s*=\s*(\{.*\})", html, re.S)
    if not m:
        raise ValueError("抖音分享页结构变了，没解析到数据")
    return json.loads(m.group(1))


def _pick_item(router: dict) -> dict:
    loader = router.get("loaderData", {})
    page = None
    for k, v in loader.items():
        if "page" in k and isinstance(v, dict):
            page = v
            break
    if not page:
        raise ValueError("抖音分享页没有视频数据")
    info = page.get("videoInfoRes") or {}
    items = info.get("item_list") or info.get("aweme_detail") or []
    if isinstance(items, dict):
        items = [items]
    if not items:
        raise ValueError("这条抖音可能已被删除或不可见")
    return items[0]


def _nowm(url: str) -> str:
    return url.replace("/playwm/", "/play/").replace("/playwm?", "/play?")


def _res_label(res: int) -> str:
    if res >= 2160:
        return "4K 超清"
    if res >= 1440:
        return "2K 超清"
    if res >= 1080:
        return "1080P 高清"
    if res >= 720:
        return "720P"
    if res > 0:
        return f"{res}P"
    return "标清"


def _human_size(num) -> str | None:
    if not num:
        return None
    num = float(num)
    for unit in ["B", "KB", "MB", "GB"]:
        if num < 1024:
            return f"{num:.1f}{unit}"
        num /= 1024
    return f"{num:.1f}TB"


def _build_qualities(video: dict, default_url: str):
    """从 bit_rate 里抽多档清晰度；抽不到就回退单档无水印。"""
    streams = {"nowm": default_url}
    quals = []
    seen = set()
    for i, b in enumerate(video.get("bit_rate") or []):
        pa = b.get("play_addr") or {}
        urls = pa.get("url_list") or []
        if not urls:
            continue
        h, w = pa.get("height"), pa.get("width")
        res = min(h, w) if h and w else (h or w or 0)
        if res in seen:
            continue
        seen.add(res)
        qid = f"dy_{res or i}"
        streams[qid] = _nowm(urls[0])
        quals.append(
            {
                "id": qid,
                "label": _res_label(res) + " 无水印",
                "_res": res,
                "height": None,  # 抖音各档一律免费，不加锁
                "size": _human_size(pa.get("data_size")),
            }
        )
    quals.sort(key=lambda q: q.get("_res") or 0, reverse=True)
    for q in quals:
        q.pop("_res", None)
    if not quals:
        quals = [{"id": "nowm", "label": "无水印 原画", "height": None, "size": None}]
    return quals, streams


def stream_download(direct_url: str, headers: dict, filepath: str, progress_cb=None) -> None:
    """流式下载直链到本地文件，progress_cb(downloaded, total) 上报进度。"""
    with httpx.Client(follow_redirects=True, timeout=60, headers=headers) as c:
        with c.stream("GET", direct_url) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            done = 0
            with open(filepath, "wb") as f:
                for chunk in r.iter_bytes(chunk_size=262144):
                    f.write(chunk)
                    done += len(chunk)
                    if progress_cb:
                        progress_cb(done, total)


def fetch_info(url: str) -> dict:
    """返回与 downloader.parse_info 兼容的字典，并附带下载所需的直链与请求头。"""
    aid = resolve_aweme_id(url)
    share = f"https://www.iesdouyin.com/share/video/{aid}/"
    with httpx.Client(follow_redirects=True, timeout=20, headers={"User-Agent": UA_MOBILE}) as c:
        html = c.get(share).text
    item = _pick_item(_parse_router_data(html))

    video = item.get("video", {})
    play_list = (video.get("play_addr") or {}).get("url_list") or []
    if not play_list:
        raise ValueError("没拿到抖音视频直链（可能是图集或直播）")
    direct = _nowm(play_list[0])
    qualities, streams = _build_qualities(video, direct)

    cover_list = (video.get("cover") or {}).get("url_list") or []
    author = (item.get("author") or {}).get("nickname")
    duration_ms = video.get("duration") or 0

    return {
        "title": (item.get("desc") or "抖音视频").strip()[:120] or "抖音视频",
        "thumbnail": cover_list[0] if cover_list else None,
        "duration": round(duration_ms / 1000) if duration_ms else None,
        "uploader": author,
        "extractor": "抖音",
        "webpage_url": f"https://www.douyin.com/video/{aid}",
        "qualities": qualities,
        "has_subtitles": False,
        "_direct_url": direct,
        "_streams": streams,
        "_headers": DOWNLOAD_HEADERS,
        "_aweme_id": aid,
    }
