"""轻量任务权限协调器。

现有入库和问答任务分别保存在各自路由模块中。本模块只登记任务所属账户、
实例和访问模式，用于权限变化时通知任务取消，不持有任务状态本身。
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

JobAccessMode = Literal["read", "write"]


@dataclass(frozen=True)
class JobAccessEntry:
    """任务权限上下文。"""

    job_id: str
    account_id: str
    instance_ids: frozenset[str]
    access_mode: JobAccessMode


class JobAccessRegistry:
    """线程安全的任务权限登记与取消协调器。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[str, JobAccessEntry] = {}
        self._cancelled: dict[str, str] = {}

    def register(
        self,
        job_id: str,
        account_id: str,
        instance_ids: str | Iterable[str],
        access_mode: JobAccessMode,
    ) -> None:
        """登记任务所属账户、实例和访问模式。"""
        normalized_ids = frozenset(
            [instance_ids] if isinstance(instance_ids, str) else instance_ids
        )
        with self._lock:
            self._entries[job_id] = JobAccessEntry(
                job_id=job_id,
                account_id=account_id,
                instance_ids=normalized_ids,
                access_mode=access_mode,
            )
            self._cancelled.pop(job_id, None)

    def unregister(self, job_id: str) -> None:
        """移除已完成或已结束的任务登记。"""
        with self._lock:
            self._entries.pop(job_id, None)
            self._cancelled.pop(job_id, None)

    def get(self, job_id: str) -> JobAccessEntry | None:
        """返回任务权限上下文。"""
        with self._lock:
            return self._entries.get(job_id)

    def cancel(self, job_id: str, reason: str) -> None:
        """标记单个任务为需要取消。"""
        with self._lock:
            if job_id in self._entries:
                self._cancelled[job_id] = reason

    def cancellation_reason(self, job_id: str) -> str | None:
        """返回任务取消原因。"""
        with self._lock:
            return self._cancelled.get(job_id)

    def cancel_for_account(self, account_id: str, reason: str) -> list[str]:
        """取消账户的全部登记任务并返回任务 ID。"""
        with self._lock:
            job_ids = [
                job_id
                for job_id, entry in self._entries.items()
                if entry.account_id == account_id
            ]
            for job_id in job_ids:
                self._cancelled[job_id] = reason
            return job_ids

    def cancel_for_instance(
        self,
        instance_id: str,
        reason: str,
        *,
        access_mode: JobAccessMode | None = None,
    ) -> list[str]:
        """取消实例相关任务，可按读写模式过滤。"""
        with self._lock:
            job_ids = [
                job_id
                for job_id, entry in self._entries.items()
                if instance_id in entry.instance_ids
                and (access_mode is None or entry.access_mode == access_mode)
            ]
            for job_id in job_ids:
                self._cancelled[job_id] = reason
            return job_ids

    def cancel_for_account_instance(
        self,
        account_id: str,
        instance_id: str,
        reason: str,
        *,
        access_mode: JobAccessMode | None = None,
    ) -> list[str]:
        """取消指定账户在指定实例上的任务，可按读写模式过滤。"""
        with self._lock:
            job_ids = [
                job_id
                for job_id, entry in self._entries.items()
                if entry.account_id == account_id
                and instance_id in entry.instance_ids
                and (access_mode is None or entry.access_mode == access_mode)
            ]
            for job_id in job_ids:
                self._cancelled[job_id] = reason
            return job_ids


job_access_registry = JobAccessRegistry()
