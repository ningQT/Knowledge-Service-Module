"""Shared identity helpers for search pipeline nodes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def node_key(node: Mapping[str, Any]) -> str:
    return f"{node.get('instance_id') or ''}\0{node.get('path') or node.get('file_path') or ''}"


def row_key(row: Mapping[str, Any]) -> str:
    return node_key({"instance_id": row.get("instance_id"), "path": row.get("file_path")})
