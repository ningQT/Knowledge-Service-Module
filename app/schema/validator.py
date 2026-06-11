"""Frontmatter schema validation."""

from app.exceptions import InvalidSchemaError

VALID_TYPES = {"source", "card", "map"}
VALID_GRAPH_LAYERS = {0, 1, 2, 3}
VALID_GRAPH_ROLES = {"inbox", "source", "concept", "method", "index"}
VALID_VERIFICATIONS = {"verified", "unverified", "draft", "truncated"}
VALID_STATUSES = {"draft", "active", "archived"}

# Required fields per note type
REQUIRED_FIELDS = {
    "source": ["type", "graph_layer", "graph_role"],
    "card": ["type", "graph_layer", "graph_role"],
    "map": ["type", "graph_layer", "graph_role"],
}

# Expected graph_layer per type
TYPE_LAYER_MAP = {
    "source": 1,
    "card": 2,
    "map": 3,
}


class SchemaValidator:
    """Validates frontmatter against the schema definition."""

    def validate(self, frontmatter: dict, note_type: str | None = None) -> list[str]:
        """Validate frontmatter and return list of warnings.

        Raises InvalidSchemaError for critical violations.
        Returns list of non-critical warnings.
        """
        warnings = []
        note_type = note_type or frontmatter.get("type")

        if not note_type:
            raise InvalidSchemaError("Missing 'type' field in frontmatter")

        if note_type not in VALID_TYPES:
            raise InvalidSchemaError(f"Invalid type: {note_type}. Must be one of {VALID_TYPES}")

        # Check required fields
        for field in REQUIRED_FIELDS.get(note_type, []):
            if field not in frontmatter:
                raise InvalidSchemaError(f"Missing required field '{field}' for type '{note_type}'")

        # Validate graph_layer
        layer = frontmatter.get("graph_layer")
        if layer is not None:
            if layer not in VALID_GRAPH_LAYERS:
                raise InvalidSchemaError(f"Invalid graph_layer: {layer}. Must be one of {VALID_GRAPH_LAYERS}")
            expected_layer = TYPE_LAYER_MAP.get(note_type)
            if expected_layer is not None and layer != expected_layer:
                warnings.append(f"graph_layer={layer} does not match type '{note_type}' (expected {expected_layer})")

        # Validate graph_role
        role = frontmatter.get("graph_role")
        if role is not None and role not in VALID_GRAPH_ROLES:
            raise InvalidSchemaError(f"Invalid graph_role: {role}. Must be one of {VALID_GRAPH_ROLES}")

        # Validate verification
        verification = frontmatter.get("verification")
        if verification is not None and verification not in VALID_VERIFICATIONS:
            raise InvalidSchemaError(f"Invalid verification: {verification}. Must be one of {VALID_VERIFICATIONS}")

        # Validate status
        status = frontmatter.get("status")
        if status is not None and status not in VALID_STATUSES:
            raise InvalidSchemaError(f"Invalid status: {status}. Must be one of {VALID_STATUSES}")

        # Validate list fields
        for field in [
            "sources",
            "concepts",
            "extracted_cards",
            "core_concepts",
            "reading_path",
            "key_relations",
            "source_materials",
            "linked_maps",
            "extractable_knowledge_points",
        ]:
            value = frontmatter.get(field)
            if value is not None and not isinstance(value, list):
                raise InvalidSchemaError(f"Field '{field}' must be a list")

        if note_type == "source":
            doc_summary = frontmatter.get("doc_summary")
            if isinstance(doc_summary, str) and len(doc_summary) > 2000:
                warnings.append("Source doc_summary should not exceed 2000 characters")

        # Check concepts/sources for cards (FR-04-1: structural quality constraints)
        if note_type == "card":
            concepts = frontmatter.get("concepts", [])
            if not concepts:
                raise InvalidSchemaError("Card must have at least one concept in 'concepts' field (FR-04-1)")

            sources = frontmatter.get("sources", [])
            if not sources:
                raise InvalidSchemaError("Card must have at least one source in 'sources' field (FR-04-1)")

        return warnings
