# MandpopDataPipeline

> Automated dataset builder for Mandarin pop music — from a song title to production-ready stems + timestamped lyrics.

From one song title, this pipeline automatically:
1. **Finds** the official MV on YouTube (highest view count, filters out covers/piano/karaoke)
2. **Downloads** the audio
3. **Separates** vocals from instrumentals using Demucs `htdemucs_ft` (Meta's SOTA model)
4. **Crawls** timestamped lyrics (LRC format) from NetEase Cloud Music
5. **Outputs** a structured, per-song directory ready for downstream use

```
python pipeline.py add "告白氣球"
```

```
D:\MandpopDataset\songs\告白氣球\
├── original.mp3         YouTube source audio
├── instrumental.wav     Vocal-separated accompaniment (htdemucs_ft)
├── vocals.wav           Isolated vocals
├── lyrics.lrc           Time-synced lyrics [00:23.93]塞纳河畔 左岸的咖啡
├── lyrics.txt           Plain text lyrics
└── metadata.json        Duration, BPM, YouTube URL, lyrics source, etc.
```

---

## Why This Exists

Mandarin pop karaoke/cover creators need three things that don't exist together in any open dataset:
- **Clean instrumentals** (vocal-removed, not re-recorded)
- **Timestamped lyrics** (LRC format, synced to the music)
- **Structured metadata** (key, BPM, duration, artist)

Commercial KTV providers (好樂迪, 錢櫃) have this data but it's proprietary. This pipeline lets you build your own from public YouTube sources.

---

## Setup

```bash
git clone https://github.com/geniuspudding/MandpopDataPipeline.git
cd MandpopDataPipeline
pip install -r requirements.txt
cp .env.example .env
# Edit .env: set DATASET_PATH to your output directory
```

### System Dependencies

| Tool | Install | Purpose |
|------|---------|---------|
| Python ≥ 3.10 | https://python.org | |
| FFmpeg | `winget install ffmpeg` | Audio conversion |
| NVIDIA GPU + CUDA | Optional but 10x faster | Demucs separation |

---

## Commands

### Add songs

```bash
# One song
python pipeline.py add "告白氣球"

# Multiple songs at once
python pipeline.py add "告白氣球" "小幸運" "演員"

# With explicit YouTube URL
python pipeline.py add "告白氣球" --url "https://youtube.com/watch?v=..."

# From a text file (one title per line, # comments supported)
python pipeline.py add --from songs.txt

# From JSON (multiple formats auto-detected)
python pipeline.py add --from songs.json
python pipeline.py add --from repertoire.json     # StreetPerformerMaster format

# Only crawl lyrics (skip download + Demucs)
python pipeline.py add --from songs.txt --lyrics-only

# Use CPU (no GPU)
python pipeline.py add "新歌" --device cpu
```

**Supported file formats for `--from`:**

| Format | Example |
|--------|---------|
| `.txt` | One title per line. `title\tURL` for explicit URLs. |
| `.json` | `{"songs": [{"title": "..."}]}` or `["title1", "title2"]` |
| `.jsonl` | One `{"title": "...", "youtube_url": "..."}` per line |

### Crawl lyrics for all songs

```bash
python pipeline.py lyrics
```

Fetches LRC (timestamped) lyrics from NetEase Cloud Music API for every song in the dataset that doesn't have lyrics yet.

### Check dataset status

```bash
python pipeline.py status
```
```
Dataset: D:\MandpopDataset
  Songs:          156
  Instrumental:   156/156
  Vocals:         156/156
  Lyrics (LRC):   148/156
  Lyrics (text):  148/156
```

### List songs

```bash
python pipeline.py list                    # All songs with status
python pipeline.py list --missing-lyrics   # Songs without lyrics
python pipeline.py list --missing-audio    # Songs without instrumental
```
```
  ♫ LRC  告白氣球
  ♫ LRC  小幸運
  ♫ ---  一路向北        ← missing lyrics (Jay Chou, not on NetEase)
```

### Export subset for a consumer project

```bash
python pipeline.py export --request request.json --output ./export
```

`request.json`:
```json
{
  "songs": ["告白氣球", "小幸運"],
  "outputs": ["instrumental.wav", "lyrics.lrc"]
}
```

---

## Architecture

This repo is a **data factory**. It doesn't build apps — it produces data for other projects to consume.

```
MandpopDataPipeline (this repo)
  │
  ├─ crawlers/youtube.py    yt-dlp search + download
  ├─ crawlers/lyrics.py     NetEase Cloud Music API → LRC
  ├─ processors/separate.py Demucs htdemucs_ft → stems
  └─ pipeline.py            CLI orchestrator
  │
  ▼ outputs to
D:\MandpopDataset\songs\    shared dataset (not in any repo)
  │
  ├──▶ StreetPerformerMaster   iOS karaoke player for street performers
  └──▶ VocalStudio             Recording, mixing, cover video production
```

Consumer projects read from the dataset directory via a shared `DATASET_PATH` environment variable. They don't need to clone this repo.

---

## Lyrics Sources

| Source | Format | Coverage | Note |
|--------|--------|----------|------|
| **NetEase Cloud Music** | LRC (timestamped) | ~95% of Mandarin pop | Primary source |
| YouTube auto-subs | LRC (timestamped) | Varies | Fallback |
| KKBOX | Text | High | Planned |
| WhisperX | LRC (generated) | 100% | Last resort, from vocals.wav |

> ⚠ Jay Chou's lyrics are unavailable on NetEase (copyright withdrawn in 2018). Use QQ Music or KKBOX for his songs.

---

## Audio Quality

| Aspect | Detail |
|--------|--------|
| Separation model | `htdemucs_ft` (Meta's Demucs, fine-tuned for vocal separation) |
| Sample rate | 44.1 kHz |
| Bit depth | 32-bit float (WAV) |
| Residual vocals | Very low (htdemucs_ft is current SOTA for Demucs family) |
| No post-processing | Raw htdemucs_ft output — tested via AB comparison, additional EQ/loudnorm degrades quality |

---

## License

The **code** in this repo is MIT licensed.

The **audio files** produced by this pipeline are derived from copyrighted YouTube content and are for **personal use only**. Do not redistribute the processed audio. The pipeline itself (code + song list) can be shared freely — users generate their own audio by running it.
