"""Hotword boosting and alias fixes for loanwords, configured in hotwords.txt.

The model's vocabulary is Vietnamese syllables plus single letters, so English words
like "offline" come out as Vietnamese-sounding guesses ("op len"). Two fixes, both
driven by the same file:

- Hotwords: sherpa-onnx boosts listed words during beam search, so the model spells
  them out (O F F LI NE) when the audio is close enough. Works well when the model's
  guess is already near the word ("Zalo"), not when it is far off.
- Aliases: whatever the model writes instead (after the "="), replaced with the word.

File format, one entry per line ("#" starts a comment):

    zalo
    offline :3.0 = op len, oflin    # optional per-word boost, then aliases
"""
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

BPE_VOCAB_FILE = "bpe.vocab"
_LINE = re.compile(r"^(?P<word>[^:=]+?)\s*(?::\s*(?P<score>[\d.]+))?\s*(?:=(?P<aliases>.*))?$")


@dataclass
class Hotword:
    word: str
    score: "float | None" = None
    aliases: "list[str]" = field(default_factory=list)


def parse(path: Path) -> "list[Hotword]":
    entries = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = _LINE.match(line)
        if not m:
            raise ValueError(f"{path}:{lineno}: can't parse {raw!r}")
        aliases = [a.strip() for a in (m["aliases"] or "").split(",") if a.strip()]
        score = float(m["score"]) if m["score"] else None
        entries.append(Hotword(" ".join(m["word"].split()), score, aliases))
    return entries


def write_sherpa_file(entries: "list[Hotword]", dest: Path) -> None:
    """sherpa-onnx's format: one uppercase word/phrase per line (the model's tokens are
    uppercase), optionally followed by " :score"."""
    lines = [e.word.upper() + (f" :{e.score}" if e.score is not None else "") for e in entries]
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_bpe_vocab(model_dir: Path) -> Path:
    """sherpa-onnx encodes hotwords with a "piece score" vocab exported from bpe.model."""
    dest = model_dir / BPE_VOCAB_FILE
    if not dest.is_file():
        pieces = _read_sentencepiece_model((model_dir / "bpe.model").read_bytes())
        with open(dest, "w", encoding="utf-8") as f:
            for piece, score in pieces:
                f.write(f"{piece}\t{score}\n")
    return dest


def _read_varint(buf: bytes, pos: int) -> "tuple[int, int]":
    result = shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if b < 0x80:
            return result, pos
        shift += 7


def _iter_fields(buf: bytes):
    """Yield (field_number, wire_type, value) for each field of a protobuf message."""
    pos = 0
    while pos < len(buf):
        key, pos = _read_varint(buf, pos)
        field_no, wire_type = key >> 3, key & 7
        if wire_type == 0:
            value, pos = _read_varint(buf, pos)
        elif wire_type == 1:
            value, pos = buf[pos:pos + 8], pos + 8
        elif wire_type == 2:
            length, pos = _read_varint(buf, pos)
            value, pos = buf[pos:pos + length], pos + length
        elif wire_type == 5:
            value, pos = buf[pos:pos + 4], pos + 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire_type}")
        yield field_no, wire_type, value


def _read_sentencepiece_model(data: bytes) -> "list[tuple[str, float]]":
    """(piece, score) pairs from a SentencePiece ModelProto, in id order.

    Parsed directly rather than through the sentencepiece package: its native module
    crashes on import on some Windows machines (older Visual C++ runtime). ModelProto
    field 1 is the repeated SentencePiece message: field 1 = piece, field 2 = score.
    """
    pieces = []
    for field_no, wire_type, value in _iter_fields(data):
        if field_no != 1 or wire_type != 2:
            continue
        piece, score = "", 0.0
        for f_no, w_type, v in _iter_fields(value):
            if f_no == 1 and w_type == 2:
                piece = v.decode("utf-8")
            elif f_no == 2 and w_type == 5:
                score = struct.unpack("<f", v)[0]
        pieces.append((piece, score))
    return pieces


def build_replacer(entries: "list[Hotword]"):
    """Text -> text, replacing each alias (and the word itself, so the output takes the
    casing written in the file) with the word, matching whole words case-insensitively."""
    rules = []
    for e in entries:
        for alias in [*e.aliases, e.word]:
            pattern = r"\s+".join(re.escape(part) for part in alias.split())
            rules.append((re.compile(rf"(?<!\w){pattern}(?!\w)", re.IGNORECASE), e.word))
    # Longest aliases first, so "op len mode" wins over "op len".
    rules.sort(key=lambda rule: -len(rule[0].pattern))

    def replace(text: str) -> str:
        for regex, word in rules:
            text = regex.sub(word, text)
        return text

    return replace
