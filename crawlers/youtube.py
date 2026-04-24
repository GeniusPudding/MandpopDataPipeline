"""YouTube audio/video download via yt-dlp."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def search_song(title: str, max_results: int = 10) -> list[dict]:
    """Search YouTube for a song, return candidate videos sorted by view count.

    Filters out covers, piano versions, karaoke, Shorts, and long mixes.
    """
    cmd = [
        "yt-dlp", f"ytsearch{max_results}:{title} 官方 MV",
        "--dump-json", "--flat-playlist", "--no-warnings", "--skip-download",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        return []

    videos = []
    noise = ["cover", "翻唱", "piano", "鋼琴", "伴奏", "karaoke", "ktv", "instrumental"]
    for line in result.stdout.strip().splitlines():
        try:
            v = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = (v.get("title") or "").lower()
        dur = v.get("duration") or 0
        if any(n in t for n in noise):
            continue
        if dur < 60 or dur > 600:
            continue
        videos.append(v)

    videos.sort(key=lambda v: v.get("view_count") or 0, reverse=True)
    return videos


def download_audio(url: str, output_path: Path) -> Path:
    """Download best audio from a YouTube URL as mp3."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "yt-dlp", "-f", "bestaudio",
        "-x", "--audio-format", "mp3", "--audio-quality", "0",
        "-o", str(output_path),
        "--no-playlist",
        url,
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"Download failed: {result.stderr[:300]}")

    # yt-dlp may append extension
    for candidate in [output_path, output_path.with_suffix(".mp3")]:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Downloaded file not found at {output_path}")


def get_video_info(url: str) -> dict | None:
    """Fetch video metadata without downloading."""
    result = subprocess.run(
        ["yt-dlp", "--dump-json", "--no-download", url],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
