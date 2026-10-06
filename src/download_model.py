"""Fetch the Zipformer-vi RNN-T bundle phostt runs on (plus Silero VAD) into models/.

Same pinned release and checksum as phostt's own `phostt download` (src/model/mod.rs
upstream): the int8 sherpa-onnx export, ~75MB. Filenames are normalized to the stable
names phostt uses (encoder.int8.onnx, decoder.onnx, joiner.int8.onnx), so a model dir
populated by the phostt CLI (~/.phostt/models) works here too, and vice versa.

    uv run src/download_model.py            # into models/
    uv run src/download_model.py D:/models  # somewhere else (then set MODEL_DIR)
"""
import hashlib
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import paths

MODEL_ID = "sherpa-onnx-zipformer-vi-int8-2025-04-20"
URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{MODEL_ID}.tar.bz2"
SHA256 = "48d0fdc9b3515eb9b00c4dfec2883207ee5ebe5c95b1959e7afce87fc3391938"

# Stable name -> prefix of the epoch-specific name inside the tarball.
RENAMES = {
    "encoder.int8.onnx": "encoder",
    "decoder.onnx": "decoder",
    "joiner.int8.onnx": "joiner",
}
# Silero VAD, used to gate silence: the RNN-T model answers non-speech with "ừ".
VAD_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
VAD_FILE = "silero_vad.onnx"
MODEL_FILES = [*RENAMES, "tokens.txt", VAD_FILE]


def model_present(model_dir: Path) -> bool:
    return all((model_dir / name).is_file() for name in MODEL_FILES)


def _normalize_filenames(model_dir: Path) -> None:
    for target, prefix in RENAMES.items():
        if (model_dir / target).exists():
            continue
        candidates = sorted(
            p for p in model_dir.glob(f"{prefix}*.onnx")
            # Prefer the int8 export for encoder/joiner, the fp32 one for the decoder
            # (the bundle's int8 decoder is the one phostt avoids too).
            if (".int8." in p.name) == (".int8." in target)
        )
        if not candidates:
            raise FileNotFoundError(f"No {prefix}*.onnx in {model_dir} to use as {target}")
        candidates[0].rename(model_dir / target)


def download(model_dir: Path = paths.MODEL_DIR) -> Path:
    if model_present(model_dir):
        print(f"Model already present in {model_dir}")
        return model_dir
    model_dir.mkdir(parents=True, exist_ok=True)
    if not (model_dir / VAD_FILE).is_file():
        print(f"Downloading {VAD_URL} ...")
        urllib.request.urlretrieve(VAD_URL, model_dir / VAD_FILE)
    if model_present(model_dir):
        print(f"Done. Model is in {model_dir}")
        return model_dir
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / f"{MODEL_ID}.tar.bz2"
        print(f"Downloading {URL} ...")
        digest = hashlib.sha256()
        with urllib.request.urlopen(URL) as resp, open(archive, "wb") as out:
            while chunk := resp.read(1 << 20):
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != SHA256:
            raise RuntimeError(f"Checksum mismatch for {archive.name}: got {digest.hexdigest()}")
        with tarfile.open(archive, "r:bz2") as tar:
            tar.extractall(tmp, filter="data")
        src = Path(tmp) / MODEL_ID
        for item in src.iterdir():
            dest = model_dir / item.name
            if dest.exists():
                shutil.rmtree(dest) if dest.is_dir() else dest.unlink()
            shutil.move(str(item), dest)
    _normalize_filenames(model_dir)
    print(f"Done. Model is in {model_dir}")
    return model_dir


if __name__ == "__main__":
    download(Path(sys.argv[1]) if len(sys.argv) > 1 else paths.MODEL_DIR)
