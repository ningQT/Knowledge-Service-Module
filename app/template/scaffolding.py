"""Instance directory scaffolding - creates vault directory structure."""

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml


def create_instance_scaffold(
    vault_path: str,
    instance_id: str,
    instance_name: str,
    template_id: str,
    auto_map: bool = True,
    directory_skeleton: list[str] | None = None,
) -> None:
    """Create the complete vault directory structure for a new instance."""
    vault = Path(vault_path)
    vault.mkdir(parents=True, exist_ok=True)

    directories = directory_skeleton or [
        "00-收件箱",
        "01-资料来源",
        "02-知识卡片",
        "03-知识地图",
        ".obsidian",
    ]
    for directory in directories:
        (vault / directory).mkdir(parents=True, exist_ok=True)

    # Ensure raw subdirectory for source documents
    source_dir = next((d for d in directories if "资料来源" in d or d == "01-sources"), None)
    if source_dir:
        (vault / source_dir / "raw").mkdir(parents=True, exist_ok=True)

    instance_config = {
        "instance": {
            "id": instance_id,
            "name": instance_name,
            "template_id": template_id,
            "vault_path": str(vault),
            "auto_map": auto_map,
            "schema_extensions": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    }
    with open(vault / "instance.yaml", "w", encoding="utf-8") as f:
        yaml.dump(instance_config, f, default_flow_style=False, allow_unicode=True)

    inbox_dir = next((d for d in directories if "收件箱" in d or d == "00-inbox"), "00-收件箱")
    obsidian_config = {
        "newFileLocation": "folder",
        "newFileFolderPath": inbox_dir,
        "useMarkdownLinks": False,
        "showFrontmatter": True,
        "alwaysUpdateLinks": True,
    }
    with open(vault / ".obsidian" / "app.json", "w", encoding="utf-8") as f:
        json.dump(obsidian_config, f, indent=2, ensure_ascii=False)

    with open(vault / ".obsidian" / "graph.json", "w", encoding="utf-8") as f:
        json.dump({}, f)
