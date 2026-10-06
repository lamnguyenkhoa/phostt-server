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
        import sentencepiece as spm

        sp = spm.SentencePieceProcessor(model_file=str(model_dir / "bpe.model"))
        with open(dest, "w", encoding="utf-8") as f:
            for i in range(sp.vocab_size()):
                f.write(f"{sp.id_to_piece(i)}\t{sp.get_score(i)}\n")
    return dest


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
