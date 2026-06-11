"""Relation builder - extracts 5 types of knowledge relations.

Reference: 检索流程完整设计 v2 Section 10.7
"""

import json
import logging
import re
from pathlib import Path

import yaml

from app.schema.metadata_normalizer import (
    clean_wikilink_target,
    extract_wikilinks_from_value,
    normalize_metadata,
    normalize_metadata_values,
)
from app.storage.path_utils import normalize_vault_path

logger = logging.getLogger(__name__)

# Wikilink regex: [[target]], [[target#heading]], or [[target|alias]]
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]")

# Cache for resolved wikilink paths: {vault_path: {note_name: relative_path}}
_wikilink_cache: dict[str, dict[str, str]] = {}

# Cache for concept→path mapping: {vault_path: {concept_lower: relative_path}}
_concept_cache: dict[str, dict[str, str]] = {}


def _strip_vault_prefix(rel_path: str, vault_path: str) -> str:
    """Strip the vault directory prefix from a data_dir-relative path.

    LocalStorageBackend.list_files() returns paths relative to its base_dir. When
    that base_dir is the global data directory, results include the vault folder
    name. When it is the vault itself, results are already vault-relative.
    """
    rel_path = normalize_vault_path(rel_path)
    vault_path = normalize_vault_path(vault_path).rstrip("/")

    vault_prefix = vault_path + "/"
    if rel_path.startswith(vault_prefix):
        return rel_path[len(vault_prefix):]

    vault_name = Path(vault_path).name
    if vault_name:
        vault_name_prefix = normalize_vault_path(vault_name) + "/"
        if rel_path.startswith(vault_name_prefix):
            return rel_path[len(vault_name_prefix):]

    return rel_path


def _build_wikilink_index(vault_path: str, storage) -> dict[str, str]:
    """Build an index mapping note names/stems to their relative file paths.

    The index is cached per vault_path to avoid repeated filesystem scans.
    Paths are stored as vault-relative (consistent with notes.file_path).
    """
    if vault_path in _wikilink_cache:
        return _wikilink_cache[vault_path]

    index: dict[str, str] = {}
    try:
        all_files = storage.list_files(vault_path, "*.md")
        for rel_path in all_files:
            # Skip .obsidian
            if ".obsidian" in rel_path:
                continue
            rel_path = _strip_vault_prefix(normalize_vault_path(rel_path), vault_path)
            stem = Path(rel_path).stem
            index[stem] = rel_path
            # Also index by lowercase for case-insensitive matching
            index[stem.lower()] = rel_path
    except Exception as e:
        logger.warning("Failed to build wikilink index for %s: %s", vault_path, e)

    _wikilink_cache[vault_path] = index
    return index


def _build_concept_index(vault_path: str, storage) -> dict[str, str]:
    """Build an index mapping concept names (lowercase) to note file paths.

    Reads frontmatter of all notes to extract concepts. Cached per vault_path.
    Paths are stored as vault-relative (consistent with notes.file_path).
    """
    if vault_path in _concept_cache:
        return _concept_cache[vault_path]

    index: dict[str, str] = {}
    try:
        all_files = storage.list_files(vault_path, "*.md")
        for rel_path in all_files:
            rel_path = _strip_vault_prefix(normalize_vault_path(rel_path), vault_path)
            if ".obsidian" in rel_path:
                continue
            try:
                content = storage.read_file(str(Path(vault_path) / rel_path))
                # Quick frontmatter extraction without full parser
                if content.startswith("---"):
                    end = content.find("---", 3)
                    if end > 0:
                        fm_text = content[3:end]
                        try:
                            fm = yaml.safe_load(fm_text) or {}
                            concepts = normalize_metadata_values(fm.get("concepts", []))
                            for concept in concepts:
                                if concept:
                                    key = str(concept).lower()
                                    stem = Path(rel_path).stem.lower()
                                    if key not in index or stem == key:
                                        index[key] = rel_path
                        except Exception:
                            pass
            except Exception:
                continue
    except Exception as e:
        logger.warning("Failed to build concept index for %s: %s", vault_path, e)

    _concept_cache[vault_path] = index
    return index


def resolve_wikilink(target: str, vault_path: str, storage) -> str:
    """Resolve a wikilink target to its actual file path.

    Matching rules:
    1. Vault-relative file path match
    2. Exact filename stem match (case-sensitive)
    3. Case-insensitive filename stem match
    4. Concept name match (looks through note frontmatter concepts)

    Returns the vault-relative file path if found, otherwise returns empty string.
    """
    target = clean_wikilink_target(target)
    normalized_target = _strip_vault_prefix(normalize_vault_path(target), vault_path)
    index = _build_wikilink_index(vault_path, storage)

    if normalized_target in index.values():
        return normalized_target

    # Try exact match first
    if target in index:
        return index[target]

    # Try case-insensitive
    lower = target.lower()
    if lower in index:
        return index[lower]

    # Try concept-based matching
    if storage and vault_path:
        concept_index = _build_concept_index(vault_path, storage)
        if lower in concept_index:
            return concept_index[lower]

    # No match — log warning and return empty
    logger.debug("Wikilink '%s' could not be resolved to a file in vault '%s'", target, vault_path)
    return ""


def clear_wikilink_cache(vault_path: str | None = None) -> None:
    """Clear the wikilink resolution cache.

    Called after sync/reindex to ensure stale entries are removed.
    """
    if vault_path:
        _wikilink_cache.pop(vault_path, None)
        _concept_cache.pop(vault_path, None)
    else:
        _wikilink_cache.clear()
        _concept_cache.clear()


def extract_direct_links(
    content: str, source_path: str, vault_path: str = "", storage=None
) -> list[dict]:
    """Extract direct_link relations from [[wikilink]] in content."""
    relations = []
    for match in WIKILINK_RE.finditer(content):
        target = clean_wikilink_target(match.group(1))
        if target:
            target_path = resolve_wikilink(target, vault_path, storage) if storage and vault_path else target
            if target_path:
                relations.append({
                    "source_path": normalize_vault_path(source_path),
                    "target_path": normalize_vault_path(target_path),
                    "rel_type": "direct_link",
                })
    return relations


def extract_source_trace(
    frontmatter: dict,
    source_path: str,
    vault_path: str = "",
    storage=None,
) -> list[dict]:
    """Extract source_trace relations from card.sources → source."""
    relations = []
    normalized = normalize_metadata(frontmatter).frontmatter
    if normalized.get("graph_layer") == 2:  # Only for cards
        sources = normalized.get("sources", [])
        for src in sources:
            target_path = resolve_wikilink(src, vault_path, storage) if storage and vault_path else src
            if target_path:
                relations.append({
                    "source_path": normalize_vault_path(source_path),
                    "target_path": normalize_vault_path(target_path),
                    "rel_type": "source_trace",
                })
    return relations


def extract_extracted_from(
    frontmatter: dict, source_path: str, vault_path: str = "", storage=None
) -> list[dict]:
    """Extract extracted_from relations from source.extracted_cards → card."""
    relations = []
    normalized = normalize_metadata(frontmatter).frontmatter
    if normalized.get("graph_layer") == 1:  # Only for sources
        extracted_cards = normalize_metadata_values(frontmatter.get("extracted_cards", []))
        for card in extracted_cards:
            target_path = resolve_wikilink(card, vault_path, storage) if storage and vault_path else card
            if target_path:
                relations.append({
                    "source_path": normalize_vault_path(source_path),
                    "target_path": normalize_vault_path(target_path),
                    "rel_type": "extracted_from",
                })
    return relations


def extract_map_contains(
    content: str, frontmatter: dict, source_path: str, vault_path: str = "", storage=None
) -> list[dict]:
    """Extract map_contains relations from map content [[wikilinks]]."""
    relations = []
    normalized = normalize_metadata(frontmatter).frontmatter
    if normalized.get("graph_layer") == 3:  # Only for maps
        for match in WIKILINK_RE.finditer(content):
            target = clean_wikilink_target(match.group(1))
            if target:
                target_path = resolve_wikilink(target, vault_path, storage) if storage and vault_path else target
                if target_path:
                    relations.append({
                        "source_path": normalize_vault_path(source_path),
                        "target_path": normalize_vault_path(target_path),
                        "rel_type": "map_contains",
                    })
    return relations


def extract_link_references(
    content: str,
    frontmatter: dict,
    source_path: str,
    vault_path: str = "",
    storage=None,
    resolver=None,
) -> list[dict]:
    """Extract diagnosable link references without creating relation edges."""
    source_path = normalize_vault_path(source_path)
    references: list[dict] = []

    for match in WIKILINK_RE.finditer(content):
        target = clean_wikilink_target(match.group(1))
        if target:
            references.append(
                _build_link_reference(
                    source_path=source_path,
                    target_text=target,
                    link_kind="body_wikilink",
                    source_field="body",
                    vault_path=vault_path,
                    storage=storage,
                    resolver=resolver,
                )
            )

    for field_name, value in frontmatter.items():
        if field_name == "raw_frontmatter":
            continue
        for link in extract_wikilinks_from_value(value):
            references.append(
                _build_link_reference(
                    source_path=source_path,
                    target_text=link["target"],
                    link_kind="frontmatter_wikilink",
                    source_field=field_name,
                    vault_path=vault_path,
                    storage=storage,
                    resolver=resolver,
                )
            )

    return _dedupe_link_references(references)


def _build_link_reference(
    *,
    source_path: str,
    target_text: str,
    link_kind: str,
    source_field: str,
    vault_path: str = "",
    storage=None,
    resolver=None,
) -> dict:
    target = clean_wikilink_target(target_text)
    target_path = ""
    if resolver:
        target_path = resolver(target) or ""
    elif storage and vault_path:
        target_path = resolve_wikilink(target, vault_path, storage)
    return {
        "source_path": source_path,
        "target_text": target,
        "target_path": normalize_vault_path(target_path) if target_path else "",
        "link_kind": link_kind,
        "source_field": source_field,
        "resolved": bool(target_path),
    }


def _dedupe_link_references(references: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, str, str]] = set()
    unique: list[dict] = []
    for reference in references:
        key = (
            reference["source_path"],
            reference["target_text"].casefold(),
            reference["link_kind"],
            reference["source_field"],
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(reference)
    return unique


def extract_all_relations(
    content: str,
    frontmatter: dict,
    source_path: str,
    vault_path: str = "",
    storage=None,
) -> list[dict]:
    """Extract all relation types from a single note.

    Combines: direct_link, source_trace, extracted_from, map_contains.
    Note: concept_overlap is computed batch-wise during indexing, not here.
    """
    relations = []
    relations.extend(extract_direct_links(content, source_path, vault_path, storage))
    relations.extend(extract_source_trace(frontmatter, source_path, vault_path, storage))
    relations.extend(extract_extracted_from(frontmatter, source_path, vault_path, storage))
    relations.extend(extract_map_contains(content, frontmatter, source_path, vault_path, storage))

    # Deduplicate
    seen = set()
    unique = []
    for r in relations:
        key = (r["source_path"], r["target_path"], r["rel_type"])
        if key not in seen:
            seen.add(key)
            unique.append(r)

    return unique


def compute_concept_overlap_batch(
    notes: list[dict],
) -> list[dict]:
    """Compute concept_overlap relations batch-wise.

    Two notes share concept_overlap if they have at least 2 common concepts.
    Reference: 检索流程完整设计 v2 Section 10.7
    """
    # Build path -> concepts mapping
    node_concepts: dict[str, set[str]] = {}
    for note in notes:
        fm = note.get("frontmatter", {})
        if isinstance(fm, str):
            fm = json.loads(fm)
        concepts = set(str(c).lower() for c in normalize_metadata_values(fm.get("concepts", [])))
        if concepts:
            node_concepts[normalize_vault_path(note["file_path"])] = concepts

    # Pairwise intersection
    paths = list(node_concepts.keys())
    overlap_relations = []
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            p1, p2 = paths[i], paths[j]
            intersection = node_concepts[p1] & node_concepts[p2]
            if len(intersection) >= 2:
                overlap_relations.append({
                    "source_path": normalize_vault_path(p1),
                    "target_path": normalize_vault_path(p2),
                    "rel_type": "concept_overlap",
                })

    return overlap_relations


def compute_concept_overlap_for_instance(
    instance_id: str,
    db,
) -> int:
    """Compute and store concept_overlap relations for an instance.

    Queries notes from DB, computes pairwise intersections, inserts results.
    Returns the number of concept_overlap relations created.
    """
    # Delete stale concept_overlap relations before recomputing
    db.execute(
        "DELETE FROM relations WHERE instance_id = ? AND rel_type = 'concept_overlap'",
        (instance_id,),
    )

    rows = db.execute(
        "SELECT file_path, frontmatter FROM notes WHERE instance_id = ?",
        (instance_id,),
    )

    notes_data = []
    for row in rows:
        fm = row["frontmatter"]
        if isinstance(fm, str):
            fm = json.loads(fm)
        notes_data.append({"file_path": normalize_vault_path(row["file_path"]), "frontmatter": fm})

    overlaps = compute_concept_overlap_batch(notes_data)

    if overlaps:
        db.executemany(
            "INSERT OR IGNORE INTO relations (instance_id, source_path, target_path, rel_type) VALUES (?, ?, ?, ?)",
            [
                (
                    instance_id,
                    normalize_vault_path(r["source_path"]),
                    normalize_vault_path(r["target_path"]),
                    r["rel_type"],
                )
                for r in overlaps
            ],
        )

    return len(overlaps)


def compute_concept_overlap_incremental(
    instance_id: str,
    new_card_paths: list[str],
    new_card_contents: list[str],
    db,
) -> int:
    """Compute concept_overlap relations incrementally for new cards only.

    PIT-25: Only delete overlaps involving new cards and compute overlaps
    between new cards and existing cards. This avoids full recalculation.

    Returns the number of concept_overlap relations created.
    """
    if not new_card_paths:
        return 0

    # Delete only overlaps involving the new cards
    new_card_paths = [normalize_vault_path(path) for path in new_card_paths]
    placeholders = ",".join(["?"] * len(new_card_paths))
    db.execute(
        f"DELETE FROM relations WHERE instance_id = ? AND rel_type = 'concept_overlap' "
        f"AND (source_path IN ({placeholders}) OR target_path IN ({placeholders}))",
        [instance_id] + new_card_paths + new_card_paths,
    )

    # Get all existing notes for this instance
    rows = db.execute(
        "SELECT file_path, frontmatter FROM notes WHERE instance_id = ?",
        (instance_id,),
    )

    existing_notes = []
    for row in rows:
        fm = row["frontmatter"]
        if isinstance(fm, str):
            fm = json.loads(fm)
        existing_notes.append({"file_path": normalize_vault_path(row["file_path"]), "frontmatter": fm})

    # Build new cards data
    new_notes = []
    for path, content in zip(new_card_paths, new_card_contents):
        from app.schema.parser import parse_frontmatter
        fm, _ = parse_frontmatter(content)
        new_notes.append({"file_path": normalize_vault_path(path), "frontmatter": fm})

    # Compute overlaps between new cards and existing cards
    all_notes = new_notes + existing_notes
    overlaps = compute_concept_overlap_batch(all_notes)

    # Filter to only include overlaps involving new cards
    new_card_set = set(new_card_paths)
    filtered_overlaps = [
        r for r in overlaps
        if r["source_path"] in new_card_set or r["target_path"] in new_card_set
    ]

    if filtered_overlaps:
        db.executemany(
            "INSERT OR IGNORE INTO relations (instance_id, source_path, target_path, rel_type) VALUES (?, ?, ?, ?)",
            [
                (
                    instance_id,
                    normalize_vault_path(r["source_path"]),
                    normalize_vault_path(r["target_path"]),
                    r["rel_type"],
                )
                for r in filtered_overlaps
            ],
        )

    return len(filtered_overlaps)
