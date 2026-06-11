"""API routes for graph visualization."""

import json

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import ensure_instance_access, get_db, require_read_context
from app.api.models import GraphEdgeResponse, GraphNodeResponse, GraphResponse
from app.storage.path_utils import normalize_vault_path

router = APIRouter(prefix="/api/v1/instances", tags=["graph"])


@router.get("/{instance_id}/graph", response_model=GraphResponse, response_model_exclude_none=True)
async def get_graph(
    instance_id: str,
    layer_filter: int | None = None,
    domain_filter: str | None = None,
    verification_filter: str | None = None,
    include_unresolved: bool = False,
    auth=Depends(require_read_context),
):
    """Return nodes and edges for React Flow rendering."""
    db = get_db()
    ensure_instance_access(auth, instance_id)

    # Verify instance exists
    rows = db.execute("SELECT id FROM instances WHERE id = ?", (instance_id,))
    if not rows:
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found")

    # Build dynamic WHERE clause
    conditions = ["n.instance_id = ?"]
    params: list = [instance_id]

    if layer_filter is not None:
        conditions.append("n.graph_layer = ?")
        params.append(layer_filter)
    if domain_filter is not None:
        conditions.append("""(
            n.domain = ?
            OR EXISTS (
                SELECT 1 FROM note_facets nf
                WHERE nf.instance_id = n.instance_id
                  AND nf.file_path = n.file_path
                  AND nf.field = 'domain'
                  AND nf.value = ?
            )
        )""")
        params.extend([domain_filter, domain_filter])
    if verification_filter is not None:
        conditions.append("n.verification = ?")
        params.append(verification_filter)

    where_clause = " AND ".join(conditions)

    # Query nodes
    node_rows = db.execute(
        f"""SELECT n.file_path, n.title, n.type, n.graph_layer, n.graph_role,
                   n.verification, n.domain, n.frontmatter
            FROM notes n
            WHERE {where_clause}
            ORDER BY n.graph_layer, n.title""",
        tuple(params),
    )

    nodes: list[GraphNodeResponse] = []
    node_paths: set[str] = set()

    for row in node_rows:
        path = normalize_vault_path(row["file_path"])
        node_paths.add(path)

        # Parse concepts from frontmatter
        concepts: list[str] = []
        try:
            fm = json.loads(row.get("frontmatter") or "{}")
            raw_concepts = fm.get("concepts", [])
            if isinstance(raw_concepts, list):
                concepts = [str(item) for item in raw_concepts if item][:10]
            elif raw_concepts:
                concepts = [str(raw_concepts)]
        except (json.JSONDecodeError, TypeError):
            pass

        nodes.append(GraphNodeResponse(
            id=path,
            title=row["title"],
            type=row["type"] or "unknown",
            graph_layer=row["graph_layer"] or 0,
            graph_role=row.get("graph_role"),
            verification=row["verification"] or "unverified",
            domain=row.get("domain"),
            concepts=concepts,
        ))

    # Query edges (only between nodes in the current set)
    edges: list[GraphEdgeResponse] = []
    if node_paths:
        edge_rows = db.execute(
            """SELECT id, source_path, target_path, rel_type
                FROM relations
                WHERE instance_id = ?
                ORDER BY rel_type""",
            (instance_id,),
        )

        for idx, row in enumerate(edge_rows):
            source = normalize_vault_path(row["source_path"])
            target = normalize_vault_path(row["target_path"])
            if source not in node_paths or target not in node_paths:
                continue
            edges.append(GraphEdgeResponse(
                id=f"e_{idx}",
                source=source,
                target=target,
                rel_type=row["rel_type"],
            ))

        if include_unresolved:
            unresolved_rows = db.execute(
                """SELECT source_path, target_text, source_field, link_kind
                   FROM link_references
                   WHERE instance_id = ? AND resolved = 0
                   ORDER BY source_path, target_text""",
                (instance_id,),
            )
            virtual_nodes: dict[str, GraphNodeResponse] = {}
            unresolved_edge_index = 0
            for row in unresolved_rows:
                source = normalize_vault_path(row["source_path"])
                if source not in node_paths:
                    continue
                if _reference_resolves(db, instance_id, row["target_text"]):
                    continue
                virtual_id = f"unresolved:{row['target_text'].casefold()}"
                if virtual_id not in virtual_nodes:
                    virtual_nodes[virtual_id] = GraphNodeResponse(
                        id=virtual_id,
                        title=row["target_text"],
                        type="unresolved",
                        graph_layer=0,
                        graph_role="unresolved",
                        verification="unresolved",
                        domain=None,
                        concepts=[],
                        unresolved=True,
                        target_text=row["target_text"],
                    )
                edges.append(GraphEdgeResponse(
                    id=f"u_{unresolved_edge_index}",
                    source=source,
                    target=virtual_id,
                    rel_type="unresolved_link",
                    source_field=row["source_field"],
                ))
                unresolved_edge_index += 1
            nodes.extend(virtual_nodes.values())

    return GraphResponse(nodes=nodes, edges=edges)


def _reference_resolves(db, instance_id: str, target_text: str) -> bool:
    target = normalize_vault_path(str(target_text or "").strip())
    stem = target.rsplit("/", 1)[-1].removesuffix(".md")
    rows = db.execute(
        """SELECT 1
           FROM notes
           WHERE instance_id = ?
             AND (
                lower(file_path) = ?
                OR lower(file_path) = ?
                OR lower(file_path) LIKE ?
                OR lower(title) = ?
             )
           LIMIT 1""",
        (
            instance_id,
            target.lower(),
            f"{stem.lower()}.md",
            f"%/{stem.lower()}.md",
            stem.lower(),
        ),
    )
    if rows:
        return True
    facet_rows = db.execute(
        """SELECT 1
           FROM note_facets
           WHERE instance_id = ?
             AND field IN ('aliases', 'concepts')
             AND lower(value) = ?
           LIMIT 1""",
        (instance_id, stem.lower()),
    )
    return bool(facet_rows)
