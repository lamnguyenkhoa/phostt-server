# phostt STT Server

Vietnamese speech-to-text server running the model behind
[phostt](https://github.com/ekhodzitsky/phostt): Zipformer-vi RNN-T, int8, ~75MB,
trained on ~70k hours of Vietnamese. This replaces `vietnamese-stt-server`
(PhoWhisper + faster-whisper) and keeps its **API unchanged**: same endpoints, same
request and response shapes, same default port (8123). Existing clients only need to
point at the new host.

## Why not phostt itself?

phostt is a Rust server. Its PyPI wheels are macOS-only, and its Python binding has no
streaming. So this server runs **the same ONNX bundle** (same pinned release and
checksum as `phostt download`) through [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx),
the project phostt's engine is ported from. Its wheels cover Windows and Linux, so
`uv sync` is the whole install: no Rust toolchain and no Docker.

Two deliberate differences from phostt's defaults:

- **Beam search** (`modified_beam_search`, 8 paths) instead of greedy decoding. It costs
  about 40% more CPU but recovers words that greedy drops on short, fast clips.
- **Silence padding** around each clip. Without it, the first word is often dropped.

## Run

Prerequisite: [uv](https://docs.astral.sh/uv/). ffmpeg comes from the `imageio-ffmpeg`
wheel, so nothing else needs to be installed on Windows or Linux.

```bash
uv sync
uv run src/download_model.py     # optional: the server downloads the model on first start
uv run src/main.py               # http://0.0.0.0:8123
uv run src/main.py --port 9000
```

Then open `http://localhost:8123/static/index.html` (test page with mic) or `/docs`.

**HTTPS (browser mic from another machine):** browsers only allow the microphone on
`https://` or `localhost`.

```bash
uv run src/make_cert.py          # self-signed cert.pem/key.pem for this host's names/IPs
uv run src/main.py --ssl-certfile cert.pem --ssl-keyfile key.pem
```

## API

- `POST /transcribe` takes a multipart file upload (`file`) and returns `{"text": "..."}`.
  It accepts any format ffmpeg decodes (WAV, MP3, browser WebM/Opus, M4A, …).
- `WS /ws/stream` gives a live preview. Send raw PCM16LE mono 16kHz binary frames. You
  receive `{"text": "..."}` messages, each holding the whole preview so far, about once a
  second. Close the socket when done, then POST the recording to `/transcribe` for the
  final text.
- `GET /health` returns `{"status": "ok", "device": "cpu" | "cuda", "model": "..."}`.
  `model` is now the bundle name, not a PhoWhisper repo id.

Silence or noise returns `""`. A Silero VAD gate handles this, because the model on its
own answers non-speech with "ừ".

**Output differences clients may notice:** the model produces no punctuation.
PhoWhisper sometimes ended with a `.`. The text is lowercased to match PhoWhisper's
style; set `TEXT_CASE=upper` for the model's raw uppercase.

## Loanwords (hotwords.txt)

The model knows almost no English, so a word like "offline" comes out as
Vietnamese-sounding guesses ("op len"). List the loanwords you need in
[hotwords.txt](hotwords.txt) and restart the server:

```
Zalo                            # boosted during decoding
offline = op len, oplank, oflin # boosted, plus these model outputs replaced with it
offline :3.0                    # optional per-word boost (default HOTWORDS_SCORE)
```

- **Boosting** makes the model spell the word out when the audio is close enough. In
  testing it fixed "Zalo" on its own, with no change on Vietnamese test clips.
- **Aliases** cover words the model hears too differently to spell, like "offline".
  To find them, transcribe a few real recordings that contain the word and copy what
  the model writes.
- The output uses the casing written in the file ("Zalo"). Boosting only works with
  `modified_beam_search`; aliases always apply.
- Keep boosts moderate: at a boost of 4 the model started repeating words
  ("zalo zalo").

## Configuration (env vars)

| Env var | Default | Description |
|-|-|-|
| `HOST` / `PORT` | `0.0.0.0` / `8123` | Bind address (also `--host`/`--port`) |
| `SSL_CERTFILE` / `SSL_KEYFILE` | blank | Enable HTTPS (also `--ssl-certfile`/`--ssl-keyfile`) |
| `MODEL_DIR` | `models/` | Model directory; a phostt CLI dir (`~/.phostt/models`) works too, plus `silero_vad.onnx` |
| `NUM_THREADS` | `min(4, cpus)` | ONNX Runtime threads per inference |
| `PROVIDER` | `cpu` | `cuda` needs sherpa-onnx's CUDA build; falls back to CPU if it fails to load |
| `DECODING_METHOD` | `modified_beam_search` | Or `greedy_search` (phostt's choice, faster) |
| `MAX_ACTIVE_PATHS` | `8` | Beam width for `modified_beam_search` |
| `VAD_THRESHOLD` | `0.3` | Silero speech threshold; Silero's own default of 0.5 missed quiet speech in testing |
| `HOTWORDS_FILE` | `hotwords.txt` | Loanword list (see above); missing or empty disables it |
| `HOTWORDS_SCORE` | `2.0` | Default boost per hotword |
| `TEXT_CASE` | `lower` | `lower`, or `upper`/`none` for the model's raw uppercase |
| `FFMPEG_BIN` | bundled | Use a specific ffmpeg instead of the imageio-ffmpeg one |
| `STREAM_UPDATE_SECONDS` | `1.0` | `/ws/stream`: minimum new audio before the preview reruns |
| `STREAM_WINDOW_SECONDS` | `10.0` | `/ws/stream`: window length before its text is committed |

## Performance

Measured on this dev machine (CPU only, 4 threads), beam search:

- 33s of audio in ~0.5s (≈60x real time); greedy decoding takes ~0.4s.
- A short clip over HTTP returns in ~0.3s. Twelve concurrent requests finish in ~0.3s.
- No GPU is needed.
