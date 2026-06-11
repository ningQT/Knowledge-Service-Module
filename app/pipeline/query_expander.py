"""Query expansion facade for phase 7 search."""

from app.pipeline.query_dictionary import expand_candidates
from app.storage.database import DatabaseBackend


def expand_query_candidates(
    exact_candidates: list[str],
    phrase_candidates: list[str],
    instance_ids: list[str],
    db: DatabaseBackend,
) -> dict:
    """Expand parsed candidates without promoting them to high-precision layers."""
    return expand_candidates(exact_candidates, phrase_candidates, instance_ids, db)
