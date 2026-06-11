"""KSM exception hierarchy."""


class KSMError(Exception):
    """Base exception for all KSM errors."""

    def __init__(self, message: str, code: str = "KSM_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class InstanceNotFoundError(KSMError):
    """Instance does not exist."""

    def __init__(self, instance_id: str):
        super().__init__(f"Instance not found: {instance_id}", "INSTANCE_NOT_FOUND")


class InstanceAlreadyExistsError(KSMError):
    """Instance name already exists."""

    def __init__(self, name: str):
        super().__init__(f"Instance name already exists: {name}", "INSTANCE_ALREADY_EXISTS")


class TemplateNotFoundError(KSMError):
    """Template does not exist."""

    def __init__(self, template_id: str):
        super().__init__(f"Template not found: {template_id}", "TEMPLATE_NOT_FOUND")


class InvalidSchemaError(KSMError):
    """Frontmatter schema validation failed."""

    def __init__(self, detail: str):
        super().__init__(f"Invalid schema: {detail}", "INVALID_SCHEMA")


class IngestFailedError(KSMError):
    """Knowledge ingestion pipeline failed."""

    def __init__(self, detail: str):
        super().__init__(f"Ingest failed: {detail}", "INGEST_FAILED")


class SearchParamError(KSMError):
    """Invalid search parameters."""

    def __init__(self, detail: str):
        super().__init__(f"Search parameter error: {detail}", "SEARCH_PARAM_ERROR")


class NodeReadError(KSMError):
    """A search result node could not be read from storage."""

    def __init__(self, detail: str):
        super().__init__(f"Node read failed: {detail}", "NODE_READ_ERROR")


class ComprehensionError(KSMError):
    """Search result comprehension failed."""

    def __init__(self, detail: str):
        super().__init__(f"Comprehension failed: {detail}", "COMPREHENSION_ERROR")


class SyncFailedError(KSMError):
    """Synchronization failed."""

    def __init__(self, detail: str):
        super().__init__(f"Sync failed: {detail}", "SYNC_FAILED")


class ReindexFailedError(KSMError):
    """Reindex failed."""

    def __init__(self, detail: str):
        super().__init__(f"Reindex failed: {detail}", "REINDEX_FAILED")


class PipelineCancelledException(KSMError):
    """Pipeline was cancelled by user."""

    def __init__(self):
        super().__init__("Pipeline cancelled by user", "PIPELINE_CANCELLED")
