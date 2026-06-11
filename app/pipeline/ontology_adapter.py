"""Ontology adapter for search pipeline integration."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.ontology_query_service import OntologyQueryService
from app.storage.database import DatabaseBackend

logger = logging.getLogger(__name__)


class OntologyAdapter:
    """Bridges ontology recall into the search pipeline."""

    def __init__(self, db: DatabaseBackend):
        self.db = db
        self._query_service = OntologyQueryService(db)

    def is_enabled(self, instance_ids: list[str]) -> bool:
        """Check global and per-instance ontology switch.

        Global switch: settings table key 'ontology.enabled', value '1' or '0'
        Per-instance switch: instances.config_json field 'ontology_enabled'
        """
        if not instance_ids:
            return False

        # Check global switch
        if not self._check_global_switch():
            return False

        # Check per-instance switch (at least one must be enabled)
        return len(self._get_enabled_instances(instance_ids)) > 0

    def _get_enabled_instances(self, instance_ids: list[str]) -> list[str]:
        """Return only instance IDs that have ontology enabled."""
        return [iid for iid in instance_ids if self._check_instance_switch(iid)]

    def recall_for_search(
        self,
        query_context: dict[str, Any],
        instance_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Execute ontology recall and return bridge-ready candidates."""
        if not self.is_enabled(instance_ids):
            return []

        # Only iterate instances with ontology enabled
        enabled_ids = self._get_enabled_instances(instance_ids)
        if not enabled_ids:
            return []

        exact_candidates = query_context.get("exact_candidates", [])
        phrase_candidates = query_context.get("phrase_candidates", [])
        expanded_candidates = query_context.get("expanded_candidates", [])
        intent_type = query_context.get("intent_type", "fallback")
        domain_hint = query_context.get("domain_hint")
        all_terms = [*exact_candidates, *phrase_candidates, *expanded_candidates]

        if not all_terms:
            return []

        candidates: list[dict[str, Any]] = []
        for inst_id in enabled_ids:
            try:
                results = self._query_service.recall_for_query(
                    inst_id,
                    all_terms,
                    intent_type=intent_type,
                    domain_hint=domain_hint,
                )
                candidates.extend(results)
            except Exception:
                logger.warning("Ontology recall failed for instance %s", inst_id, exc_info=True)

        if not candidates:
            return []

        # Bridge to note-compatible format (per-instance to avoid cross-instance pollution)
        return self._bridge_to_notes(candidates, instance_ids)

    def _bridge_to_notes(
        self,
        ontology_results: list[dict[str, Any]],
        instance_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Convert ontology recall results into note-compatible candidate dicts."""
        bridged: list[dict[str, Any]] = []

        for result in ontology_results:
            bridge_paths = result.get("bridge_paths", [])
            if not bridge_paths:
                continue

            # Use the source instance from the result for bridging
            source_instance = result.get("instance_id")
            bridge_instances = [source_instance] if source_instance and source_instance in instance_ids else instance_ids

            for path_info in bridge_paths:
                note_path = path_info["file_path"]
                note_info = self._load_note_info(note_path, bridge_instances)
                if note_info is None:
                    continue

                # Enrich with ontology metadata
                note_info["match_type"] = "ontology_recall"
                note_info["candidate_layer"] = "ontology"
                note_info["candidate_layers"] = ["ontology"]
                note_info["matched_channels"] = result.get("matched_channels", [])
                note_info["base_score"] = result.get("recall_score", 0.5)
                note_info["recall_reason"] = result.get("recall_reason", "")
                note_info["ontology_entity_id"] = result.get("entity_id")
                note_info["ontology_entity_name"] = result.get("entity_name")
                bridged.append(note_info)

        return bridged

    def _load_note_info(
        self,
        file_path: str,
        instance_ids: list[str],
    ) -> dict[str, Any] | None:
        """Load note info from database for bridging."""
        placeholders = ",".join("?" * len(instance_ids))
        rows = self.db.execute(
            """SELECT id, instance_id, file_path, title, type, domain, kind,
                      graph_layer, graph_role, verification, status
               FROM notes
               WHERE file_path = ? AND instance_id IN ({})""".format(placeholders),
            [file_path, *instance_ids],
        )
        if not rows:
            return None

        row = rows[0]
        return {
            "note_id": row["id"],
            "path": row["file_path"],
            "title": row["title"],
            "type": row.get("type"),
            "domain": row.get("domain"),
            "kind": row.get("kind"),
            "graph_layer": row.get("graph_layer", 0),
            "graph_role": row.get("graph_role"),
            "verification": row.get("verification", "unverified"),
            "status": row.get("status", "active"),
            "instance_id": row["instance_id"],
        }

    def _check_global_switch(self) -> bool:
        """Check if ontology is globally enabled via settings table."""
        rows = self.db.execute(
            "SELECT value FROM settings WHERE key = 'ontology.enabled'",
        )
        if not rows:
            return False  # Default off
        return rows[0]["value"] == "1"

    def _check_instance_switch(self, instance_id: str) -> bool:
        """Check if ontology is enabled for a specific instance."""
        rows = self.db.execute(
            "SELECT config_json FROM instances WHERE id = ?",
            (instance_id,),
        )
        if not rows:
            return False

        config_raw = rows[0].get("config_json", "{}")
        try:
            config = json.loads(config_raw) if isinstance(config_raw, str) else config_raw
        except (json.JSONDecodeError, TypeError):
            config = {}

        return bool(config.get("ontology_enabled", True))
