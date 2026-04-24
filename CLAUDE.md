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

## 資料集輸出路徑

所有處理結果存在 `DATASET_PATH`（預設 `D:\MandpopDataset`），不在 repo 內：

```
D:\MandpopDataset\
└── songs\
    └── {歌名}\
        ├── original.mp3         YouTube 原曲
        ├── instrumental.wav     htdemucs_ft 去人聲
        ├── vocals.wav           分離出的人聲
        ├── lyrics.lrc           逐行對時歌詞（網易雲）
        ├── lyrics.txt           純文本歌詞
        └── metadata.json        完整 metadata
```

## 主要指令

```bash
python pipeline.py add "告白氣球"                    # 加一首歌
python pipeline.py add "新歌" --url "https://..."     # 指定 URL
python pipeline.py batch repertoire.json              # 批次處理歌單
python pipeline.py lyrics                             # 補爬歌詞
python pipeline.py status                             # 看統計
python pipeline.py export --request req.json --output ./out  # 匯出子集
```

## 處理流程

```
song title
  → YouTube search (yt-dlp ytsearch10, 取觀看數最高)
  → download original.mp3
  → Demucs htdemucs_ft → instrumental.wav + vocals.wav
  → NetEase Cloud Music API → lyrics.lrc + lyrics.txt
  → metadata.json
```

## 歌詞來源優先順序

1. **網易雲音樂 API**（有 LRC 時間軸，華語覆蓋最高）
2. YouTube 自動字幕（fallback，有時間軸但品質差）
3. （未來：KKBOX、WhisperX 從 vocals.wav 轉錄）

注意：周杰倫的歌在網易雲沒有歌詞（版權撤走），需要其他來源。

## 技術棧

- **yt-dlp**：YouTube 下載
- **Demucs htdemucs_ft**：人聲分離（需要 NVIDIA GPU）
- **requests + BeautifulSoup**：歌詞爬蟲
- **Python 3.10+**

## 環境設定

```bash
cp .env.example .env
# 編輯 .env 設定 DATASET_PATH
pip install -r requirements.txt
```

## 與消費者專案的介面

消費者專案透過兩個東西跟本 repo 溝通：
1. `.env` 裡的 `DATASET_PATH` — 指向同一個資料夾
2. `export --request` — 消費者提交一份 JSON 列出要哪些歌 + 要哪些檔案

消費者**不需要** clone 本 repo。只要 `D:\MandpopDataset\` 裡有資料，直接讀就好。
