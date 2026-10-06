"""Vietnamese STT server on phostt's Zipformer-vi RNN-T model.

Drop-in replacement for vietnamese-stt-server: same endpoints, same request/response
shapes (POST /transcribe, WS /ws/stream, GET /health, /static test page), so clients
only need the new host/port.

Inference runs the exact ONNX bundle phostt ships (see download_model.py) through
sherpa-onnx, which phostt's Rust engine is itself ported from. sherpa-onnx has
Windows/Linux/macOS wheels, so the whole server installs with `uv sync` -- no Rust
toolchain, no Docker.
"""
import asyncio
import logging
import os
import subprocess
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import sherpa_onnx
from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

import hotwords
import paths
from download_model import MODEL_ID, VAD_FILE, download, model_present

MODEL_DIR = Path(os.environ.get("MODEL_DIR") or paths.MODEL_DIR)
SAMPLE_RATE = 16000
# onnxruntime execution provider: "cpu" works everywhere. "cuda" needs the CUDA build
# of sherpa-onnx (see README); the 30M-param int8 model is already ~60x real time on CPU.
PROVIDER = os.environ.get("PROVIDER", "cpu").lower()
NUM_THREADS = int(os.environ.get("NUM_THREADS", str(min(4, os.cpu_count() or 1))))
# The model emits UPPERCASE text; PhoWhisper (the previous server) emitted lowercase.
# "lower" keeps client-visible output close to before; "upper"/"none" leave it as-is.
TEXT_CASE = os.environ.get("TEXT_CASE", "lower").lower()
# "modified_beam_search" costs ~40% more CPU than phostt's "greedy_search" (still ~60x
# real time) and recovers words greedy drops on short, fast clips.
DECODING_METHOD = os.environ.get("DECODING_METHOD", "modified_beam_search")
MAX_ACTIVE_PATHS = int(os.environ.get("MAX_ACTIVE_PATHS", "8"))
# Silero VAD speech threshold. The default 0.5 missed real quiet speech in testing.
VAD_THRESHOLD = float(os.environ.get("VAD_THRESHOLD", "0.3"))
# Loanwords to boost and fix (see hotwords.py). Boosting needs modified_beam_search.
HOTWORDS_FILE = Path(os.environ.get("HOTWORDS_FILE") or paths.APP_DIR / "hotwords.txt")
# Default boost per hotword. Around 4 the model started repeating words ("zalo zalo").
HOTWORDS_SCORE = float(os.environ.get("HOTWORDS_SCORE", "2.0"))
# Silence added around each clip before decoding: without the lead-in the encoder tends
# to drop the first word, without the tail the last one.
_PAD_HEAD = np.zeros(SAMPLE_RATE // 2, dtype=np.float32)
_PAD_TAIL = np.zeros(SAMPLE_RATE, dtype=np.float32)
# Live preview (/ws/stream): re-transcribe the in-progress window whenever at least
# STREAM_UPDATE_SECONDS of new audio has arrived, and commit the window once it reaches
# STREAM_WINDOW_SECONDS so each pass stays short.
STREAM_UPDATE_SECONDS = float(os.environ.get("STREAM_UPDATE_SECONDS", "1.0"))
STREAM_WINDOW_SECONDS = float(os.environ.get("STREAM_WINDOW_SECONDS", "10.0"))


def _ffmpeg_bin() -> str:
    """$FFMPEG_BIN, else the static ffmpeg the imageio-ffmpeg wheel ships (so nothing
    has to be installed on the host), which itself honors $IMAGEIO_FFMPEG_EXE."""
    if os.environ.get("FFMPEG_BIN"):
        return os.environ["FFMPEG_BIN"]
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


FFMPEG_BIN = _ffmpeg_bin()

logger = logging.getLogger("uvicorn.error")

model_state = {}


def _hotword_options() -> dict:
    """Load hotwords.txt: set up alias replacement, and return the recognizer options
    that enable boosting (empty when there's nothing to boost)."""
    model_state["fix_aliases"] = lambda text: text
    if not HOTWORDS_FILE.is_file():
        return {}
    entries = hotwords.parse(HOTWORDS_FILE)
    if not entries:
        return {}
    model_state["fix_aliases"] = hotwords.build_replacer(entries)
    logger.info("Hotwords from %s: %s", HOTWORDS_FILE, ", ".join(e.word for e in entries))
    if DECODING_METHOD != "modified_beam_search":
        logger.warning("Hotword boosting needs DECODING_METHOD=modified_beam_search; "
                       "only the aliases in %s will apply.", HOTWORDS_FILE.name)
        return {}
    sherpa_file = MODEL_DIR / "hotwords.active.txt"
    hotwords.write_sherpa_file(entries, sherpa_file)
    return {
        "hotwords_file": str(sherpa_file),
        "hotwords_score": HOTWORDS_SCORE,
        "modeling_unit": "bpe",
        "bpe_vocab": str(hotwords.ensure_bpe_vocab(MODEL_DIR)),
    }


def _load_recognizer(provider: str) -> "sherpa_onnx.OfflineRecognizer":
    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(MODEL_DIR / "encoder.int8.onnx"),
        decoder=str(MODEL_DIR / "decoder.onnx"),
        joiner=str(MODEL_DIR / "joiner.int8.onnx"),
        tokens=str(MODEL_DIR / "tokens.txt"),
        num_threads=NUM_THREADS,
        sample_rate=SAMPLE_RATE,
        decoding_method=DECODING_METHOD,
        max_active_paths=MAX_ACTIVE_PATHS,
        provider=provider,
        **_hotword_options(),
    )
    # Warm up now so a broken provider fails at startup, not on a user's first request.
    _decode(recognizer, np.zeros(SAMPLE_RATE, dtype=np.float32))
    return recognizer


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not model_present(MODEL_DIR):
        logger.info("Model not found in %s; downloading it now.", MODEL_DIR)
        await asyncio.to_thread(download, MODEL_DIR)
    provider = PROVIDER
    try:
        model_state["recognizer"] = _load_recognizer(provider)
    except Exception:
        if provider == "cpu":
            raise
        logger.exception("Failed to load model with provider=%s; falling back to CPU.", provider)
        provider = "cpu"
        model_state["recognizer"] = _load_recognizer(provider)
    model_state["device"] = provider
    logger.info(
        "Model loaded from %s (provider=%s, threads=%d, decoding=%s)",
        MODEL_DIR, provider, NUM_THREADS, DECODING_METHOD,
    )
    yield
    model_state.clear()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(paths.STATIC_DIR)), name="static")


def load_audio(raw_bytes: bytes) -> np.ndarray:
    """Decode arbitrary audio bytes to 16kHz mono float32 via ffmpeg."""
    # A temp file rather than stdin: containers like MP4/M4A need a seekable input.
    src = tempfile.NamedTemporaryFile(suffix=".input", delete=False)
    try:
        src.write(raw_bytes)
        src.close()
        result = subprocess.run(
            [FFMPEG_BIN, "-v", "error", "-i", src.name,
             "-ar", str(SAMPLE_RATE), "-ac", "1", "-f", "s16le", "-"],
            capture_output=True,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=400, detail="Could not decode audio file")
        return np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    finally:
        Path(src.name).unlink(missing_ok=True)


def _decode(recognizer: "sherpa_onnx.OfflineRecognizer", audio: np.ndarray) -> str:
    stream = recognizer.create_stream()
    stream.accept_waveform(SAMPLE_RATE, audio)
    recognizer.decode_stream(stream)
    return stream.result.text.strip()


def has_speech(audio: np.ndarray) -> bool:
    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(MODEL_DIR / VAD_FILE)
    config.silero_vad.threshold = VAD_THRESHOLD
    config.silero_vad.min_speech_duration = 0.1
    config.silero_vad.min_silence_duration = 0.1
    config.sample_rate = SAMPLE_RATE
    # Stateful, so one per call; it loads in a few ms.
    vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=1)
    window = config.silero_vad.window_size
    for start in range(0, len(audio), window):
        vad.accept_waveform(audio[start:start + window])
        if vad.is_speech_detected():
            return True
    vad.flush()
    return not vad.empty()


def transcribe_array(audio: np.ndarray) -> str:
    # The model never outputs "nothing": silence and noise come back as "ừ". Gate on
    # Silero VAD and return "" when it hears no speech. Only a gate -- the whole clip is
    # still decoded, so no context is cut off at segment edges.
    if len(audio) < SAMPLE_RATE // 10 or not has_speech(audio):
        return ""
    text = _decode(model_state["recognizer"], np.concatenate([_PAD_HEAD, audio, _PAD_TAIL]))
    if TEXT_CASE == "lower":
        text = text.lower()
    return model_state["fix_aliases"](text)


@app.post("/transcribe")
async def transcribe(file: UploadFile):
    raw_bytes = await file.read()
    # Run decode + inference off the event loop so live-preview sockets stay responsive.
    audio = await asyncio.to_thread(load_audio, raw_bytes)
    return {"text": await asyncio.to_thread(transcribe_array, audio)}


@app.websocket("/ws/stream")
async def stream(websocket: WebSocket):
    """Live preview transcription, meant to run alongside a client-side recording.

    The client sends raw PCM16LE mono 16kHz audio as binary frames and closes the socket
    when done. The server replies with {"text": "..."} -- the full preview so far, which
    replaces the previous one. Only one inference runs at a time per socket; audio that
    arrives meanwhile is picked up by the next pass, so a slow device just updates less
    often instead of falling behind.
    """
    await websocket.accept()
    update_samples = int(STREAM_UPDATE_SECONDS * SAMPLE_RATE)
    window_samples = int(STREAM_WINDOW_SECONDS * SAMPLE_RATE)
    window = np.empty(0, dtype=np.float32)  # audio since the last commit
    committed: "list[str]" = []
    audio_arrived = asyncio.Event()

    async def preview_loop():
        nonlocal window
        transcribed_len = 0
        while True:
            await audio_arrived.wait()
            audio_arrived.clear()
            if len(window) - transcribed_len < update_samples:
                continue
            snapshot = window
            transcribed_len = len(snapshot)
            text = await asyncio.to_thread(transcribe_array, snapshot)
            if len(snapshot) >= window_samples:
                if text:
                    committed.append(text)
                # The receiver only ever appends, so everything past the snapshot is new.
                window = window[len(snapshot):]
                transcribed_len = 0
                text = ""
            await websocket.send_json({"text": " ".join(committed + [text]).strip()})

    preview_task = asyncio.create_task(preview_loop())
    try:
        while not preview_task.done():
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes"):
                pcm16 = np.frombuffer(message["bytes"], dtype=np.int16)
                window = np.concatenate([window, pcm16.astype(np.float32) / 32768.0])
                audio_arrived.set()
    except WebSocketDisconnect:
        pass
    finally:
        preview_task.cancel()


@app.get("/health")
async def health():
    return {"status": "ok", "device": model_state.get("device", PROVIDER), "model": MODEL_ID}


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8123")))
    # HTTPS: browsers only allow the web page's mic access on https:// (or localhost).
    # make_cert.py creates a self-signed pair.
    parser.add_argument("--ssl-certfile", default=os.environ.get("SSL_CERTFILE") or None)
    parser.add_argument("--ssl-keyfile", default=os.environ.get("SSL_KEYFILE") or None)
    args = parser.parse_args()

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        ssl_certfile=args.ssl_certfile,
        ssl_keyfile=args.ssl_keyfile,
    )
