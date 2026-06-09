"""
prompt_me.py — Full RAG query: retrieve + generate.

Pipeline stage 5 (Generation) from planning.md. Given a query, it:
  1. retrieves the top-k most similar chunks from ChromaDB (stage 4), then
  2. asks Groq's OpenAI gpt-oss-20b model (reasoning enabled) to answer using
     ONLY those chunks, citing its source, or to say it doesn't know.

    python prompt_me.py "What universities are in Seattle?"

Uses the official OpenAI SDK pointed at Groq's OpenAI-compatible endpoint, so
the model is OpenAI's open-weight gpt-oss-20b served by Groq.

Run embed_data.py first to build the collection, and set GROQ_API_KEY in .env.
"""

import os
import sys

import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv
from openai import OpenAI

from embed_data import CHROMA_PATH, COLLECTION_NAME, EMBEDDING_MODEL, ensure_fresh

# Force UTF-8 so printing answers/chunks with emoji / non-Latin text doesn't
# crash on the Windows console's default cp1252 codec.
sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

TOP_K = 3  # planning.md "Retrieval Approach"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"  # OpenAI-compatible Groq endpoint
GROQ_MODEL = "openai/gpt-oss-20b"  # OpenAI OSS 20B, served by Groq
REASONING_EFFORT = "medium"  # gpt-oss "thinking" — low | medium | high

# Map each source folder (the metadata stored at embed time) to a human label
# and URL, so the model can cite sources in the required markdown-link format.
# URLs come from the Documents table in planning.md.
SOURCE_META = {
    "zillow": ("Zillow", "https://www.zillow.com/seattle-wa/"),
    "derby_slu": ("Derby SLU", "https://www.liveatderbyslu.com/"),
    "apartments_com": ("Apartments.com", "https://www.apartments.com/seattle-wa/"),
    "craigslist": ("Craigslist", "https://seattle.craigslist.org/search/apa"),
    "reddit_housing": ("Reddit", "https://www.reddit.com/r/seattlehousing/"),
    "reddit_pros_cons": (
        "Reddit",
        "https://www.reddit.com/r/SeattleWA/comments/188kibg/"
        "the_pros_and_cons_of_living_in_seattle/",
    ),
    "wikivoyage": ("Wikivoyage", "https://en.wikivoyage.org/wiki/Seattle"),
    "facebook": ("Facebook", "https://www.facebook.com/groups/150655681825/"),
    "city_data": ("City-Data", "https://www.city-data.com/city/Seattle-Washington.html"),
    "teamblind": ("Teamblind", "https://www.teamblind.com/"),
}

SYSTEM_PROMPT = (
    "You answer questions about living in Seattle using ONLY the context chunks "
    "provided in the user message. Do not use any outside knowledge. If the "
    "context does not contain enough information to answer, reply with exactly: "
    "I don't know.\n"
    "Every answer must cite its source as a markdown link in this exact format: "
    '"your answer" [SourceName](url) — using only the SourceName and url shown '
    "for the chunk(s) you used. Do NOT cite by chunk number (e.g. [1] or the "
    "bracket-number style); always write the full [SourceName](url) link."
)


def retrieve(query: str, k: int = TOP_K) -> list[dict]:
    """Return the top-k chunks as [{'source', 'text', 'distance'}]."""
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )
    collection = client.get_collection(
        name=COLLECTION_NAME, embedding_function=embed_fn
    )
    res = collection.query(query_texts=[query], n_results=k)
    return [
        {"source": m.get("source"), "text": d, "distance": dist}
        for d, m, dist in zip(
            res["documents"][0], res["metadatas"][0], res["distances"][0]
        )
    ]


def build_context(chunks: list[dict]) -> str:
    """Render retrieved chunks with their citable source label + URL."""
    blocks = []
    for i, c in enumerate(chunks, 1):
        label, url = SOURCE_META.get(c["source"], (c["source"], ""))
        blocks.append(f"[{i}] Source: {label} ({url})\n{c['text']}")
    return "\n\n".join(blocks)


def source_links(chunks: list[dict]) -> list[str]:
    """Deduped 'Label (url)' strings for the chunks that were retrieved."""
    seen: list[str] = []
    for c in chunks:
        label, url = SOURCE_META.get(c["source"], (c["source"], ""))
        entry = f"{label} ({url})" if url else label
        if entry not in seen:
            seen.append(entry)
    return seen


def ask(question: str, k: int = TOP_K) -> dict:
    """End-to-end RAG: retrieve -> generate. Returns answer, sources, reasoning.

    Raises RuntimeError with a readable message if the key is missing or no
    chunks are found, so callers (CLI and GUI) can surface it the same way.
    """
    question = question.strip()
    if not question:
        return {"answer": "Please enter a question.", "sources": [], "reasoning": ""}

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key.startswith("gsk_your"):
        raise RuntimeError(
            "Set GROQ_API_KEY in .env (free key at https://console.groq.com)."
        )

    # Rebuild the index first if the corpus changed since it was last embedded.
    ensure_fresh()

    chunks = retrieve(question, k)
    if not chunks:
        raise RuntimeError("No chunks retrieved. Run embed_data.py first.")

    user_message = (
        f"Context chunks:\n\n{build_context(chunks)}\n\nQuestion: {question}"
    )

    # OpenAI SDK aimed at Groq's OpenAI-compatible endpoint.
    client = OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)
    completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0,
        reasoning_effort=REASONING_EFFORT,  # enable gpt-oss thinking
        extra_body={"reasoning_format": "parsed"},  # Groq: split reasoning out
    )
    message = completion.choices[0].message

    # Groq returns the thinking trace in a non-standard "reasoning" field, which
    # the OpenAI SDK exposes via model_extra rather than a typed attribute.
    reasoning = getattr(message, "reasoning", None)
    if reasoning is None and getattr(message, "model_extra", None):
        reasoning = message.model_extra.get("reasoning")

    return {
        "answer": (message.content or "").strip(),
        "sources": source_links(chunks),
        "reasoning": (reasoning or "").strip(),
    }


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python prompt_me.py "your question here"')
        sys.exit(1)
    query = " ".join(sys.argv[1:]).strip()

    try:
        result = ask(query)
    except RuntimeError as e:
        print(e)
        sys.exit(1)

    print(f'Query: "{query}"\n')
    if result["reasoning"]:
        print("--- Thinking ---")
        print(result["reasoning"])
        print()
    print("--- Answer ---")
    print(result["answer"])
    print("\n--- Retrieved from ---")
    for s in result["sources"]:
        print(f"• {s}")


if __name__ == "__main__":
    main()
