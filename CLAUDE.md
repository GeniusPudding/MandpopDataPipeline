# MandpopDataPipeline — 華語流行歌資料集建置

> 這份是給 Claude（或任何開發者）的上下文文件。

## 定位

這是一個**資料工廠**：負責下載、處理、標註華語流行歌曲，產出結構化的資料集供其他專案使用。

**本 repo 不做**：iOS app、錄音混音、影片製作。那些是消費者專案的事。

## 消費者專案

| 專案 | 需要什麼 | 位置 |
|------|---------|------|
| **StreetPerformerMaster** | instrumental.m4a + lyrics.lrc（iOS 點歌 app） | `../StreetPerformerMaster/` |
| **VocalStudio**（未來） | instrumental.wav + vocals.wav + lyrics.lrc（錄音混音） | `../VocalStudio/` |

## 資料集結構

程式碼和資料同在一個 repo。音訊檔 .gitignored（太大 + 版權），metadata + 歌詞被 track：

```
D:\MandpopDataset\              (= this repo)
├── pipeline.py                 主 CLI
├── setup_env.py                一行安裝
├── crawlers/                   YouTube 下載、歌詞爬蟲、排行榜爬蟲
├── processors/                 Demucs 人聲分離
├── master_songs.jsonl          歌單索引（tracked）
├── songs/
│   └── {歌名}/
│       ├── metadata.json       tracked
│       ├── lyrics.lrc          tracked（行級時間軸）
│       ├── lyrics.txt          tracked（純文本）
│       ├── instrumental.wav    .gitignored
│       ├── vocals.wav          .gitignored
│       └── original.mp3        .gitignored
└── .gitignore                  排除 *.wav *.mp3 *.m4a
```

## 主要指令

```bash
python pipeline.py add "告白氣球"                    # 加一首歌
python pipeline.py add "告白氣球" "小幸運" "演員"     # 多首
python pipeline.py add --from songs.txt              # 從檔案批次加
python pipeline.py add --from songs.txt --lyrics-only # 只爬歌詞
python pipeline.py discover --era all --add          # 從排行榜發掘歌曲
python pipeline.py lyrics                            # 補爬歌詞
python pipeline.py status                            # 統計
python pipeline.py list --missing-lyrics             # 列出缺歌詞的
python pipeline.py sync                              # 從磁碟同步 master list
python pipeline.py export --request req.json --output ./out
```

## 歌詞來源（fallback 鏈）

1. **網易雲音樂 API**（有 LRC 時間軸，華語覆蓋最高）
2. **QQ 音樂 API**（有 LRC，補網易雲缺的，尤其周杰倫）
3. **YouTube 自動字幕**（有時間軸但品質差，最後手段）

## 技術棧

- **yt-dlp**：YouTube 下載
- **Demucs htdemucs_ft**：人聲分離（需要 NVIDIA GPU）
- **requests + BeautifulSoup**：歌詞爬蟲
- **Python 3.10+**

## 與消費者專案的介面

兩個 repo 透過 `.env` 的 `DATASET_PATH` 指向同一個資料夾。消費者不需要 clone 本 repo，只要讀 `D:\MandpopDataset\` 裡的資料。

## Git 規範

- **commit 訊息不加 Co-Authored-By**。不要加任何 AI co-author 標記。
- commit message 用英文，簡潔描述改了什麼。
- 音訊檔（*.wav, *.mp3, *.m4a）永遠不進 git。
