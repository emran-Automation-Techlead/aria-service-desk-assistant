"""ChromaDB-backed retrieval: chunks each Confluence article and embeds it,
so the decision/synthesis prompts see only the few most relevant chunks
instead of every article's full text — the actual RAG pattern, not a
"stuff the whole KB in the prompt" shortcut.

Runs fully local via Chroma's persistent client under data/chroma/, using
OpenAI embeddings (text-embedding-3-small). Re-indexing is incremental:
publishing a new article (the self-healing KB path) embeds just that one
article rather than rebuilding the whole collection.
"""
import re
from pathlib import Path
from typing import List
import chromadb
from chromadb.utils import embedding_functions
from models import KBArticle, Team
from config import settings

_PERSIST_DIR = str(Path(__file__).parent / "data" / "chroma")

_client = chromadb.PersistentClient(path=_PERSIST_DIR)
_embedder = embedding_functions.OpenAIEmbeddingFunction(
    api_key=settings.openai_api_key, model_name="text-embedding-3-small"
)
_collection = _client.get_or_create_collection(name="aria_kb", embedding_function=_embedder)

_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 80

_indexed_teams: set = set()


def _chunk_text(text: str) -> List[str]:
    """Paragraph/numbered-step aware chunker: splits on blank lines and
    numbered list items first, then packs those pieces into ~_CHUNK_SIZE
    windows with a small overlap so a step near a chunk boundary isn't
    orphaned from its neighbors."""
    pieces = [p.strip() for p in re.split(r"\n\s*\n|(?=\n\d+\.\s)", text) if p.strip()]
    if not pieces:
        return [text.strip()] if text.strip() else []

    chunks: List[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) + 1 > _CHUNK_SIZE:
            chunks.append(current)
            current = current[-_CHUNK_OVERLAP:] + "\n" + piece
        else:
            current = f"{current}\n{piece}" if current else piece
    if current:
        chunks.append(current)
    return chunks


def _chunk_article(article: KBArticle) -> List[dict]:
    chunks = _chunk_text(article.body)
    return [
        {
            "id": f"{article.id}::{i}",
            "text": f"{article.title}\n{chunk}",
            "metadata": {
                "team": article.team.value,
                "article_id": article.id,
                "title": article.title,
                "doc_type": article.doc_type,
                "url": article.url,
            },
        }
        for i, chunk in enumerate(chunks)
    ]


def index_article(article: KBArticle) -> None:
    """(Re-)index one article: replaces any chunks it already has."""
    existing = _collection.get(where={"article_id": article.id})
    if existing and existing.get("ids"):
        _collection.delete(ids=existing["ids"])

    docs = _chunk_article(article)
    if not docs:
        return
    _collection.add(
        ids=[d["id"] for d in docs],
        documents=[d["text"] for d in docs],
        metadatas=[d["metadata"] for d in docs],
    )


def ensure_team_indexed(team: Team, articles: List[KBArticle]) -> None:
    """Index a team's articles once per process; publish_article() calls
    index_article() directly afterwards so new articles show up immediately
    without waiting for a full re-index."""
    if team.value in _indexed_teams:
        return
    for article in articles:
        index_article(article)
    _indexed_teams.add(team.value)


def search(team: Team, query: str, k: int = 6) -> List[dict]:
    if _collection.count() == 0:
        return []
    result = _collection.query(query_texts=[query], n_results=k, where={"team": team.value})
    hits = []
    ids = result.get("ids") or [[]]
    if not ids[0]:
        return hits
    for i, chunk_id in enumerate(ids[0]):
        meta = result["metadatas"][0][i]
        hits.append({
            "chunk_id": chunk_id,
            "text": result["documents"][0][i],
            "distance": result["distances"][0][i] if result.get("distances") else None,
            "article_id": meta["article_id"],
            "title": meta["title"],
            "doc_type": meta["doc_type"],
            "url": meta["url"],
        })
    return hits


def best_articles_context(team: Team, query: str, k: int = 6, max_articles: int = 3) -> str:
    """Group the top chunk hits by article and format the best few for the
    decision prompt — retrieval-scoped context, not the whole KB."""
    hits = search(team, query, k=k)
    grouped: dict = {}
    order: List[str] = []
    for h in hits:
        if h["article_id"] not in grouped:
            grouped[h["article_id"]] = []
            order.append(h["article_id"])
        grouped[h["article_id"]].append(h)

    blocks = []
    for article_id in order[:max_articles]:
        chunks = grouped[article_id]
        title, doc_type = chunks[0]["title"], chunks[0]["doc_type"]
        text = "\n...\n".join(c["text"] for c in chunks)
        blocks.append(f"[{article_id}] ({doc_type}) {title}\n{text}")
    return "\n\n".join(blocks)
