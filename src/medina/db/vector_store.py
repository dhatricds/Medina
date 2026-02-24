"""ChromaDB vector store for semantic search across corrections and QA."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_client = None
_CHROMA_PATH: Path | None = None

# Collection names
CORRECTIONS_COLLECTION = "corrections"
QA_INTERACTIONS_COLLECTION = "qa_interactions"
COVE_FINDINGS_COLLECTION = "cove_findings"


def _get_chroma_path() -> Path:
    """Return the configured ChromaDB path, falling back to default."""
    if _CHROMA_PATH is not None:
        return _CHROMA_PATH
    return Path(__file__).resolve().parents[3] / "output" / "chroma_db"


def init_vector_store(chroma_path: str | Path | None = None) -> None:
    """Initialize the ChromaDB persistent client and create collections."""
    global _client, _CHROMA_PATH
    try:
        import chromadb
    except ImportError:
        logger.warning(
            "chromadb not installed — vector search disabled. "
            "Install with: pip install chromadb"
        )
        return

    if chroma_path is not None:
        _CHROMA_PATH = Path(chroma_path)
    path = _get_chroma_path()
    path.mkdir(parents=True, exist_ok=True)

    _client = chromadb.PersistentClient(path=str(path))

    # Create or get collections
    _client.get_or_create_collection(
        name=CORRECTIONS_COLLECTION,
        metadata={"description": "Correction text embeddings for similarity search"},
    )
    _client.get_or_create_collection(
        name=QA_INTERACTIONS_COLLECTION,
        metadata={"description": "Q&A pairs from chat for knowledge retrieval"},
    )
    _client.get_or_create_collection(
        name=COVE_FINDINGS_COLLECTION,
        metadata={"description": "Verification findings for pattern detection"},
    )
    logger.info("ChromaDB initialized at %s with 3 collections", path)


def get_collection(name: str):
    """Get a ChromaDB collection by name. Returns None if not initialized."""
    if _client is None:
        return None
    try:
        return _client.get_collection(name)
    except Exception:
        logger.warning("Collection %s not found", name)
        return None


def add_document(
    collection_name: str,
    doc_id: str,
    text: str,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Add a document to a ChromaDB collection."""
    coll = get_collection(collection_name)
    if coll is None:
        return False
    try:
        coll.upsert(
            ids=[doc_id],
            documents=[text],
            metadatas=[metadata or {}],
        )
        return True
    except Exception as e:
        logger.warning("Failed to add document to %s: %s", collection_name, e)
        return False


def query_similar(
    collection_name: str,
    query_text: str,
    n_results: int = 5,
    where: dict | None = None,
) -> list[dict[str, Any]]:
    """Query for similar documents in a collection.

    Returns list of dicts with keys: id, document, metadata, distance.
    """
    coll = get_collection(collection_name)
    if coll is None:
        return []
    try:
        kwargs: dict[str, Any] = {
            "query_texts": [query_text],
            "n_results": n_results,
        }
        if where:
            kwargs["where"] = where
        results = coll.query(**kwargs)

        docs: list[dict[str, Any]] = []
        if results and results.get("ids"):
            for i, doc_id in enumerate(results["ids"][0]):
                docs.append({
                    "id": doc_id,
                    "document": (results.get("documents") or [[]])[0][i]
                    if results.get("documents")
                    else "",
                    "metadata": (results.get("metadatas") or [[]])[0][i]
                    if results.get("metadatas")
                    else {},
                    "distance": (results.get("distances") or [[]])[0][i]
                    if results.get("distances")
                    else 0.0,
                })
        return docs
    except Exception as e:
        logger.warning("Query failed on %s: %s", collection_name, e)
        return []


def close_vector_store() -> None:
    """Clean up the ChromaDB client."""
    global _client
    _client = None
    logger.info("ChromaDB client closed")
