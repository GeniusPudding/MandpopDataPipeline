"""
MandpopDataPipeline — Mandarin pop song dataset builder.

Add songs:
    python pipeline.py add "告白氣球"                           # One song
    python pipeline.py add "告白氣球" "小幸運" "演員"            # Multiple songs
    python pipeline.py add --from songs.txt                     # From text file (one per line)
    python pipeline.py add --from songs.json                    # From JSON
    python pipeline.py add --from repertoire.json               # StreetPerformerMaster format
    python pipeline.py add "告白氣球" --url "https://..."       # With explicit YouTube URL
    python pipeline.py add --from songs.txt --lyrics-only       # Only crawl lyrics, skip download

Manage:
    python pipeline.py status                                   # Dataset stats
    python pipeline.py list                                     # List all songs + status
    python pipeline.py list --missing-lyrics                    # Songs without lyrics
    python pipeline.py lyrics                                   # Crawl lyrics for all songs
    python pipeline.py export --request req.json --output ./out # Export subset

Environment:
    DATASET_PATH=D:\\MandpopDataset   (in .env or environment variable)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()
_raw = os.environ.get("DATASET_PATH", ".")
DATASET_PATH = Path(_raw).resolve() if _raw != "." else Path(__file__).parent.resolve()
MASTER_LIST = DATASET_PATH / "master_songs.jsonl"


def songs_dir() -> Path:
    d = DATASET_PATH / "songs"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ─────────────────────────────────────────────
# Master song list (JSONL — one record per line)
# ─────────────────────────────────────────────

def load_master() -> dict[str, dict]:
    """Load master_songs.jsonl into {title: record} dict."""
    if not MASTER_LIST.exists():
        return {}
    records = {}
    for line in MASTER_LIST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            records[rec["title"]] = rec
        except (json.JSONDecodeError, KeyError):
            continue
    return records


def save_master(records: dict[str, dict]):
    """Write master_songs.jsonl from {title: record} dict (sorted)."""
    MASTER_LIST.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for title in sorted(records):
        lines.append(json.dumps(records[title], ensure_ascii=False))
    MASTER_LIST.write_text("\n".join(lines) + "\n", encoding="utf-8")


def upsert_master(title: str, **fields) -> dict:
    """Add or update one song in the master list. Returns the record."""
    records = load_master()
    rec = records.get(title, {"title": title, "added_at": datetime.now().isoformat()})
    rec.update({k: v for k, v in fields.items() if v is not None})
    records[title] = rec
    save_master(records)
    return rec


def sync_master_from_disk():
    """Scan songs_dir and update master list status from actual files.

    Useful for bootstrapping: if songs already exist on disk but the
    master list doesn't know about them yet.
    """
    records = load_master()
    sd = songs_dir()
    updated = 0
    for d in sd.iterdir():
        if not d.is_dir():
            continue
        title = d.name
        rec = records.get(title, {"title": title, "added_at": datetime.now().isoformat()})

        has_inst = (d / "instrumental.wav").exists()
        has_lrc = (d / "lyrics.lrc").exists()
        has_txt = (d / "lyrics.txt").exists()

        new_status = "done" if has_inst else "pending"
        lyrics_status = "lrc" if has_lrc else ("txt" if has_txt else "none")

        if rec.get("status") != new_status or rec.get("lyrics") != lyrics_status:
            rec["status"] = new_status
            rec["lyrics"] = lyrics_status
            updated += 1

        # Pull youtube_url from metadata.json if we don't have it yet.
        meta_path = d / "metadata.json"
        if not rec.get("youtube_url") and meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("youtube_url"):
                rec["youtube_url"] = meta["youtube_url"]

        records[title] = rec

    save_master(records)
    return updated


# ─────────────────────────────────────────────
# Song list parsing (accepts many formats)
# ─────────────────────────────────────────────

def parse_song_input(file_path: Path) -> list[dict]:
    """Parse a song list from various file formats.

    Supported:
        .txt   — one title per line, # comments, blank lines ignored
        .json  — {"songs": [{"title": "..."}]} or [{"title": "..."}] or ["title1", ...]
        .jsonl — one JSON object per line: {"title": "...", "youtube_url": "..."}

    StreetPerformerMaster's repertoire.json is auto-detected (has "version" + "songs").
    """
    text = file_path.read_text(encoding="utf-8")
    suffix = file_path.suffix.lower()

    if suffix == ".txt":
        songs = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Support "title  url" format (tab or multi-space separated).
            parts = line.split("\t") if "\t" in line else line.split("  ", 1)
            title = parts[0].strip()
            url = parts[1].strip() if len(parts) > 1 else ""
            songs.append({"title": title, "youtube_url": url} if url else {"title": title})
        return songs

    if suffix == ".jsonl":
        songs = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                songs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return songs

    # .json
    data = json.loads(text)

    # StreetPerformerMaster repertoire.json format.
    if isinstance(data, dict) and "songs" in data:
        raw = data["songs"]
        return [
            {"title": s["title"], **{k: v for k, v in s.items() if k != "title"}}
            if isinstance(s, dict) else {"title": s}
            for s in raw
        ]

    # Plain list of strings.
    if isinstance(data, list) and data and isinstance(data[0], str):
        return [{"title": t} for t in data]

    # List of dicts.
    if isinstance(data, list):
        return data

    return []


# ─────────────────────────────────────────────
# add: Download + Demucs + lyrics
# ─────────────────────────────────────────────

def add_song(title: str, youtube_url: str | None = None,
             device: str = "cuda", lyrics_only: bool = False):
    """Full pipeline for one song: search → download → separate → lyrics."""
    from crawlers.youtube import search_song, download_audio, get_video_info
    from crawlers.lyrics import fetch_lyrics
    from processors.separate import separate_vocals

    song_dir = songs_dir() / title
    song_dir.mkdir(exist_ok=True)
    meta_path = song_dir / "metadata.json"

    # Register in master list immediately (even before processing).
    upsert_master(title, youtube_url=youtube_url, status="pending")

    already_processed = (song_dir / "instrumental.wav").exists()

    if lyrics_only:
        if (song_dir / "lyrics.lrc").exists():
            print(f"  {title}: lyrics already exist, skipping")
            return
        print(f"  {title}...", end=" ", flush=True)
        lrc, txt, source = fetch_lyrics(title)
        if lrc:
            (song_dir / "lyrics.lrc").write_text(lrc, encoding="utf-8")
        if txt:
            (song_dir / "lyrics.txt").write_text(txt, encoding="utf-8")
        lyrics_status = "lrc" if lrc else ("txt" if txt else "none")
        upsert_master(title, lyrics=lyrics_status)
        print(f"✓ {source}" if source else "✗ not found")
        return

    if already_processed:
        print(f"  {title}: already processed, skipping")
        upsert_master(title, status="done")
        return

    print(f"\n{'='*50}")
    print(f"Processing: {title}")
    print(f"{'='*50}")

    # Step 1: Find YouTube URL.
    if not youtube_url:
        print("  [1/4] Searching YouTube...", flush=True)
        candidates = search_song(title)
        if not candidates:
            print(f"  ✗ No YouTube results for '{title}'")
            return
        youtube_url = candidates[0].get("url") or candidates[0].get("webpage_url")
        print(f"  Found: {candidates[0].get('title', '?')} "
              f"({candidates[0].get('view_count', 0):,} views)")

    # Step 2: Download.
    print("  [2/4] Downloading...", flush=True)
    original_path = song_dir / "original.mp3"
    if not original_path.exists():
        try:
            download_audio(youtube_url, original_path)
        except Exception as e:
            print(f"  ✗ Download failed: {e}")
            return

    # Step 3: Demucs.
    print("  [3/4] Demucs (htdemucs_ft)...", flush=True)
    if not (song_dir / "instrumental.wav").exists():
        try:
            separate_vocals(original_path, song_dir, device=device)
        except Exception as e:
            print(f"  ✗ Separation failed: {e}")
            return

    # Step 4: Lyrics.
    print("  [4/4] Lyrics...", end=" ", flush=True)
    lrc_text, plain_text, source = fetch_lyrics(title)
    lyrics_info = {"source": source, "has_timestamps": False}
    if lrc_text:
        (song_dir / "lyrics.lrc").write_text(lrc_text, encoding="utf-8")
        lyrics_info["has_timestamps"] = True
        print(f"✓ {source} (LRC)")
    if plain_text:
        (song_dir / "lyrics.txt").write_text(plain_text, encoding="utf-8")
        if not lrc_text:
            print(f"✓ {source} (text only)")
    if not lrc_text and not plain_text:
        print("✗ not found")

    # Step 5: Metadata.
    info = get_video_info(youtube_url) if youtube_url else {}
    meta = {
        "title": title,
        "youtube_url": youtube_url or "",
        "youtube_title": (info or {}).get("title", ""),
        "duration_sec": (info or {}).get("duration"),
        "view_count": (info or {}).get("view_count"),
        "uploader": (info or {}).get("uploader", ""),
        "separation_model": "htdemucs_ft",
        "lyrics": lyrics_info,
        "files": {
            f.stem: f.name for f in song_dir.iterdir()
            if f.is_file() and f.name != "metadata.json"
        },
        "processed_at": datetime.now().isoformat(),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # Update master list.
    lyrics_status = "lrc" if lyrics_info.get("has_timestamps") else (
        "txt" if plain_text else "none")
    upsert_master(title, status="done", youtube_url=youtube_url,
                  lyrics=lyrics_status)
    print(f"  ✓ Done: {song_dir}")


def add_many(titles: list[str] | None = None, from_file: Path | None = None,
             url: str | None = None, device: str = "cuda",
             lyrics_only: bool = False):
    """Add one or more songs. Accepts titles directly or from a file."""
    songs = []

    if from_file:
        songs = parse_song_input(from_file)
        print(f"Loaded {len(songs)} songs from {from_file}")
    elif titles:
        songs = [{"title": t} for t in titles]

    if not songs:
        print("No songs to process.")
        return

    total = len(songs)
    for i, song in enumerate(songs, 1):
        title = song.get("title") or song.get("name", "")
        song_url = song.get("youtube_url") or url
        if not title:
            continue
        print(f"\n[{i}/{total}]", flush=True)
        add_song(title, youtube_url=song_url or None,
                 device=device, lyrics_only=lyrics_only)
        if not lyrics_only:
            time.sleep(1)


# ─────────────────────────────────────────────
# lyrics: Crawl lyrics for existing songs
# ─────────────────────────────────────────────

def crawl_all_lyrics():
    """Crawl lyrics for all songs that don't have them yet."""
    from crawlers.lyrics import fetch_lyrics

    sd = songs_dir()
    song_dirs = sorted([d for d in sd.iterdir() if d.is_dir()])
    total = len(song_dirs)
    found = 0
    skipped = 0

    print(f"Crawling lyrics for {total} songs...")
    for i, d in enumerate(song_dirs, 1):
        title = d.name
        if (d / "lyrics.lrc").exists() or (d / "lyrics.txt").exists():
            skipped += 1
            continue

        print(f"  [{i}/{total}] {title}...", end=" ", flush=True)
        lrc, txt, source = fetch_lyrics(title)
        if lrc:
            (d / "lyrics.lrc").write_text(lrc, encoding="utf-8")
            found += 1
            print(f"✓ {source}")
        if txt:
            (d / "lyrics.txt").write_text(txt, encoding="utf-8")
            if not lrc:
                found += 1
                print(f"✓ {source} (text)")
        if not lrc and not txt:
            print("✗")
        time.sleep(1)

    print(f"\nDone: {found} new, {skipped} skipped")


# ─────────────────────────────────────────────
# status + list
# ─────────────────────────────────────────────

def show_status():
    records = load_master()
    if not records:
        print(f"Master list empty. Run: pipeline.py sync  (to scan existing files)")
        print(f"  or: pipeline.py add --from songs.txt    (to add songs)")
        return

    total = len(records)
    done = sum(1 for r in records.values() if r.get("status") == "done")
    pending = sum(1 for r in records.values() if r.get("status") == "pending")
    has_lrc = sum(1 for r in records.values() if r.get("lyrics") == "lrc")
    has_txt = sum(1 for r in records.values() if r.get("lyrics") == "txt")
    no_lyrics = sum(1 for r in records.values() if r.get("lyrics") in (None, "none"))

    print(f"Dataset: {DATASET_PATH}")
    print(f"  Master list:    {MASTER_LIST.name}")
    print(f"  Total songs:    {total}")
    print(f"  Processed:      {done}")
    print(f"  Pending:        {pending}")
    print(f"  Lyrics (LRC):   {has_lrc}")
    print(f"  Lyrics (text):  {has_txt}")
    print(f"  No lyrics:      {no_lyrics}")


def list_songs(missing_lyrics: bool = False, missing_audio: bool = False,
               pending: bool = False):
    records = load_master()
    if not records:
        print("Master list empty. Run: pipeline.py sync")
        return

    for title in sorted(records):
        rec = records[title]
        status = rec.get("status", "?")
        lyrics = rec.get("lyrics", "none")

        if missing_lyrics and lyrics not in (None, "none"):
            continue
        if missing_audio and status == "done":
            continue
        if pending and status != "pending":
            continue

        icon = "♫" if status == "done" else ("⏳" if status == "pending" else "✗")
        lrc_icon = "LRC" if lyrics == "lrc" else ("TXT" if lyrics == "txt" else "---")
        print(f"  {icon} {lrc_icon}  {title}")


# ─────────────────────────────────────────────
# export
# ─────────────────────────────────────────────

def export_for_project(request_file: Path, output_dir: Path):
    """Export a subset based on a request JSON."""
    import shutil

    req = json.loads(request_file.read_text(encoding="utf-8"))

    # Accept both {"songs": [...]} and plain list.
    titles = req.get("songs", req) if isinstance(req, dict) else req
    if isinstance(titles, list) and titles and isinstance(titles[0], dict):
        titles = [s.get("title", "") for s in titles]
    wanted_files = req.get("outputs", ["instrumental.wav", "lyrics.lrc"]) \
        if isinstance(req, dict) else ["instrumental.wav", "lyrics.lrc"]

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    sd = songs_dir()

    copied = 0
    missing = 0
    for title in titles:
        if not title:
            continue
        src = sd / title
        if not src.exists():
            print(f"  ⚠ {title}: not in dataset")
            missing += 1
            continue
        for fname in wanted_files:
            src_file = src / fname
            if src_file.exists():
                dst = output_dir / f"{title}{src_file.suffix}"
                shutil.copy2(src_file, dst)
                copied += 1

    print(f"Exported: {copied} files, {missing} songs not found")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="MandpopDataPipeline — Mandarin pop song dataset builder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # add
    p_add = sub.add_parser("add", help="Add songs to the dataset",
                           formatter_class=argparse.RawDescriptionHelpFormatter,
                           epilog=(
                               "examples:\n"
                               '  pipeline.py add "告白氣球"\n'
                               '  pipeline.py add "告白氣球" "小幸運" "演員"\n'
                               '  pipeline.py add --from songs.txt\n'
                               '  pipeline.py add --from repertoire.json\n'
                               '  pipeline.py add --from songs.txt --lyrics-only'
                           ))
    p_add.add_argument("titles", nargs="*", help="Song title(s)")
    p_add.add_argument("--from", dest="from_file", type=Path,
                       help="Load songs from file (.txt / .json / .jsonl)")
    p_add.add_argument("--url", help="YouTube URL (only for single song)")
    p_add.add_argument("--device", default="cuda", choices=["cpu", "cuda"])
    p_add.add_argument("--lyrics-only", action="store_true",
                       help="Only crawl lyrics, skip download + separation")

    # list
    p_list = sub.add_parser("list", help="List songs in the dataset")
    p_list.add_argument("--missing-lyrics", action="store_true",
                        help="Only show songs without lyrics")
    p_list.add_argument("--missing-audio", action="store_true",
                        help="Only show songs without instrumental")
    p_list.add_argument("--pending", action="store_true",
                        help="Only show songs not yet processed")

    # lyrics
    sub.add_parser("lyrics", help="Crawl lyrics for all songs without them")

    # status
    sub.add_parser("status", help="Show dataset statistics")

    # discover
    p_disc = sub.add_parser("discover",
                            help="Discover popular songs from music charts / playlists")
    p_disc.add_argument("--era",
                        help="Era: 2000s / 2010s / 2020s / classic / ktv / all")
    p_disc.add_argument("--chart",
                        help="NetEase chart: hot / new / original / surge")
    p_disc.add_argument("--playlist", type=int,
                        help="Specific NetEase playlist ID")
    p_disc.add_argument("--add", action="store_true",
                        help="Also register discovered songs in master list (pending)")
    p_disc.add_argument("--process", action="store_true",
                        help="Also download + separate + lyrics (slow)")
    p_disc.add_argument("--output", "-o", type=Path,
                        help="Save song list to file (default: print to stdout)")
    p_disc.add_argument("--device", default="cuda", choices=["cpu", "cuda"])

    # sync
    sub.add_parser("sync", help="Scan disk and update master_songs.jsonl from existing files")

    # export
    p_export = sub.add_parser("export", help="Export subset for a consumer project")
    p_export.add_argument("--request", type=Path, required=True,
                          help="JSON file listing songs + desired outputs")
    p_export.add_argument("--output", type=Path, required=True,
                          help="Output directory")

    args = parser.parse_args()

    if args.command == "add":
        if not args.titles and not args.from_file:
            p_add.print_help()
            return
        add_many(titles=args.titles or None, from_file=args.from_file,
                 url=args.url, device=args.device,
                 lyrics_only=args.lyrics_only)
    elif args.command == "list":
        list_songs(missing_lyrics=args.missing_lyrics,
                   missing_audio=args.missing_audio,
                   pending=args.pending)
    elif args.command == "lyrics":
        crawl_all_lyrics()
    elif args.command == "discover":
        from crawlers.charts import discover_songs
        songs = discover_songs(era=args.era, playlist_id=args.playlist,
                               chart=args.chart)
        # Deduplicate against master list.
        existing = load_master()
        new_songs = [s for s in songs if s["title"] not in existing]
        print(f"\nDiscovered {len(songs)} songs, {len(new_songs)} new "
              f"({len(songs) - len(new_songs)} already in master list)")

        if args.output:
            args.output.write_text(
                "\n".join(s["title"] for s in new_songs) + "\n",
                encoding="utf-8",
            )
            print(f"Saved {len(new_songs)} new titles to {args.output}")

        if args.add or args.process:
            for s in new_songs:
                upsert_master(s["title"], artist=s.get("artist"),
                              netease_id=s.get("netease_id"), status="pending")
            print(f"Registered {len(new_songs)} songs as pending in master list")

        if args.process:
            print(f"\nProcessing {len(new_songs)} songs...")
            for i, s in enumerate(new_songs, 1):
                print(f"\n[{i}/{len(new_songs)}]", flush=True)
                add_song(s["title"], device=args.device)
                time.sleep(1)

        if not args.output and not args.add and not args.process:
            # Just print the new songs.
            for s in new_songs:
                print(f"  {s['title']}  ({s.get('artist', '')})")

    elif args.command == "sync":
        updated = sync_master_from_disk()
        records = load_master()
        print(f"Synced: {updated} records updated, {len(records)} total in master list")
    elif args.command == "status":
        show_status()
    elif args.command == "export":
        export_for_project(args.request, args.output)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
