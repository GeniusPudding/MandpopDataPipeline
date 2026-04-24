"""Discover popular Mandarin pop songs from music charts and playlists.

Sources:
    - NetEase Cloud Music playlists (curated by era / genre / mood)
    - NetEase Cloud Music top charts

Usage:
    from crawlers.charts import discover_songs
    songs = discover_songs(era="2000s")

CLI:
    python -m crawlers.charts --era all
    python -m crawlers.charts --era 2010s
    python -m crawlers.charts --playlist 12345678
    python -m crawlers.charts --chart hot
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://music.163.com/",
}

# Search keywords per era — used to DYNAMICALLY find playlists (not hardcoded IDs).
ERA_SEARCH_KEYWORDS = {
    "2000s":   ["华语经典 2000", "2000年代 华语金曲"],
    "2010s":   ["华语经典 2010", "2010年代 华语金曲"],
    "2020s":   ["华语新歌 2020", "2020年代 华语"],
    "classic": ["华语经典金曲", "华语经典老歌 500", "80 90 华语经典"],
    "ktv":     ["KTV必点 华语", "KTV 华语金曲"],
    "love":    ["华语情歌 经典", "华语抒情"],
    "rock":    ["华语摇滚 经典", "华语独立"],
}


def _fetch_track_details(track_ids: list[int], batch_size: int = 200) -> list[dict]:
    """Fetch track details in batches from NetEase song detail API."""
    all_tracks = []
    for i in range(0, len(track_ids), batch_size):
        batch = track_ids[i:i + batch_size]
        c_param = json.dumps([{"id": tid} for tid in batch])
        try:
            resp = requests.post(
                "https://music.163.com/api/v3/song/detail",
                data={"c": c_param},
                headers=HEADERS, timeout=20,
            )
            if resp.status_code == 200:
                songs = resp.json().get("songs", [])
                all_tracks.extend(songs)
        except Exception:
            pass
        if i + batch_size < len(track_ids):
            time.sleep(0.5)
    return all_tracks


def fetch_playlist(playlist_id: int) -> list[dict]:
    """Fetch all songs from a NetEase playlist.

    Uses the v6 API which returns track IDs for large playlists, then
    fetches track details in batches.

    Returns list of {"title": "...", "artist": "...", "netease_id": ...}
    """
    # First try: get full detail (works for playlists < ~100 tracks).
    url = f"https://music.163.com/api/playlist/detail?id={playlist_id}&n=1000"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return []
        data = resp.json()
        tracks = data.get("result", {}).get("tracks", [])

        # If tracks are truncated, fetch by track IDs.
        if not tracks:
            track_ids = [t["id"] for t in data.get("result", {}).get("trackIds", [])]
            if track_ids:
                tracks = _fetch_track_details(track_ids)
        songs = []
        for t in tracks:
            title = t.get("name", "").strip()
            # Handle both old API ("artists") and v3 API ("ar") formats.
            raw_artists = t.get("artists") or t.get("ar") or []
            artists = [a.get("name", "") for a in raw_artists]
            artist = ", ".join(a for a in artists if a)
            if title:
                songs.append({
                    "title": title,
                    "artist": artist,
                    "netease_id": t.get("id"),
                })
        return songs
    except Exception as e:
        print(f"  Error fetching playlist {playlist_id}: {e}", file=sys.stderr)
        return []


def search_playlists(keyword: str, limit: int = 3) -> list[dict]:
    """Search NetEase for playlists matching a keyword.

    Returns list of {"id": ..., "name": ..., "trackCount": ...}
    sorted by track count (largest first).
    """
    try:
        resp = requests.post(
            "https://music.163.com/api/search/get",
            data={"s": keyword, "type": 1000, "limit": limit, "offset": 0},
            headers=HEADERS, timeout=15,
        )
        if resp.status_code != 200:
            return []
        playlists = resp.json().get("result", {}).get("playlists", [])
        return sorted(playlists, key=lambda p: p.get("trackCount", 0), reverse=True)
    except Exception as e:
        print(f"  Search error: {e}", file=sys.stderr)
        return []


def filter_mandarin(songs: list[dict]) -> list[dict]:
    """Rough filter: keep songs whose title contains CJK characters
    (removes English-only, Korean-only, Japanese-only tracks).
    """
    cjk_re = re.compile(r"[\u4e00-\u9fff]")
    return [s for s in songs if cjk_re.search(s["title"])]


def discover_songs(
    era: str | None = None,
    playlist_id: int | None = None,
    chart: str | None = None,
    mandarin_only: bool = True,
) -> list[dict]:
    """Discover songs from specified source(s).

    Args:
        era: "2000s", "2010s", "2020s", "classic", "ktv", or "all"
        playlist_id: specific NetEase playlist ID
        chart: "hot", "new", "original", "surge"
        mandarin_only: filter out non-CJK titles

    Returns deduplicated list of {"title", "artist", "netease_id"}.
    """
    all_songs = []

    if playlist_id:
        print(f"Fetching playlist {playlist_id}...")
        all_songs.extend(fetch_playlist(playlist_id))

    elif chart:
        # Search for chart-like playlists.
        print(f"Searching for chart playlists: {chart}...")
        results = search_playlists(f"华语 {chart} 排行榜")
        for p in results[:2]:
            print(f"  {p['name']} ({p.get('trackCount', 0)} tracks)...",
                  end=" ", flush=True)
            songs = fetch_playlist(p["id"])
            print(f"fetched {len(songs)}")
            all_songs.extend(songs)
            time.sleep(1)

    elif era:
        eras = list(ERA_SEARCH_KEYWORDS.keys()) if era == "all" else [era]
        for e in eras:
            keywords = ERA_SEARCH_KEYWORDS.get(e, [])
            if not keywords:
                print(f"  Unknown era: {e}. Available: {list(ERA_SEARCH_KEYWORDS.keys())}")
                continue
            for kw in keywords:
                print(f"  [{e}] Searching: \"{kw}\"...", flush=True)
                results = search_playlists(kw, limit=3)
                for p in results[:2]:  # Top 2 playlists per keyword.
                    pid = p["id"]
                    name = p["name"]
                    tc = p.get("trackCount", 0)
                    if tc < 10:
                        continue
                    print(f"    → {name} ({tc} tracks)...", end=" ", flush=True)
                    songs = fetch_playlist(pid)
                    print(f"fetched {len(songs)}")
                    all_songs.extend(songs)
                    time.sleep(1)

    # Deduplicate by title.
    seen = set()
    unique = []
    for s in all_songs:
        if s["title"] not in seen:
            seen.add(s["title"])
            unique.append(s)

    if mandarin_only:
        unique = filter_mandarin(unique)

    return unique


def main():
    parser = argparse.ArgumentParser(
        description="Discover popular Mandarin pop songs from music charts",
    )
    parser.add_argument("--era", help="Era: 2000s / 2010s / 2020s / classic / ktv / all")
    parser.add_argument("--playlist", type=int, help="NetEase playlist ID")
    parser.add_argument("--chart", help="Chart: hot / new / original / surge")
    parser.add_argument("--format", choices=["txt", "json", "jsonl"], default="txt",
                        help="Output format (default: txt)")
    parser.add_argument("--output", "-o", type=str, help="Output file (default: stdout)")
    args = parser.parse_args()

    if not any([args.era, args.playlist, args.chart]):
        parser.print_help()
        print("\nExamples:")
        print("  python -m crawlers.charts --era all")
        print("  python -m crawlers.charts --era 2000s --format txt -o songs_2000s.txt")
        print("  python -m crawlers.charts --chart hot --format jsonl")
        print('  python -m crawlers.charts --era all -o new_songs.txt && python pipeline.py add --from new_songs.txt')
        return

    songs = discover_songs(era=args.era, playlist_id=args.playlist, chart=args.chart)
    print(f"\nDiscovered {len(songs)} unique Mandarin songs", file=sys.stderr)

    # Format output.
    if args.format == "txt":
        lines = [s["title"] for s in songs]
        output = "\n".join(lines)
    elif args.format == "json":
        output = json.dumps(songs, ensure_ascii=False, indent=2)
    else:  # jsonl
        output = "\n".join(json.dumps(s, ensure_ascii=False) for s in songs)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output + "\n")
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
