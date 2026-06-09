"""
print_chunks.py — Sentence-aware chunking preview for the Seattle RAG corpus.

Loads every documents/<source>/content.txt, splits it into sentence-aware
chunks (per planning.md: 10 sentences per chunk, 3 sentences of overlap), then
reports the total chunk count and prints five random chunks so you can eyeball
chunk quality before embedding.

Run clean_docs.py first so the input is normalized.

    python print_chunks.py
"""

import random
import re
import sys
from pathlib import Path

DOCUMENTS_DIR = Path("documents")

# Chunking parameters — keep in sync with planning.md "Chunking Strategy".
CHUNK_SENTENCES = 10
OVERLAP_SENTENCES = 3

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Split text into sentences, treating each cleaned line as >= 1 sentence.

    Listing records (e.g. Zillow rows) have no terminal punctuation, so they
    become one sentence each; prose lines split on . ! ? boundaries.
    """
    sentences: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for part in SENTENCE_SPLIT_RE.split(line):
            part = part.strip()
            if part:
                sentences.append(part)
    return sentences


def chunk_sentences(
    sentences: list[str],
    size: int = CHUNK_SENTENCES,
    overlap: int = OVERLAP_SENTENCES,
) -> list[str]:
    """Group sentences into overlapping windows of `size` with `overlap` carryover."""
    if not sentences:
        return []
    step = size - overlap
    chunks: list[str] = []
    i = 0
    n = len(sentences)
    while i < n:
        window = sentences[i:i + size]
        chunks.append(" ".join(window))
        if i + size >= n:
            break
        i += step
    return chunks


def load_chunks() -> list[dict]:
    """Return [{'source': ..., 'text': ...}] for every chunk in the corpus."""
    all_chunks: list[dict] = []
    for content_file in sorted(DOCUMENTS_DIR.glob("*/content.txt")):
        source = content_file.parent.name
        text = content_file.read_text(encoding="utf-8")
        sentences = split_sentences(text)
        for chunk in chunk_sentences(sentences):
            all_chunks.append({"source": source, "text": chunk})
    return all_chunks


def main():
    # The corpus contains emoji / non-Latin text; force UTF-8 so printing chunks
    # doesn't crash on the Windows console's default cp1252 codec. Done here (not
    # at import) so importing this module has no side effects on the importer.
    sys.stdout.reconfigure(encoding="utf-8")

    chunks = load_chunks()

    # Per-source breakdown.
    by_source: dict[str, int] = {}
    for c in chunks:
        by_source[c["source"]] = by_source.get(c["source"], 0) + 1

    print(f"Chunking: {CHUNK_SENTENCES} sentences/chunk, "
          f"{OVERLAP_SENTENCES} overlap\n")
    print("Chunks per source:")
    for source, count in sorted(by_source.items()):
        print(f"  {source:<18} {count:>4}")
    print(f"\nTotal chunks: {len(chunks)}\n")

    sample = random.sample(chunks, min(5, len(chunks)))
    print("=" * 70)
    print("FIVE RANDOM CHUNKS")
    print("=" * 70)
    for i, c in enumerate(sample, 1):
        print(f"\n[{i}] source: {c['source']}")
        print("-" * 70)
        print(c["text"])


if __name__ == "__main__":
    main()
