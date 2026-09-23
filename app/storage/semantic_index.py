"""Semantic index for vector-based similarity search on note embeddings.

Stores and retrieves embedding vectors in SQLite via the note_embeddings table.
Provides cosine-similarity search for semantic deduplication.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.llm.embedding import EmbeddingService
from app.storage.database import DatabaseBackend

logger = logging.getLogger(__name__)


class SemanticIndex:
    """Vector index backed by SQLite note_embeddings table.

    For small-to-medium knowledge bases (< 10 000 notes) this loads all
    embeddings for an instance into memory and computes cosine similarity
    naively.  No external vector DB or numpy dependency required.
    """

    def __init__(self, db: DatabaseBackend, embedding_service: EmbeddingService) -> None:
        self._db = db
        self._embedding = embedding_service

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_note(
        self,
        instance_id: str,
        file_path: str,
        title: str,
        summary: str,
        concepts: list[str],
    ) -> bool:
        """Embed the note metadata and store the vector.

        Returns ``True`` when the embedding was successfully stored,
        ``False`` when embedding failed (graceful degradation).
        """
        embed_text = self._build_embed_text(title, summary, concepts)
        vector = self._embedding.embed_text(embed_text)
        if not vector:
            logger.warning(
                "Failed to generate embedding for %s/%s, skipping",
                instance_id,
                file_path,
            )
            return False

        embedding_blob = self._vector_to_blob(vector)
        now = datetime.now(timezone.utc).isoformat()
        model_name = self._embedding._model  # noqa: SLF001 – internal access is acceptable here

        # Upsert: replace if (instance_id, file_path) already exists
        self._db.execute(
            """INSERT INTO note_embeddings
                   (instance_id, file_path, embedding_model, embedding, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(instance_id, file_path) DO UPDATE SET
                   embedding_model = excluded.embedding_model,
                   embedding = excluded.embedding,
                   updated_at = excluded.updated_at""",
            (instance_id, file_path, model_name, embedding_blob, now, now),
        )
        return True

    def find_similar(
        self,
        instance_id: str,
        query_text: str,
        *,
        top_k: int = 5,
        threshold: float = 0.8,
    ) -> list[dict[str, Any]]:
        """Find notes most similar to *query_text* within an instance.

        Loads every embedding for the instance, computes cosine similarity
        in pure Python, and returns the ``top_k`` results above ``threshold``.
        Each result dict contains: file_path, score, title, type.
        """
        query_vector = self._embedding.embed_text(query_text)
        if not query_vector:
            logger.warning("Failed to embed query text, returning empty results")
            return []

        # Load all embeddings for this instance
        rows = self._db.execute(
            """SELECT ne.file_path, ne.embedding
               FROM note_embeddings ne
               WHERE ne.instance_id = ?""",
            (instance_id,),
        )
        if not rows:
            return []

        # Compute similarities
        scored: list[dict[str, Any]] = []
        for row in rows:
            vec = self._blob_to_vector(row["embedding"])
            if not vec:
                continue
            sim = EmbeddingService.cosine_similarity(query_vector, vec)
            if sim >= threshold:
                scored.append({
                    "file_path": row["file_path"],
                    "score": round(sim, 6),
                })

        if not scored:
            return []

        # Sort descending by score and take top_k
        scored.sort(key=lambda r: r["score"], reverse=True)
        top_results = scored[:top_k]

        # Enrich with title and type from the notes table
        paths = [r["file_path"] for r in top_results]
        if paths:
            placeholders = ",".join("?" * len(paths))
            notes_rows = self._db.execute(
                f"""SELECT file_path, title, type
                    FROM notes
                    WHERE instance_id = ? AND file_path IN ({placeholders})""",
                [instance_id, *paths],
            )
            notes_map: dict[str, dict[str, Any]] = {
                nr["file_path"]: nr for nr in notes_rows
            }
            for result in top_results:
                note_info = notes_map.get(result["file_path"], {})
                result["title"] = note_info.get("title", "")
                result["type"] = note_info.get("type", "")

        return top_results

    def remove_note(self, instance_id: str, file_path: str) -> bool:
        """Delete a single note embedding. Returns True if a row was deleted."""
        rows = self._db.execute(
            "SELECT id FROM note_embeddings WHERE instance_id = ? AND file_path = ?",
            (instance_id, file_path),
        )
        if not rows:
            return False
        self._db.execute(
            "DELETE FROM note_embeddings WHERE instance_id = ? AND file_path = ?",
            (instance_id, file_path),
        )
        return True

    def rebuild(self, instance_id: str) -> int:
        """Rebuild the in-memory index from SQLite for the given instance.

        This simply reloads embeddings from the database.  In this
        implementation the "index" IS the database, so rebuild is a no-op
        that returns the count of stored embeddings.

        Returns the number of embeddings available for the instance.
        """
        rows = self._db.execute(
            "SELECT COUNT(*) AS cnt FROM note_embeddings WHERE instance_id = ?",
            (instance_id,),
        )
        return rows[0]["cnt"] if rows else 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_embed_text(title: str, summary: str, concepts: list[str]) -> str:
        """Construct the text to be embedded from note metadata.

        Format: ``"{title}\\n{summary}\\n{concept1, concept2, ...}"``
        """
        concept_str = ", ".join(concepts) if concepts else ""
        parts = [title, summary, concept_str]
        return "\n".join(parts)

    @staticmethod
    def _vector_to_blob(vector: list[float]) -> bytes:
        """Serialize a float vector to JSON bytes for SQLite BLOB storage."""
        return json.dumps(vector).encode("utf-8")

    @staticmethod
    def _blob_to_vector(blob: bytes | str) -> list[float]:
        """Deserialize a JSON blob back to a float vector."""
        if isinstance(blob, str):
            blob = blob.encode("utf-8")
        try:
            data = json.loads(blob)
            if isinstance(data, list):
                return [float(x) for x in data]
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("Failed to decode embedding blob: %s", exc)
        return []
