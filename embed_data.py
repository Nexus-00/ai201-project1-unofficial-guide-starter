"""
embed_data.py — Embed the Seattle corpus into ChromaDB.

Pipeline stage 3 (Embedding + Vector Store) from planning.md:

  Document Ingestion -> Chunking -> [Embedding + Vector Store] -> Retrieval -> Generation

Reads every documents/<source>/content.txt, chunks it with the same
sentence-aware logic as print_chunks.py (10 sentences/chunk, 3 overlap per
planning.md), embeds each chunk with all-MiniLM-L6-v2, and stores it in a
persistent ChromaDB collection with metadata (source + chunk index).

The collection is rebuilt from scratch on every run so re-embedding never
produces duplicates.

    python embed_data.py

Run clean_docs.py first so the input text is normalized. (ensure_fresh() does
this automatically when the corpus has changed.)
"""

import hashlib
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

# Raw inputs that clean_docs.py consumes — folded into the fingerprint so that
# editing a source file (even without re-cleaning) is detected as a change.
from clean_docs import (
    DERBY_PAGES_FILE,
    FACEBOOK_JSON,
    REDDIT_JSON,
    ZILLOW_JSON,
)
# Reuse the exact chunking used by the preview so the index matches what you saw.
from print_chunks import (
    CHUNK_SENTENCES,
    DOCUMENTS_DIR,
    OVERLAP_SENTENCES,
    chunk_sentences,
    split_sentences,
)

# Keep these aligned with planning.md "Retrieval Approach".
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
CHROMA_PATH = "chroma_db"
COLLECTION_NAME = "seattle_guide"
BATCH_SIZE = 256

# Fingerprint of the corpus that produced the current index, written next to it.
HASH_PATH = Path(CHROMA_PATH) / "corpus.sha256"


def load_chunks() -> list[dict]:
    """Return [{'id', 'text', 'source', 'chunk_index'}] for the whole corpus."""
    chunks: list[dict] = []
    for content_file in sorted(DOCUMENTS_DIR.glob("*/content.txt")):
        source = content_file.parent.name
        text = content_file.read_text(encoding="utf-8")
        sentences = split_sentences(text)
        for i, chunk in enumerate(chunk_sentences(sentences)):
            chunks.append(
                {
                    "id": f"{source}-{i}",
                    "text": chunk,
                    "source": source,
                    "chunk_index": i,
                }
            )
    return chunks


def _raw_input_paths() -> list[Path]:
    """Existing raw source files that feed clean_docs.py."""
    paths = [Path(name) for name in REDDIT_JSON]
    paths += [DERBY_PAGES_FILE, FACEBOOK_JSON, ZILLOW_JSON]
    return [p for p in paths if p.exists()]


def corpus_fingerprint(chunks: list[dict] | None = None) -> str:
    """SHA-256 over everything that determines the index contents.

    Folds in the embedding model, the chunking parameters, the raw input files,
    and every chunk's id + text. If any of these change, the digest changes, so
    a stale index is detectable without re-embedding.
    """
    if chunks is None:
        chunks = load_chunks()
    h = hashlib.sha256()
    h.update(EMBEDDING_MODEL.encode())
    h.update(f"chunk={CHUNK_SENTENCES};overlap={OVERLAP_SENTENCES}".encode())
    for path in sorted(_raw_input_paths(), key=lambda p: p.name):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    for c in chunks:
        h.update(c["id"].encode())
        h.update(c["text"].encode("utf-8"))
    return h.hexdigest()


def _read_stored_fingerprint() -> str | None:
    return HASH_PATH.read_text(encoding="utf-8").strip() if HASH_PATH.exists() else None


def index_is_fresh() -> bool:
    """True if a collection exists and its fingerprint matches the current corpus."""
    if not Path(CHROMA_PATH).exists():
        return False
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    if COLLECTION_NAME not in [c.name for c in client.list_collections()]:
        return False
    stored = _read_stored_fingerprint()
    return stored is not None and stored == corpus_fingerprint()


def ensure_fresh(verbose: bool = True) -> bool:
    """If the index is stale/missing, re-run preprocessing + embedding.

    Returns True if a rebuild happened. Cheap (file reads + chunking, no model
    load) when nothing changed, so it's safe to call before every query.
    """
    if index_is_fresh():
        return False
    if verbose:
        print("[freshness] corpus changed or index missing — "
              "re-running clean_docs + embed_data ...")
    import clean_docs  # local import: only needed on the rebuild path

    clean_docs.main()
    main()
    return True


def main() -> None:
    chunks = load_chunks()
    if not chunks:
        print("No chunks found. Run clean_docs.py and check the documents/ folder.")
        return

    print(f"Loaded {len(chunks):,} chunks from {DOCUMENTS_DIR}/")

    client = chromadb.PersistentClient(path=CHROMA_PATH)

    # Same embedding function the query side will use, so embeds and queries
    # live in one vector space.
    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )

    # Rebuild the collection so re-running never double-inserts.
    if COLLECTION_NAME in [c.name for c in client.list_collections()]:
        client.delete_collection(COLLECTION_NAME)
    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},  # cosine similarity, per planning.md
    )

    print(f"Embedding with {EMBEDDING_MODEL} -> collection '{COLLECTION_NAME}' "
          f"at {CHROMA_PATH}/ ...")
    for start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[start:start + BATCH_SIZE]
        collection.add(
            ids=[c["id"] for c in batch],
            documents=[c["text"] for c in batch],
            metadatas=[
                {"source": c["source"], "chunk_index": c["chunk_index"]}
                for c in batch
            ],
        )
        print(f"  embedded {min(start + BATCH_SIZE, len(chunks)):,}/{len(chunks):,}")

    # Record the fingerprint of exactly what we just embedded, so later runs can
    # tell whether the index is still current.
    HASH_PATH.parent.mkdir(parents=True, exist_ok=True)
    HASH_PATH.write_text(corpus_fingerprint(chunks), encoding="utf-8")

    print(f"\nDone. {collection.count():,} chunks stored in '{COLLECTION_NAME}'.")


if __name__ == "__main__":
    main()
