"""Exceptions raised by shared phase-two infrastructure."""

from app.exceptions import KSMError


class SharedInfraError(KSMError):
    def __init__(self, message: str, code: str = "SHARED_INFRA_ERROR"):
        super().__init__(message, code)


class EmptyContentError(SharedInfraError):
    def __init__(self):
        super().__init__("Document content is empty", "EMPTY_CONTENT")


class YAMLParseError(SharedInfraError):
    def __init__(self, detail: str):
        super().__init__(f"Invalid YAML frontmatter: {detail}", "YAML_PARSE_ERROR")


class StructureParseError(SharedInfraError):
    def __init__(self, detail: str):
        super().__init__(f"Markdown structure parse failed: {detail}", "STRUCTURE_PARSE_ERROR")


class BudgetExhaustedError(SharedInfraError):
    def __init__(self):
        super().__init__("Reading budget exhausted", "BUDGET_EXHAUSTED")
