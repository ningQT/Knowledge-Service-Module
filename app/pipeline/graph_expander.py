"""Graph expansion — BFS from anchor nodes along relations.

Reference: 知识服务模块检索流程完整设计_v2 Section 10
"""

import json
import logging

from app.pipeline.node_key import node_key as _node_key
from app.storage.database import DatabaseBackend

logger = logging.getLogger(__name__)

# Relation types that allow 2-hop expansion
# concept_overlap excluded from strong types per design doc §7.6 (hop-2 exclusion)
STRONG_REL_TYPES = {"direct_link", "source_trace", "extracted_from", "map_contains"}
ALL_REL_TYPES = STRONG_REL_TYPES | {"concept_overlap"}


def graph_expansion(
    anchors: list[dict],
    intent_type: str,
    instance_ids: list[str],
    max_depth: int,
    db: DatabaseBackend,
) -> dict:
    """BFS graph expansion from anchor nodes.

    Returns dict with 'nodes', 'edges', 'stats'.
    """
    visited = {_node_key(a) for a in anchors}
    frontier = {(a.get("instance_id"), a["path"]) for a in anchors}
    all_nodes: dict[str, dict] = {}
    all_edges: list[dict] = []
    depth = 0

    # Add anchor nodes
    for a in anchors:
        all_nodes[_node_key(a)] = {**a, "hop_distance": 0, "rel_type_to_anchor": None}

    while depth < max_depth and frontier:
        depth += 1
        next_frontier: set[tuple[str | None, str]] = set()

        for current_instance_id, current_path in frontier:
            if not current_instance_id:
                continue
            # Forward relations
            edges = _query_relations(current_path, current_instance_id, db)
            # Reverse relations
            reverse_edges = _query_reverse_relations(current_path, current_instance_id, db)

            all_edges.extend(edges)
            all_edges.extend(reverse_edges)

            for edge in edges:
                neighbor_path = edge["target_path"]
                neighbor_key = _edge_target_key(edge)
                if neighbor_key in visited:
                    continue
                visited.add(neighbor_key)
                next_frontier.add((edge["instance_id"], neighbor_path))

                neighbor_info = _load_note_info(neighbor_path, edge["instance_id"], db)
                if neighbor_info:
                    neighbor_info["hop_distance"] = depth
                    neighbor_info["rel_type_to_anchor"] = edge["rel_type"]
                    all_nodes[neighbor_key] = neighbor_info

                    # 2-hop: only continue on strong relations
                    if depth < max_depth and edge["rel_type"] not in STRONG_REL_TYPES:
                        next_frontier.discard((edge["instance_id"], neighbor_path))

            for edge in reverse_edges:
                neighbor_path = edge["source_path"]
                neighbor_key = _edge_source_key(edge)
                if neighbor_key in visited:
                    continue
                visited.add(neighbor_key)
                next_frontier.add((edge["instance_id"], neighbor_path))

                neighbor_info = _load_note_info(neighbor_path, edge["instance_id"], db)
                if neighbor_info:
                    neighbor_info["hop_distance"] = depth
                    neighbor_info["rel_type_to_anchor"] = edge["rel_type"]
                    all_nodes[neighbor_key] = neighbor_info

                    if depth < max_depth and edge["rel_type"] not in STRONG_REL_TYPES:
                        next_frontier.discard((edge["instance_id"], neighbor_path))

        frontier = next_frontier

    return {
        "nodes": all_nodes,
        "edges": all_edges,
        "stats": {
            "total_nodes": len(all_nodes),
            "total_edges": len(all_edges),
            "max_depth_reached": depth,
        },
    }


def _query_relations(source_path: str, instance_id: str, db: DatabaseBackend) -> list[dict]:
    """Forward relations: source_path → targets."""
    return db.execute(
        """SELECT instance_id, source_path, target_path, rel_type
            FROM relations
            WHERE source_path = ?
              AND instance_id = ?""",
        (source_path, instance_id),
    )


def _query_reverse_relations(target_path: str, instance_id: str, db: DatabaseBackend) -> list[dict]:
    """Reverse relations: sources → target_path."""
    return db.execute(
        """SELECT instance_id, source_path, target_path, rel_type
            FROM relations
            WHERE target_path = ?
              AND instance_id = ?""",
        (target_path, instance_id),
    )


def _load_note_info(file_path: str, instance_id: str, db: DatabaseBackend) -> dict | None:
    """Load note info from the index."""
    rows = db.execute(
        """SELECT instance_id, file_path, title, graph_layer, graph_role, domain, kind,
                   verification, frontmatter
            FROM notes
            WHERE file_path = ?
              AND instance_id = ?
            LIMIT 1""",
        (file_path, instance_id),
    )
    if not rows:
        return None
    row = rows[0]
    fm = json.loads(row["frontmatter"]) if isinstance(row["frontmatter"], str) else row["frontmatter"]
    return {
        "instance_id": row["instance_id"],
        "path": row["file_path"],
        "title": row["title"],
        "graph_layer": row["graph_layer"],
        "graph_role": row.get("graph_role"),
        "domain": row.get("domain"),
        "kind": row.get("kind"),
        "verification": row.get("verification", "unverified"),
        "frontmatter": fm,
        "concepts": fm.get("concepts", []),
        "score": 0.0,
        "match_type": "",
    }


def _edge_source_key(edge: dict) -> str:
    return f"{edge.get('instance_id') or ''}\0{edge.get('source_path') or ''}"


def _edge_target_key(edge: dict) -> str:
    return f"{edge.get('instance_id') or ''}\0{edge.get('target_path') or ''}"
