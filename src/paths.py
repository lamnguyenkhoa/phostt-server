"""Filesystem layout shared by every module in src/.

The Python code lives in src/; data (models/, static/, cert.pem/key.pem) sits one level
up in the app folder. Paths are resolved from this file rather than the working
directory, so the scripts behave the same wherever they are run from.
"""
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
APP_DIR = SRC_DIR.parent

STATIC_DIR = APP_DIR / "static"
# Extracted Zipformer-vi bundle (encoder/decoder/joiner ONNX + tokens.txt).
MODEL_DIR = APP_DIR / "models"
