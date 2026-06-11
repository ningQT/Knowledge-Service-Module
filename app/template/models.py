"""Template pydantic models."""

from pydantic import BaseModel, Field


class NoteTemplate(BaseModel):
    """A note template with its content."""

    name: str
    content: str


class TemplateDefinition(BaseModel):
    """Full template definition loaded from template.yaml."""

    id: str = Field(description="Template unique identifier")
    name: str = Field(description="Human-readable template name")
    version: str = Field(default="1.0")
    description: str = Field(default="")
    directory_skeleton: list[str] = Field(default_factory=list)
    default_config: dict = Field(default_factory=dict)
    note_templates: dict[str, NoteTemplate] = Field(default_factory=dict)
    schema_path: str | None = Field(default=None)
