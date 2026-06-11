"""Template registry for loading and managing templates."""

import logging
from pathlib import Path

import yaml

from app.exceptions import TemplateNotFoundError
from app.template.models import NoteTemplate, TemplateDefinition

logger = logging.getLogger(__name__)


class TemplateRegistry:
    """Loads and manages knowledge base templates."""

    def __init__(self, template_dir: str):
        self.template_dir = Path(template_dir)
        self._templates: dict[str, TemplateDefinition] = {}

    def load_templates(self) -> None:
        """Discover and load all templates from template_dir."""
        if not self.template_dir.exists():
            logger.warning(f"Template directory not found: {self.template_dir}")
            return

        for template_path in self.template_dir.iterdir():
            if template_path.is_dir():
                yaml_file = template_path / "template.yaml"
                if yaml_file.exists():
                    try:
                        template = self._load_template(template_path)
                        self._templates[template.id] = template
                        logger.info(f"Loaded template: {template.id}")
                    except Exception as e:
                        logger.error(f"Failed to load template {template_path.name}: {e}")

    def list_templates(self) -> list[TemplateDefinition]:
        """List all loaded templates."""
        return list(self._templates.values())

    def get_template(self, template_id: str) -> TemplateDefinition:
        """Get a template by ID."""
        if template_id not in self._templates:
            raise TemplateNotFoundError(template_id)
        return self._templates[template_id]

    def has_template(self, template_id: str) -> bool:
        """Check if template exists."""
        return template_id in self._templates

    def _load_template(self, template_path: Path) -> TemplateDefinition:
        """Load a single template from its directory."""
        yaml_file = template_path / "template.yaml"
        with open(yaml_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Load note templates
        notes_dir = template_path / "notes"
        note_templates = {}
        if notes_dir.exists():
            for note_file in notes_dir.glob("*.md"):
                name = note_file.stem
                content = note_file.read_text(encoding="utf-8")
                note_templates[name] = NoteTemplate(name=name, content=content)

        # Load schema path
        schema_path = template_path / "schema.yaml"

        return TemplateDefinition(
            id=data.get("id", template_path.name),
            name=data.get("name", template_path.name),
            version=data.get("version", "1.0"),
            description=data.get("description", ""),
            directory_skeleton=data.get("directory_skeleton", []),
            default_config=data.get("default_config", {}),
            note_templates=note_templates,
            schema_path=str(schema_path) if schema_path.exists() else None,
        )
