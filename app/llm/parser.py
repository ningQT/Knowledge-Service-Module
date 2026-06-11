"""LLM output parsing utilities."""

import json
import re
import logging
from typing import TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


def parse_llm_json(raw_text: str) -> dict:
    """Extract and parse JSON from LLM response text.

    Handles: raw JSON, JSON in code blocks, JSON with surrounding text.
    """
    text = raw_text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from code blocks
    code_block_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if code_block_match:
        try:
            return json.loads(code_block_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding first { ... } or [ ... ]
    for pattern in [r"\{.*\}", r"\[.*\]"]:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

    raise ValueError(f"Could not extract JSON from LLM response: {text[:200]}...")


def parse_llm_output(raw_text: str, expected_model: type[T]) -> T:
    """Parse LLM response into a pydantic model.

    Retries JSON extraction and validation with type coercion.
    """
    data = parse_llm_json(raw_text)

    try:
        return expected_model.model_validate(data)
    except ValidationError as e:
        logger.warning(f"Validation failed, attempting fix: {e}")
        # Try to fix common issues
        if isinstance(data, dict):
            # Remove unexpected fields
            expected_fields = set(expected_model.model_fields.keys())
            filtered = {k: v for k, v in data.items() if k in expected_fields}
            # PIT-11: Attempt type coercion for common LLM output issues
            filtered = _coerce_types(filtered, expected_model)
            try:
                return expected_model.model_validate(filtered)
            except ValidationError:
                pass
        raise


def _coerce_types(data: dict, model_class: type[BaseModel]) -> dict:
    """Coerce common type mismatches in LLM output.

    Handles: str->int, str->float, int->str for numeric-looking strings.
    """
    coerced = {}
    for key, value in data.items():
        if key not in model_class.model_fields:
            continue
        field_info = model_class.model_fields[key]
        expected_type = field_info.annotation

        # Handle Optional types
        if hasattr(expected_type, "__args__"):
            # Get the inner type from Optional[X] or Union[X, None]
            args = [a for a in expected_type.__args__ if a is not type(None)]
            if args:
                expected_type = args[0]

        if isinstance(value, str):
            # str -> int
            if expected_type is int and value.strip().isdigit():
                try:
                    coerced[key] = int(value.strip())
                    continue
                except (ValueError, TypeError):
                    pass
            # str -> float
            if expected_type is float:
                try:
                    coerced[key] = float(value.strip())
                    continue
                except (ValueError, TypeError):
                    pass
        elif isinstance(value, (int, float)):
            # int/float -> str (for dict keys that should be strings)
            if expected_type is str:
                coerced[key] = str(value)
                continue

        coerced[key] = value
    return coerced
