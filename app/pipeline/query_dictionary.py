"""Instance-scoped query dictionary cache and longest-match parsing."""

from dataclasses import dataclass, field
import json
import re
import threading
from typing import Any

from app.storage.database import DatabaseBackend


@dataclass
class DictionaryTerm:
    term: str
    layer: str
    source: str
    canonical: str
    relation_type: str | None = None
    file_path: str | None = None
    frequency: int = 1

    @property
    def match_key(self) -> str:
        return _match_key(self.term)


@dataclass
class InstanceDictionary:
    instance_id: str
    terms: dict[str, DictionaryTerm] = field(default_factory=dict)
    alias_map: dict[str, set[str]] = field(default_factory=dict)
    synonym_map: dict[str, set[str]] = field(default_factory=dict)
    note_alias_map: dict[str, set[str]] = field(default_factory=dict)
    cooccurrence_map: dict[str, set[str]] = field(default_factory=dict)

    @property
    def sorted_terms(self) -> list[DictionaryTerm]:
        return sorted(self.terms.values(), key=lambda item: len(item.match_key), reverse=True)


_cache: dict[str, InstanceDictionary] = {}
_cache_lock = threading.Lock()
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
_TOKEN_SPLIT_RE = re.compile(r"[\s,.;:!?，。；：！？、（）()\[\]{}<>《》\"'“”‘’]+")


def invalidate_query_caches(instance_id: str | None = None) -> None:
    """Invalidate query dictionary/expansion caches."""
    with _cache_lock:
        if instance_id is None:
            _cache.clear()
        else:
            _cache.pop(instance_id, None)


def get_instance_dictionary(instance_id: str, db: DatabaseBackend) -> InstanceDictionary:
    with _cache_lock:
        cached = _cache.get(instance_id)
    if cached is not None:
        return cached

    built = build_instance_dictionary(instance_id, db)
    with _cache_lock:
        _cache[instance_id] = built
    return built


def refresh_instance_dictionary(instance_id: str, db: DatabaseBackend) -> InstanceDictionary:
    built = build_instance_dictionary(instance_id, db)
    with _cache_lock:
        _cache[instance_id] = built
    return built


def build_instance_dictionary(instance_id: str, db: DatabaseBackend) -> InstanceDictionary:
    dictionary = InstanceDictionary(instance_id=instance_id)
    _load_lexicon_terms(dictionary, db)
    _load_facet_terms(dictionary, db)
    _load_note_terms(dictionary, db)
    _load_cooccurrence(dictionary, db)
    _load_ontology_terms(dictionary, db)
    return dictionary


def parse_with_dictionaries(
    normalized_query: str,
    instance_ids: list[str],
    db: DatabaseBackend,
) -> dict[str, Any]:
    dictionaries = [get_instance_dictionary(instance_id, db) for instance_id in instance_ids]
    sorted_terms = sorted(
        (
            (dictionary, item)
            for dictionary in dictionaries
            for item in dictionary.terms.values()
        ),
        key=lambda pair: len(pair[1].match_key),
        reverse=True,
    )
    exact_terms: list[str] = []
    phrase_terms: list[str] = []
    matches: list[dict[str, Any]] = []
    consumed: list[tuple[int, int]] = []
    query_key = _match_key(normalized_query)

    for dictionary, item in sorted_terms:
        for start, end in _find_term_spans(query_key, item.match_key):
            if _overlaps(consumed, start, end):
                continue
            consumed.append((start, end))
            target = exact_terms if item.layer == "exact" else phrase_terms
            _append_unique(target, item.canonical)
            matches.append({
                "term": item.term,
                "canonical": item.canonical,
                "layer": item.layer,
                "source": item.source,
                "instance_id": dictionary.instance_id,
                "file_path": item.file_path,
            })

    residual_text = _mask_spans(query_key, consumed)
    residual_tokens = _residual_tokens(residual_text)
    for token in residual_tokens:
        _append_unique(phrase_terms, token)

    return {
        "exact_candidates": exact_terms,
        "phrase_candidates": phrase_terms,
        "dictionary_matches": matches,
        "residual_tokens": residual_tokens,
    }


def expand_candidates(
    exact_candidates: list[str],
    phrase_candidates: list[str],
    instance_ids: list[str],
    db: DatabaseBackend,
) -> dict[str, Any]:
    dictionaries = [get_instance_dictionary(instance_id, db) for instance_id in instance_ids]
    seeds = [*exact_candidates, *phrase_candidates]
    expanded: list[str] = []
    sources: list[dict[str, str]] = []
    high_precision = {_term_key(term) for term in seeds}

    for dictionary in dictionaries:
        for seed in seeds:
            seed_key = _term_key(seed)
            for source_name, mapping in (
                ("instance_alias", dictionary.alias_map),
                ("instance_synonym", dictionary.synonym_map),
                ("note_alias", dictionary.note_alias_map),
                ("cooccurrence", dictionary.cooccurrence_map),
            ):
                for value in mapping.get(seed_key, set()):
                    if _term_key(value) in high_precision:
                        continue
                    if _append_unique(expanded, value):
                        sources.append({
                            "term": value,
                            "source": source_name,
                            "seed": seed,
                            "instance_id": dictionary.instance_id,
                        })

    return {"expanded_candidates": expanded, "expansion_sources": sources}


def _load_lexicon_terms(dictionary: InstanceDictionary, db: DatabaseBackend) -> None:
    rows = db.execute(
        """SELECT relation_type, canonical_term, variant_terms_json
           FROM instance_search_lexicon
           WHERE instance_id = ? AND enabled = 1""",
        (dictionary.instance_id,),
    )
    for row in rows:
        canonical = str(row["canonical_term"]).strip()
        relation_type = row["relation_type"]
        variants = _load_json_list(row.get("variant_terms_json"))
        layer = "exact" if relation_type == "alias" else "expanded"
        _add_term(
            dictionary,
            term=canonical,
            canonical=canonical,
            layer="exact" if relation_type == "alias" else "phrase",
            source=f"lexicon_{relation_type}",
            relation_type=relation_type,
        )
        values = {canonical, *variants}
        mapping = dictionary.alias_map if relation_type == "alias" else dictionary.synonym_map
        for left in values:
            for right in values:
                if _term_key(left) != _term_key(right):
                    mapping.setdefault(_term_key(left), set()).add(right)
            if relation_type == "alias":
                _add_term(
                    dictionary,
                    term=left,
                    canonical=canonical,
                    layer=layer,
                    source="lexicon_alias",
                    relation_type=relation_type,
                )


def _load_facet_terms(dictionary: InstanceDictionary, db: DatabaseBackend) -> None:
    rows = db.execute(
        """SELECT file_path, field, value, COUNT(*) AS cnt
           FROM note_facets
           WHERE instance_id = ?
             AND field IN ('aliases', 'concepts', 'domain', 'kind')
           GROUP BY file_path, field, value""",
        (dictionary.instance_id,),
    )
    concepts_by_file: dict[str, set[str]] = {}
    aliases_by_file: dict[str, set[str]] = {}
    for row in rows:
        value = str(row["value"] or "").strip()
        if not value:
            continue
        field_name = row["field"]
        layer = "exact" if field_name in {"aliases", "concepts"} else "phrase"
        _add_term(
            dictionary,
            term=value,
            canonical=value,
            layer=layer,
            source=f"facet_{field_name}",
            file_path=row["file_path"],
            frequency=int(row.get("cnt") or 1),
        )
        if field_name == "concepts":
            concepts_by_file.setdefault(row["file_path"], set()).add(value)
        if field_name == "aliases":
            aliases_by_file.setdefault(row["file_path"], set()).add(value)

    for file_path, aliases in aliases_by_file.items():
        concepts = concepts_by_file.get(file_path, set())
        for alias in aliases:
            for concept in concepts:
                dictionary.note_alias_map.setdefault(_term_key(alias), set()).add(concept)
                dictionary.note_alias_map.setdefault(_term_key(concept), set()).add(alias)


def _load_note_terms(dictionary: InstanceDictionary, db: DatabaseBackend) -> None:
    rows = db.execute(
        "SELECT file_path, title FROM notes WHERE instance_id = ?",
        (dictionary.instance_id,),
    )
    for row in rows:
        title = str(row["title"] or "").strip()
        if not title:
            continue
        _add_term(
            dictionary,
            term=title,
            canonical=title,
            layer="phrase",
            source="note_title",
            file_path=row["file_path"],
        )


def _load_cooccurrence(dictionary: InstanceDictionary, db: DatabaseBackend) -> None:
    rows = db.execute(
        """SELECT source_path, target_path
           FROM relations
           WHERE instance_id = ? AND rel_type = 'concept_overlap'""",
        (dictionary.instance_id,),
    )
    if not rows:
        return
    paths = sorted({row["source_path"] for row in rows} | {row["target_path"] for row in rows})
    if not paths:
        return
    placeholders = ",".join("?" * len(paths))
    facet_rows = db.execute(
        f"""SELECT file_path, value
            FROM note_facets
            WHERE instance_id = ?
              AND field = 'concepts'
              AND file_path IN ({placeholders})""",
        [dictionary.instance_id, *paths],
    )
    concepts_by_path: dict[str, set[str]] = {}
    for row in facet_rows:
        concepts_by_path.setdefault(row["file_path"], set()).add(row["value"])
    for row in rows:
        left = concepts_by_path.get(row["source_path"], set())
        right = concepts_by_path.get(row["target_path"], set())
        for seed in left:
            dictionary.cooccurrence_map.setdefault(_term_key(seed), set()).update(right - {seed})
        for seed in right:
            dictionary.cooccurrence_map.setdefault(_term_key(seed), set()).update(left - {seed})


def _load_ontology_terms(dictionary: InstanceDictionary, db: DatabaseBackend) -> None:
    rows = db.execute(
        """SELECT id, name
           FROM ontology_entities
           WHERE instance_id = ? AND status IN ('active', 'candidate') AND searchable = 1""",
        (dictionary.instance_id,),
    )
    for row in rows:
        name = str(row["name"] or "").strip()
        if not name:
            continue
        _add_term(
            dictionary,
            term=name,
            canonical=name,
            layer="exact",
            source="ontology_entity",
        )

    alias_rows = db.execute(
        """SELECT a.entity_id, a.alias_text
           FROM ontology_entity_aliases a
           JOIN ontology_entities e
             ON a.instance_id = e.instance_id AND a.entity_id = e.id
           WHERE a.instance_id = ?
             AND e.status IN ('active', 'candidate') AND e.searchable = 1""",
        (dictionary.instance_id,),
    )
    for row in alias_rows:
        alias = str(row["alias_text"] or "").strip()
        if not alias:
            continue
        _add_term(
            dictionary,
            term=alias,
            canonical=alias,
            layer="exact",
            source="ontology_entity",
        )
        # Build alias_map: alias <-> entity name for expansion
        entity_rows = db.execute(
            "SELECT name FROM ontology_entities WHERE instance_id = ? AND id = ?",
            (dictionary.instance_id, row["entity_id"]),
        )
        if entity_rows:
            entity_name = str(entity_rows[0]["name"] or "").strip()
            if entity_name:
                dictionary.alias_map.setdefault(_term_key(alias), set()).add(entity_name)
                dictionary.alias_map.setdefault(_term_key(entity_name), set()).add(alias)

    type_rows = db.execute(
        """SELECT name
           FROM ontology_types
           WHERE instance_id = ? AND status IN ('active', 'candidate') AND searchable = 1""",
        (dictionary.instance_id,),
    )
    for row in type_rows:
        name = str(row["name"] or "").strip()
        if not name:
            continue
        _add_term(
            dictionary,
            term=name,
            canonical=name,
            layer="phrase",
            source="ontology_type",
        )


def _add_term(
    dictionary: InstanceDictionary,
    *,
    term: str,
    canonical: str,
    layer: str,
    source: str,
    relation_type: str | None = None,
    file_path: str | None = None,
    frequency: int = 1,
) -> None:
    text = str(term or "").strip()
    if len(text) < 2:
        return
    key = _match_key(text)
    existing = dictionary.terms.get(key)
    item = DictionaryTerm(
        term=text,
        layer=layer,
        source=source,
        canonical=canonical,
        relation_type=relation_type,
        file_path=file_path,
        frequency=frequency,
    )
    if existing is None or _term_priority(item) > _term_priority(existing):
        dictionary.terms[key] = item


def _term_priority(item: DictionaryTerm) -> int:
    source_weight = {
        "lexicon_alias": 50,
        "ontology_entity": 45,
        "facet_concepts": 40,
        "facet_aliases": 35,
        "note_title": 25,
        "lexicon_synonym": 20,
        "ontology_type": 15,
        "facet_domain": 10,
        "facet_kind": 10,
    }
    return source_weight.get(item.source, 0)


def _find_term_spans(text: str, term: str) -> list[tuple[int, int]]:
    if not text or not term:
        return []
    matches: list[tuple[int, int]] = []
    start = 0
    text_key = text.casefold()
    term_key = term.casefold()
    while True:
        index = text_key.find(term_key, start)
        if index < 0:
            break
        matches.append((index, index + len(term)))
        start = index + len(term)
    return matches


def _overlaps(spans: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(start < span_end and end > span_start for span_start, span_end in spans)


def _mask_spans(text: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return text
    chars = list(text)
    for start, end in spans:
        for index in range(start, min(end, len(chars))):
            chars[index] = " "
    return "".join(chars)


def _append_unique(values: list[str], value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    key = _term_key(text)
    if key in {_term_key(item) for item in values}:
        return False
    values.append(text)
    return True


def _load_json_list(value: Any) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item or "").strip()]


def _term_key(value: str) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _match_key(value: str) -> str:
    text = str(value or "").strip().casefold()
    text = re.sub(r"[^\w\s一-鿿\-()]", " ", text)
    text = re.sub(r"\(\)+$", "", text)
    return " ".join(text.split())


def _residual_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for fragment in _TOKEN_SPLIT_RE.split(text):
        fragment = fragment.strip()
        if not fragment:
            continue
        for token in _segment_residual(fragment):
            if len(token.strip()) >= 2:
                tokens.append(token.strip())
    return tokens


def _segment_residual(text: str) -> list[str]:
    try:
        import pkuseg  # type: ignore
    except Exception:
        return _fallback_segment_residual(text)
    try:
        segmenter = pkuseg.pkuseg()
        return [token for token in segmenter.cut(text) if token.strip()]
    except Exception:
        return _fallback_segment_residual(text)


def _fallback_segment_residual(text: str) -> list[str]:
    """Segment residual fragments without external CJK tokenizers."""
    normalized = str(text or "").strip()
    if not normalized:
        return []

    # Keep the residual fragment intact when we do not have a real tokenizer.
    # The fallback path should stay conservative and avoid inventing noisy
    # 2-char windows that pollute phrase candidates.
    if _CJK_RUN_RE.search(normalized):
        return [normalized]
    return [normalized]
