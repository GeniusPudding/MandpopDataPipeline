"""Lyrics crawlers — multiple sources with fallback chain.

Priority:
    1. NetEase Cloud Music API (free, has LRC timestamps, best for Mandarin)
    2. YouTube auto-generated subtitles (has timestamps)
    3. (Future: KKBOX, Mojim, WhisperX)

Usage:
    from crawlers.lyrics import fetch_lyrics
    lrc, txt, source = fetch_lyrics("告白氣球")
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def fetch_lyrics(title: str) -> tuple[str | None, str | None, str | None]:
    """Try all sources to get lyrics for a song.

    Returns (lrc_text, plain_text, source_name).
    lrc_text has [mm:ss.xx] timestamps; plain_text is clean text.
    Either may be None. source_name identifies which source succeeded.
    """
    # 1. NetEase Cloud Music (best for Mandarin pop).
    lrc, txt = _fetch_netease(title)
    if lrc and len(lrc) > 30:
        return lrc, txt, "netease"

    # 2. YouTube auto-subs (fallback).
    # Would need youtube_url — skip for now in standalone mode.

    return None, None, None


def _fetch_netease(title: str) -> tuple[str | None, str | None]:
    """Fetch lyrics from NetEase Cloud Music API."""
    import requests

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://music.163.com/",
    }

    try:
        # Search.
        resp = requests.post(
            "https://music.163.com/api/search/get",
            data={"s": title, "type": 1, "limit": 5, "offset": 0},
            headers=headers,
            timeout=15,
        )
        if resp.status_code != 200:
            return None, None
        songs = resp.json().get("result", {}).get("songs", [])
        if not songs:
            return None, None

        song_id = songs[0]["id"]

        # Get lyrics.
        resp2 = requests.get(
            f"https://music.163.com/api/song/lyric?id={song_id}&lv=1&tv=1",
            headers=headers,
            timeout=15,
        )
        if resp2.status_code != 200:
            return None, None
        data = resp2.json()
        lrc = data.get("lrc", {}).get("lyric")

        # Strip timestamps for plain text version.
        plain = None
        if lrc:
            lines = [re.sub(r"\[[\d:.]+\]", "", l).strip()
                     for l in lrc.splitlines()]
            plain = "\n".join(l for l in lines if l)

        return lrc, plain
    except Exception as e:
        print(f"  NetEase error: {e}")
        return None, None


def fetch_lyrics_youtube_subs(youtube_url: str) -> str | None:
    """Try to get auto-generated Chinese subtitles from YouTube."""
    if not youtube_url:
        return None
    try:
        # Download auto-subs.
        result = subprocess.run(
            ["yt-dlp", "--write-auto-subs", "--sub-lang", "zh",
             "--skip-download", "--sub-format", "vtt",
             "-o", "%(id)s", youtube_url],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=30,
        )
        # Find .vtt files.
        for vtt in Path(".").glob("*.zh*.vtt"):
            text = vtt.read_text(encoding="utf-8", errors="replace")
            vtt.unlink()
            return _vtt_to_lrc(text)
        return None
    except Exception:
        return None


def _vtt_to_lrc(vtt_text: str) -> str:
    """Convert VTT to LRC format."""
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
    # Deduplicate.
    deduped = []
    for ln in lines:
        text_part = ln.split("]", 1)[-1] if "]" in ln else ln
        if not deduped or text_part != deduped[-1].split("]", 1)[-1]:
            deduped.append(ln)
    return "\n".join(deduped)
