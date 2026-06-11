"""Character-budget helpers for controlled document reading."""

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from app.shared_infra.models import BudgetStatus, ReadingStrategy
from app.shared_infra.truncation import truncate_with_marker


def create_budget(limit: int) -> BudgetStatus:
    limit = max(0, limit)
    return BudgetStatus(limit=limit, used=0, remaining=limit, utilization=0.0)


def update_budget(status: BudgetStatus, used: int) -> BudgetStatus:
    total_used = max(0, used)
    remaining = max(status.limit - total_used, 0)
    utilization = total_used / status.limit if status.limit else 1.0
    return BudgetStatus(
        limit=status.limit,
        used=total_used,
        remaining=remaining,
        utilization=min(utilization, 1.0),
    )


def is_over_budget(status: BudgetStatus) -> bool:
    return status.used > status.limit


def enforce_budget(
    items: list[dict[str, Any]],
    budget_status: BudgetStatus,
    estimate_fn: Callable[[dict[str, Any]], int],
    priority_map: dict[str, int],
    min_reserve: int = 0,
) -> tuple[list[dict[str, Any]], BudgetStatus]:
    """Keep higher-priority items inside the budget and mark lower priority as skipped."""
    working = [deepcopy(item) for item in items]
    working.sort(key=lambda item: priority_map.get(item.get("group", ""), 99))
    accepted: list[dict[str, Any]] = []
    used = 0

    for item in working:
        estimate = max(0, estimate_fn(item))
        if used + estimate <= budget_status.limit:
            item["truncated"] = False
            accepted.append(item)
            used += estimate
            continue

        downgraded = _downgrade_item(item, estimate_fn, budget_status.limit - used)
        if downgraded is not None:
            accepted.append(downgraded)
            used += max(0, estimate_fn(downgraded))
            continue

        item["strategy"] = ReadingStrategy.SKIP.value
        item["content"] = None
        item["truncated"] = True
        accepted.append(item)

    if used == 0 and min_reserve > 0 and accepted:
        first = min(accepted, key=lambda item: priority_map.get(item.get("group", ""), 99))
        if first.get("content"):
            first["content"] = truncate_with_marker(str(first["content"]), min_reserve)
            first["strategy"] = ReadingStrategy.SUMMARY.value
            first["truncated"] = True
            used = len(first["content"])

    return accepted, update_budget(budget_status, used)


def _downgrade_item(
    item: dict[str, Any],
    estimate_fn: Callable[[dict[str, Any]], int],
    remaining: int,
) -> dict[str, Any] | None:
    if remaining <= 0:
        return None
    chain = [
        ReadingStrategy.KEY_SECTIONS.value,
        ReadingStrategy.SUMMARY.value,
        ReadingStrategy.SKIP.value,
    ]
    content = str(item.get("content") or "")
    for strategy in chain:
        candidate = deepcopy(item)
        candidate["strategy"] = strategy
        candidate["truncated"] = True
        if strategy == ReadingStrategy.KEY_SECTIONS.value:
            candidate["content"] = truncate_with_marker(content, max(remaining, 0))
        elif strategy == ReadingStrategy.SUMMARY.value:
            candidate["content"] = truncate_with_marker(content, min(remaining, 800))
        else:
            candidate["content"] = None
        if estimate_fn(candidate) <= remaining:
            return candidate
    return None
