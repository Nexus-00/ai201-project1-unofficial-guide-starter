# The Unofficial Guide — Project 1

> **How to use this template:**
> Complete each section *after* you've built and tested the corresponding part of your system.
> Do not write placeholder text — if a section isn't done yet, leave it blank and come back.
> Every section below is required for submission. One-liners will not receive full credit.

---

## Domain

Activities in Seattle. Depending on where you look, there can be many different subjective experiences can vary depending on what website you're looking, and moving into Seattle has its own complications. In addition, there may be surprises that don't show up in the news or official websites; one has to rely on the wisdom of the community in combination with official sources to get the whole picture.

---

## Document Sources

| # | Source | Description | URL or location |
|---|--------|-------------|-----------------|
| 1 | Zillow | A popular service for buying and renting apartments. | https://www.zillow.com/seattle-wa/ |
| 2 | Derby Boutique Apartments | Rent studio apartments near South Lake Union. | https://www.liveatderbyslu.com/ |
| 3 | Apartments | Another service for finding properties to rent. | https://www.apartments.com/seattle-wa/ |
| 4 | Craigslist | General website for buyers/renters to connect directly with sellers/landlords | https://seattle.craigslist.org/search/apa |
| 5 | Reddit | Seattle Housing for Redditors, of varying quality. | https://www.reddit.com/r/seattlehousing/ |
| 6 | Reddit | Pros and Cons of Living in Seattle | https://www.reddit.com/r/SeattleWA/comments/188kibg/the_pros_and_cons_of_living_in_seattle/ |
| 7 | Wikivoyage | Travel guide covering Seattle districts, getting around, and things to do | https://en.wikivoyage.org/wiki/Seattle |
| 8 | Facebook | Facebook group about Seattle | https://www.facebook.com/groups/150655681825/ |
| 9 | City-Data.com | Discussions of Neighborhoods, rents, and quality of life. | https://www.city-data.com/city/Seattle-Washington.html | 
| 10 | Teamblind | Public forum popular with tech workers with threads about Seattle | https://www.teamblind.com/ |

---

## Chunking Strategy

**Chunk size:** 10 sentences per chunk

**Overlap:** 3 sentences

**Reasoning:** Since the sources vary greatly in format (forum posts, listings, articles), sentence-aware chunking keeps semantic units intact rather than cutting mid-sentence. A 3-sentence overlap ensures context at chunk boundaries isn't lost — larger than the original 50-character overlap because sentences carry more meaning than raw character counts.

**Actual corpus size:** This configuration produces **1139 chunks** across all 10 sources (wikivoyage 232, city_data 203, reddit_housing 165, reddit_pros_cons 158, zillow 98, craigslist 85, facebook 85, apartments_com 50, teamblind 43, derby_slu 20). This is above the original ~200 target, but with top-k=3 a larger index just improves coverage rather than hurting retrieval. The cleaning step (`clean_docs.py`) drops City-Data's HMDA mortgage/loan-statistics tables, which were number-only rows irrelevant to apartment-living questions (city_data fell from 282 to 203 chunks). Cleaning iterates to a fixed point, so the corpus is deterministic — one `clean_docs.py` run produces the same output as many. Zillow comes from a structured listings export (`seattle_listings.json`) rather than scraped HTML — each of its 51 listings expands into specs, walkability, nearby schools, and a full description, so it now contributes 98 chunks instead of the 12 the bot-walled scrape yielded. The thinnest source, derby_slu, has only one property's worth of unit listings.

---

## Embedding Model

**Embedding model:** all-MiniLM-L6-v2

**Production tradeoff reflection:** For real users, I would choose the default embedding model as I think it's generally useful for those looking to live in Seattle for work or school. Multilingual support isn't something I'm considering since that introduces complexity for querying and the storage and document requirements to support additional languages would explode.

---

## Grounded Generation

**System prompt grounding instruction:**

System Prompt:
```
You answer questions about living in Seattle using ONLY the context chunks provided in the user message. Do not use any outside knowledge. If the context does not contain enough information to answer, reply with exactly: I don't know.

Every answer must cite its source as a markdown link in this exact format: 
'"your answer" [SourceName](url)' — using only the SourceName and url shown for the chunk(s) you used. Do NOT cite by chunk number (e.g. [1] or the bracket-number style); always write the full [SourceName](url) link.
```

Explanation:
This simple prompt steers the model into thinking through its response and only providing an answer if it can be found from at least one source. The sources are formatted specifically by name then the URL. Based on the user's query, only the top 3 most relevant chunks are shown to the model, and it is up to that to decide which sources to use.



**How source attribution is surfaced in the response:**
Source attribution shows up in both the answer, as well as a separate box indicating what sources the model pulled information from.

---

## Evaluation Report

| # | Question | Expected answer | System response (summarized) | Retrieval quality | Response accuracy |
|---|----------|-----------------|------------------------------|-------------------|-------------------|
| 1 | What is one university in Seattle? | University of Washington | University of Washington [Wikivoyage](https://en.wikivoyage.org/wiki/Seattle) | Relevant | Accurate |
| 2 | What are some of the biggest tech companies in Seattle? | Microsoft, Google, Amazon, Meta | Amazon, Microsoft, Starbucks, T‑Mobile, Nintendo of America, and several other tech‑based firms are among the biggest companies headquartered in Seattle. [Wikivoyage (https://en.wikivoyage.org/wiki/Seattle)] | Relevant | Accurate |
| 3 | How many people live in Seattle? | About at least 750,000. | 780,995 people live in Seattle. [City-Data](https://www.city-data.com/city/Seattle-Washington.html) | Relevant | Accurate |
| 4 | Is Seattle a walkable city? | Yes | Yes, Seattle is walkable, with many walkable neighborhoods and good public transit. [Reddit](https://www.reddit.com/r/SeattleWA/comments/188kibg/the_pros_and_cons_of_living_in_seattle/) [Wikivoyage](https://en.wikivoyage.org/wiki/Seattle) | Relevant | Accurate |
| 5 | What is Seattle's 2nd most famous building? | Smith Tower | I don't know | Partially relevant | Inaccurate |

**Retrieval quality:** Relevant / Partially relevant / Off-target  
**Response accuracy:** Accurate / Partially accurate / Inaccurate

---

## Failure Case Analysis

**Question that failed:** What is Seattle's 2nd most famous building?

**What the system returned:** I don't know / The Columbia Center

**Root cause (tied to a specific pipeline stage):** The question is vague and the model in non-deterministic, even if the retrieval from ChromaDB is consistent. This problem occured at the Embedding + Vector stage, where while the most likely relevant chunks are passed to the models, the embeddings database can't give the correct chunks to the model because the correct answer isn't in ChromaDB.

**What you would change to fix it:** I think there isn't a specific 2nd most famous building in Seattle, so I'll have to add that extra bit of information in the embedding database so the model can better answer that question, particularly a ranked list of famous landmarks in Seattle.

---

## Spec Reflection

**One way the spec helped you during implementation:**
The spec helped me steer Claude Code to use specific libraries and methods while creating the implementaiton. Planning.md also helped me figure out what the flow of my chatbot with grounding looked like without going in blind; that is to say there was a specific step-by-step process that I understood what was happening in the code, and how the current implementation worked.

**One way your implementation diverged from the spec, and why:**
One way my implementation diverged from the spec was changing the way I obtained my source data to split them into logical chunks before feeding them into ChromaDB. The problem was that for many websites, they have anti-bot mechanisms that made scraping data difficult. I initally wanted to automate the sourcing of the data via libraries like BeautifulSoup and Reddit wrappers. However, I had to resort to using methods like apify and manually copying-and-pasting the information to get around such blocks. I also used OpenAI's API point towards Groq's endpoints instead of using Groq's own library as the OpenAPI library allows a significantly greater access to other LLMs, compared to Groq's limited selections.


---

## AI Usage

**Instance 1**

- *What I gave the AI:* I asked Claude Code to create specific python files using information from planning.md to process the information one step at a time.
- *What it produced:* For each step, I asked Claude Code to produce retrieve_docs.py, clean_docs.py, print_chunks.py, embed_data.py, and retrieve_data.py.
- *What I changed or overrode:* After produces these files, I also asked it to produce prompt_me.py, which is the core file that does LLM inference with grounding. I asked the model to modify the previous files to create a fingerprint file "corpus.sha256" which is based on the info from the source files and all chunk's IDs and text. If the source information changes, attempting to run the inference file will cause the embeddings database to be updated with new information. This solves subtle issues of wrong or outdated information retrieval because the database is out of date, or the source documents have changed.

**Instance 2**

- *What I gave the AI:* I asked Claude Code to automatically scrape data from different data sources and save them to the documents folder, formatted as structured .txt documents. Such sources include Zillow, Reddit, and Facebook.
- *What it produced:* Claude Code was able to run code that scraped the data from the other seven ources, but it ended up running into issues with Zillow, Reddit, and Facebook. For Reddit, it got blocked, for Zillow, it ran into a JS-based challenge of which it could not get through, and Facebook groups are locked behind a login wall.
- *What I changed or overrode:* I used Claude Cowork to create an extension to automatically scrape data from Reddit and Zillow. I then used Apify to grab posts and comments from the Seattle Facebook group and asked Claude Code to format its findings from json to txt.
