1. python retrieve_docs.py   # ingest: scrape city-data/wikivoyage + browser sources into documents/
2. python clean_docs.py       # normalize + convert the JSON dumps (reddit, derby, facebook, zillow)
3. python print_chunks.py     # (optional) preview chunk counts + 5 random chunks to sanity-check
4. python embed_data.py       # chunk + embed everything into ChromaDB
5. python retrieve_data.py "your query"   # retrieve top-k chunks for a query