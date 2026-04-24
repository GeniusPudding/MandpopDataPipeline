"""
人聲分離 - 使用 Demucs (Meta 開源)

輸入: 原曲音檔路徑
輸出: instrumental.wav (去人聲的伴奏)

Demucs 會把歌曲分成 4 軌: vocals, drums, bass, other
我們把 drums + bass + other 混回來就是乾淨的伴奏
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

DEMUCS_MODEL = "htdemucs_ft"  # fine-tuned 版，人聲分離品質最佳


def separate_vocals(
    input_audio: Path,
    output_dir: Path,
    model: str = DEMUCS_MODEL,
    device: str = "cpu",
) -> Path:
    """
    執行 Demucs 分離人聲，回傳合成好的 instrumental.wav 路徑

    Args:
        input_audio: 原曲音檔
        output_dir: 輸出資料夾 (會產出 instrumental.wav 於此)
        model: Demucs 模型名稱 (預設 htdemucs)
        device: "cpu" 或 "cuda"

    Returns:
        Path to instrumental.wav
    """
    input_audio = Path(input_audio).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_audio.exists():
        raise FileNotFoundError(f"找不到輸入音檔: {input_audio}")

    # Demucs 會在指定的 --out 目錄下建立 {model}/{原檔名}/ 子資料夾
    demucs_out = output_dir / "_demucs_raw"
    demucs_out.mkdir(exist_ok=True)

    print(f"  [Demucs] 模型={model}, 裝置={device}")
    print(f"  [Demucs] 分離中... (首次執行會下載模型權重)")

    cmd = [
        sys.executable, "-m", "demucs.separate",
        "-n", model,
        "-d", device,
        "--out", str(demucs_out),
        str(input_audio),
    ]
    # Windows: 明確指定 UTF-8 編碼，否則 Demucs 寫到 stderr 的中文檔名/字元
    # 會讓預設 cp950 解碼器炸 UnicodeDecodeError
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        print(f"  [Demucs] stdout: {(result.stdout or '')[-500:]}")
        print(f"  [Demucs] stderr: {(result.stderr or '')[-500:]}")
        raise RuntimeError("Demucs 執行失敗，請確認已安裝 demucs 並可執行")

    # 找到 demucs 產出的 stems
    stem_dir = demucs_out / model / input_audio.stem
    if not stem_dir.exists():
        # demucs 可能用原始副檔名命名資料夾
        candidates = list((demucs_out / model).glob(f"{input_audio.stem}*"))
        if not candidates:
            raise RuntimeError(f"找不到 Demucs 輸出: {stem_dir}")
        stem_dir = candidates[0]

    drums = stem_dir / "drums.wav"
    bass = stem_dir / "bass.wav"
    other = stem_dir / "other.wav"
    vocals = stem_dir / "vocals.wav"

    for p in (drums, bass, other):
        if not p.exists():
            raise RuntimeError(f"缺少 stem: {p}")

    # 把 drums + bass + other 相加成 instrumental
    print(f"  [Demucs] 合成 instrumental (drums + bass + other)")
    instrumental_path = output_dir / "instrumental.wav"
    _mix_stems([drums, bass, other], instrumental_path)

    # 額外保留 vocals 以防後續要用
    if vocals.exists():
        shutil.copy2(vocals, output_dir / "vocals.wav")

    # 清掉 demucs 原始輸出資料夾節省空間
    shutil.rmtree(demucs_out, ignore_errors=True)

    return instrumental_path


def _mix_stems(stem_paths: list[Path], output_path: Path) -> None:
    """把多個 stem 相加混音成一個 wav"""
    mixed = None
    sr = None
    for p in stem_paths:
        audio, cur_sr = sf.read(str(p), always_2d=True)
        if sr is None:
            sr = cur_sr
            mixed = np.zeros_like(audio, dtype=np.float64)
        elif cur_sr != sr:
            raise RuntimeError(f"Stem sample rate 不一致: {p}")
        mixed += audio

    # 防 clipping: 如果峰值超過 1.0 就等比縮放
    peak = np.max(np.abs(mixed))
    if peak > 1.0:
        mixed = mixed / peak * 0.99

    sf.write(str(output_path), mixed.astype(np.float32), sr)
