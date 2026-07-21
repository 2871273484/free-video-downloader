"""OpenAI 兼容的 AI 能力：视频总结、字幕翻译。

未配置 Key 时抛出 AINotConfigured，路由层转成友好提示，不影响下载主流程。
"""
from __future__ import annotations

from . import config


class AINotConfigured(Exception):
    pass


def _client():
    if not config.ai_enabled():
        raise AINotConfigured("尚未配置 AI，请在 .env 填写 AI_BASE_URL / AI_API_KEY")
    from openai import OpenAI

    return OpenAI(base_url=config.AI_BASE_URL, api_key=config.AI_API_KEY)


def _chat(system: str, user: str, max_tokens: int = 1200) -> str:
    client = _client()
    resp = client.chat.completions.create(
        model=config.AI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.4,
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


def summarize(text: str, title: str = "") -> str:
    if not text.strip():
        raise ValueError("这个视频没抓到字幕，没法总结")
    text = text[:12000]
    system = (
        "你是视频内容助理。用简体中文输出结构化总结：一句话概述、"
        "3-6 个关键要点（带序号）、以及一句适合发朋友圈的金句。语言口语、简洁。"
    )
    user = f"视频标题：{title}\n\n字幕内容：\n{text}"
    return _chat(system, user)


def translate_subtitles(text: str, target_lang: str = "中文") -> str:
    if not text.strip():
        raise ValueError("没有可翻译的字幕内容")
    text = text[:12000]
    system = (
        f"你是字幕翻译。把下面字幕逐句翻译成{target_lang}，"
        "保持一行一句，不要加解释、不要合并句子。"
    )
    return _chat(system, text, max_tokens=2000)
