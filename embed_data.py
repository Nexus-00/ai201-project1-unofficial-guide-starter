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

Run clean_docs.py first so the input text is normalized.
"""

import chromadb
from chromadb.utils import embedding_functions

# Reuse the exact chunking used by the preview so the index matches what you saw.
from print_chunks import (
    DOCUMENTS_DIR,
    chunk_sentences,
    split_sentences,
)

# Keep these aligned with planning.md "Retrieval Approach".
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
CHROMA_PATH = "chroma_db"
COLLECTION_NAME = "seattle_guide"
BATCH_SIZE = 256


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

    print(f"\nDone. {collection.count():,} chunks stored in '{COLLECTION_NAME}'.")


if __name__ == "__main__":
    main()
