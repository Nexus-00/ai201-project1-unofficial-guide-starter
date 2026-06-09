"""
retrieve_data.py — Query the Seattle corpus in ChromaDB.

Pipeline stage 4 (Retrieval) from planning.md. Given a query string, embeds it
with the same model used at index time and prints the top-k most similar chunks
(top-k = 3, per planning.md) with their source and similarity.

    python retrieve_data.py "Rent prices in Seattle"

Run embed_data.py first to build the collection.
"""

import sys

import chromadb
from chromadb.utils import embedding_functions

from embed_data import CHROMA_PATH, COLLECTION_NAME, EMBEDDING_MODEL

# Force UTF-8 so printing chunks with emoji / non-Latin text doesn't crash on
# the Windows console's default cp1252 codec.
sys.stdout.reconfigure(encoding="utf-8")

TOP_K = 3  # planning.md "Retrieval Approach"


def retrieve(query: str, k: int = TOP_K) -> None:
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )
    try:
        collection = client.get_collection(
            name=COLLECTION_NAME, embedding_function=embed_fn
        )
    except Exception:
        print(f"Collection '{COLLECTION_NAME}' not found at {CHROMA_PATH}/. "
              f"Run embed_data.py first.")
        return

    results = collection.query(query_texts=[query], n_results=k)
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]

    print(f'Query: "{query}"')
    print(f"Top {len(docs)} chunks (cosine distance; lower = more similar)\n")
    for rank, (doc, meta, dist) in enumerate(zip(docs, metas, dists), 1):
        print("=" * 70)
        print(f"[{rank}] source: {meta.get('source')}  "
              f"chunk #{meta.get('chunk_index')}  "
              f"similarity: {1 - dist:.3f}  (distance {dist:.3f})")
        print("-" * 70)
        print(doc)
        print()


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python retrieve_data.py "your query here"')
        sys.exit(1)
    query = " ".join(sys.argv[1:]).strip()
    retrieve(query)


if __name__ == "__main__":
    main()
