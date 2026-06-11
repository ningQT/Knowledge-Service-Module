"""Query parsing - extract concept candidates and a lightweight domain hint."""

import re

from app.pipeline.query_dictionary import parse_with_dictionaries
from app.pipeline.query_expander import expand_query_candidates
from app.storage.database import DatabaseBackend


NOISE_WORDS = [
    "what",
    "is",
    "a",
    "an",
    "the",
    "define",
    "definition",
    "compare",
    "difference",
    "list",
    "overview",
    "summary",
    "relation",
    "source",
    "reference",
    "什么是",
    "定义",
    "原理",
    "区别",
    "差异",
    "对比",
    "比较",
    "有哪些",
    "哪些",
    "列出",
    "总览",
    "概览",
    "来源",
    "来自",
    "哪篇",
    "资料",
    "关系",
    "关联",
    "相关",
]

TOPIC_SCAN_STOPWORDS = (
    "都有哪些人",
    "都有哪些",
    "有哪些人",
    "有哪些",
    "都有谁",
    "都有哪",
    "有谁",
    "人物",
)


def parse_query(
    normalized_query: str,
    instance_ids: list[str],
    intent_type: str,
    db: DatabaseBackend,
) -> dict:
    """Extract structured query context."""
    cleaned_query = _remove_noise(normalized_query)
    parsed = parse_with_dictionaries(cleaned_query, instance_ids, db)
    exact_candidates = parsed["exact_candidates"]
    phrase_candidates = parsed["phrase_candidates"]
    if intent_type == "topic_scan":
        phrase_candidates = _dedupe([
            *phrase_candidates,
            *_extract_topic_scan_terms(normalized_query, cleaned_query),
        ])
    expansion = expand_query_candidates(exact_candidates, phrase_candidates, instance_ids, db)
    expanded_candidates = expansion["expanded_candidates"]
    candidates = _dedupe([*exact_candidates, *phrase_candidates])
    domain_hint = suggest_domain(candidates, instance_ids, db)
    matched_facets = match_facets(candidates, instance_ids, db)

    return {
        "concept_candidates": candidates,
        "exact_candidates": exact_candidates,
        "phrase_candidates": phrase_candidates,
        "expanded_candidates": expanded_candidates,
        "domain_hint": domain_hint,
        "matched_facets": matched_facets,
        "intent_type": intent_type,
        "instance_ids": instance_ids,
        "dictionary_matches": parsed["dictionary_matches"],
        "expansion_sources": expansion["expansion_sources"],
        "residual_tokens": parsed["residual_tokens"],
    }


def _remove_noise(query: str) -> str:
    query_text = query
    for word in NOISE_WORDS:
        if word.isascii() and word.replace("_", "").isalpha():
            query_text = re.sub(rf"\b{re.escape(word)}\b", " ", query_text, flags=re.IGNORECASE)
        else:
            query_text = query_text.replace(word, " ")
    return query_text


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _extract_topic_scan_terms(raw_query: str, cleaned_query: str) -> list[str]:
    """Extract deterministic CJK phrase candidates for enumerative queries."""
    base = str(cleaned_query or raw_query or "").strip()
    if not base:
        return []

    value = base
    for word in TOPIC_SCAN_STOPWORDS:
        value = value.replace(word, " ")
    value = re.sub(r"\s+", " ", value).strip()

    candidates: list[str] = []
    cjk_runs = re.findall(r"[\u4e00-\u9fff]{2,}", value)
    for run in cjk_runs:
        if len(run) <= 3:
            candidates.append(run)
            continue
        for index in range(0, len(run) - 1):
            piece = run[index:index + 2]
            if len(piece) >= 2:
                candidates.append(piece)
    return _dedupe(candidates)


def suggest_domain(
    candidates: list[str],
    instance_ids: list[str],
    db: DatabaseBackend,
) -> str | None:
    """Suggest a domain by searching indexed titles, frontmatter, and facets."""
    if not candidates or not instance_ids:
        return None

    placeholders = ",".join("?" * len(instance_ids))
    for candidate in candidates:
        try:
            rows = db.execute(
                f"""SELECT nf.value AS domain, COUNT(*) as cnt
                    FROM note_facets nf
                    JOIN notes n
                      ON n.instance_id = nf.instance_id
                     AND n.file_path = nf.file_path
                    WHERE nf.instance_id IN ({placeholders})
                      AND nf.field = 'domain'
                      AND (
                        n.title LIKE ?
                        OR n.frontmatter LIKE ?
                        OR EXISTS (
                            SELECT 1 FROM note_facets needle
                            WHERE needle.instance_id = nf.instance_id
                              AND needle.file_path = nf.file_path
                              AND needle.value LIKE ?
                        )
                      )
                    GROUP BY nf.value
                    ORDER BY cnt DESC
                    LIMIT 1""",
                [*instance_ids, f"%{candidate}%", f"%{candidate}%", f"%{candidate}%"],
            )
            if rows:
                return rows[0]["domain"]
        except Exception:
            pass

        try:
            rows = db.execute(
                f"""SELECT domain, COUNT(*) as cnt
                    FROM notes
                    WHERE instance_id IN ({placeholders})
                      AND (title LIKE ? OR frontmatter LIKE ?)
                      AND domain IS NOT NULL
                    GROUP BY domain
                    ORDER BY cnt DESC
                    LIMIT 1""",
                [*instance_ids, f"%{candidate}%", f"%{candidate}%"],
            )
            if rows:
                return rows[0]["domain"]
        except Exception:
            continue
    return None


def match_facets(
    candidates: list[str],
    instance_ids: list[str],
    db: DatabaseBackend,
) -> list[dict]:
    """Find exact alias/concept/domain/kind facet matches for query candidates."""
    if not candidates or not instance_ids:
        return []

    placeholders = ",".join("?" * len(instance_ids))
    matches: list[dict] = []
    for candidate in candidates:
        try:
            rows = db.execute(
                f"""SELECT file_path, field, value
                    FROM note_facets
                    WHERE instance_id IN ({placeholders})
                      AND field IN ('aliases', 'concepts', 'domain', 'kind')
                      AND lower(value) = ?
                    ORDER BY field, file_path
                    LIMIT 10""",
                [*instance_ids, candidate.lower()],
            )
        except Exception:
            rows = []
        for row in rows:
            matches.append({
                "candidate": candidate,
                "field": row["field"],
                "value": row["value"],
                "file_path": row["file_path"],
            })
    return matches
