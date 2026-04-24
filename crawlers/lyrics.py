"""Lyrics crawlers — multiple sources with fallback chain.

Priority:
    1. NetEase Cloud Music API (free, has LRC timestamps, best for Mandarin)
    2. QQ Music API (free, has LRC, covers Jay Chou + NetEase gaps)
    3. YouTube auto-generated subtitles (has timestamps, last resort)

Usage:
    from crawlers.lyrics import fetch_lyrics
    lrc, txt, source = fetch_lyrics("告白氣球")
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


def fetch_lyrics(title: str, youtube_url: str | None = None,
                 ) -> tuple[str | None, str | None, str | None]:
    """Try all sources to get lyrics for a song.

    Returns (lrc_text, plain_text, source_name).
    lrc_text has [mm:ss.xx] timestamps; plain_text is clean text.
    Either may be None. source_name identifies which source succeeded.
    """
    # 1. NetEase Cloud Music.
    lrc, txt = _fetch_netease(title)
    if lrc and len(lrc) > 30:
        return lrc, txt, "netease"

    # 2. QQ Music (especially for Jay Chou).
    lrc, txt = _fetch_qq_music(title)
    if lrc and len(lrc) > 30:
        return lrc, txt, "qq_music"

    # 3. YouTube auto-subs.
    if youtube_url:
        yt_lrc = fetch_lyrics_youtube_subs(youtube_url)
        if yt_lrc and len(yt_lrc) > 30:
            txt = "\n".join(
                re.sub(r"\[[\d:.]+\]", "", l).strip()
                for l in yt_lrc.splitlines() if l.strip()
            )
            return yt_lrc, txt, "youtube_subs"

    return None, None, None


def _lrc_to_plain(lrc: str) -> str:
    """Strip [mm:ss.xx] timestamps from LRC to get plain text."""
    lines = [re.sub(r"\[[\d:.]+\]", "", l).strip() for l in lrc.splitlines()]
    return "\n".join(l for l in lines if l)


# ─────────────────────────────────────────────
# Source 1: NetEase Cloud Music
# ─────────────────────────────────────────────

def _fetch_netease(title: str) -> tuple[str | None, str | None]:
    import requests

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://music.163.com/",
    }

    try:
        resp = requests.post(
            "https://music.163.com/api/search/get",
            data={"s": title, "type": 1, "limit": 5, "offset": 0},
            headers=headers, timeout=15,
        )
        if resp.status_code != 200:
            return None, None
        songs = resp.json().get("result", {}).get("songs", [])
        if not songs:
            return None, None

        song_id = songs[0]["id"]

        resp2 = requests.get(
            f"https://music.163.com/api/song/lyric?id={song_id}&lv=1&tv=1",
            headers=headers, timeout=15,
        )
        if resp2.status_code != 200:
            return None, None
        lrc = resp2.json().get("lrc", {}).get("lyric")
        return (lrc, _lrc_to_plain(lrc)) if lrc else (None, None)
    except Exception as e:
        print(f"  NetEase error: {e}")
        return None, None


# ─────────────────────────────────────────────
# Source 2: QQ Music
# ─────────────────────────────────────────────

def _fetch_qq_music(title: str) -> tuple[str | None, str | None]:
    import requests

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://y.qq.com/",
    }

    try:
        # Search.
        search_data = json.dumps({
            "search": {
                "method": "DoSearchForQQMusicDesktop",
                "module": "music.search.SearchCgiService",
                "param": {
                    "search_type": 0,
                    "query": title,
                    "page_num": 1,
                    "num_per_page": 5,
                },
            }
        })
        resp = requests.get(
            "https://u.y.qq.com/cgi-bin/musicu.fcg",
            params={"data": search_data},
            headers=headers, timeout=15,
        )
        if resp.status_code != 200:
            return None, None
        songs = (resp.json()
                 .get("search", {})
                 .get("data", {})
                 .get("body", {})
                 .get("song", {})
                 .get("list", []))
        if not songs:
            return None, None

        songmid = songs[0].get("mid", "")
        if not songmid:
            return None, None

        # Get lyrics.
        resp2 = requests.get(
            "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg",
            params={"songmid": songmid, "format": "json", "nobase64": 1},
            headers=headers, timeout=15,
        )
        if resp2.status_code != 200:
            return None, None
        lrc = resp2.json().get("lyric", "")
        if not lrc:
            return None, None
        return lrc, _lrc_to_plain(lrc)
    except Exception as e:
        print(f"  QQ Music error: {e}")
        return None, None


# ─────────────────────────────────────────────
# Source 3: YouTube auto-subs
# ─────────────────────────────────────────────

def fetch_lyrics_youtube_subs(youtube_url: str) -> str | None:
    if not youtube_url:
        return None
    try:
        result = subprocess.run(
            ["yt-dlp", "--write-auto-subs", "--sub-lang", "zh",
             "--skip-download", "--sub-format", "vtt",
             "-o", "%(id)s", youtube_url],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=30,
        )
        for vtt in Path(".").glob("*.zh*.vtt"):
            text = vtt.read_text(encoding="utf-8", errors="replace")
            vtt.unlink()
            return _vtt_to_lrc(text)
        return None
    except Exception:
        return None


def _vtt_to_lrc(vtt_text: str) -> str:
    lines = []
    time_re = re.compile(r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})")
    current_time = ""
    for line in vtt_text.splitlines():
        m = time_re.match(line)
        if m:
            h, mi, s, ms = int(m[1]), int(m[2]), int(m[3]), int(m[4])
            total_min = h * 60 + mi
            current_time = f"[{total_min:02d}:{s:02d}.{ms // 10:02d}]"
        elif line.strip() and current_time and not line.startswith(("WEBVTT", "Kind:")):
            clean = re.sub(r"<[^>]+>", "", line).strip()
            if clean:
                lines.append(f"{current_time}{clean}")
                current_time = ""
    deduped = []
    for ln in lines:
        text_part = ln.split("]", 1)[-1] if "]" in ln else ln
        if not deduped or text_part != deduped[-1].split("]", 1)[-1]:
            deduped.append(ln)
    return "\n".join(deduped)
