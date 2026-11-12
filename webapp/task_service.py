"""FIFO print jobs and thread-safe, replayable progress across both ports."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import json
import threading
import time
import uuid

from fastapi import HTTPException
from fastapi.responses import StreamingResponse


@dataclass
class Task:
    total: int
    events: list[dict] = field(default_factory=list)
    cancelled: bool = False
    finished_at: float = 0


_tasks: dict[str, Task] = {}
_lock = threading.RLock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="label-print")
_accepting = True
MAX_TASKS = 200
RETENTION_SECONDS = 3600


def submit(function, total: int, *args, **kwargs) -> str:
    with _lock:
        now = time.monotonic()
        for key in list(_tasks):
            record = _tasks[key]
            if record.finished_at and now - record.finished_at > RETENTION_SECONDS:
                del _tasks[key]
        while len(_tasks) >= MAX_TASKS:
            completed = next((key for key, task in _tasks.items() if task.finished_at), None)
            if completed is None:
                raise HTTPException(429, "打印队列已满，请稍后重试")
            del _tasks[completed]
        if not _accepting:
            raise HTTPException(503, "服务正在停止")
        task_id = uuid.uuid4().hex
        record = Task(total=total)
        _tasks[task_id] = record

        def run():
            current = 0
            last_error = None

            def progress(current, total, status, item=None, error=None):
                publish(task_id, current, total, status, item, error)
            try:
                if is_cancelled(task_id):
                    progress(0, total, "cancelled")
                else:
                    function(task_id, *args, on_progress=progress, **kwargs)
            except Exception as exc:
                with _lock:
                    current = next((event["current"] for event in reversed(record.events)
                                    if event["status"] == "done"), 0)
                last_error = str(exc)
                progress(current, total, "error", error=last_error)
            finally:
                with _lock:
                    terminal = bool(record.finished_at)
                if not terminal:
                    progress(current, total, "finished", error=last_error)

        _executor.submit(run)
        return task_id


def publish(task_id, current, total, status, item=None, error=None):
    with _lock:
        task = _tasks.get(task_id)
        if task is None:
            return
        if task.finished_at:
            return
        task.events.append({"taskId": task_id, "current": current, "total": total,
                            "status": status, "item": item, "error": error})
        if status in ("finished", "cancelled"):
            task.finished_at = time.monotonic()


def cancel(task_id: str):
    with _lock:
        if task_id not in _tasks:
            raise HTTPException(404, "任务不存在或已过期")
        if not _tasks[task_id].finished_at:
            _tasks[task_id].cancelled = True


def is_cancelled(task_id: str) -> bool:
    with _lock:
        task = _tasks.get(task_id)
        return bool(task and task.cancelled)


def run_batch(task_id, items, printer_name, draw, on_progress):
    from . import printer_service
    total = len(items)
    completed = 0
    if on_progress is None:
        on_progress = lambda *args: None
    with printer_service.session() as api:
        if is_cancelled(task_id):
            on_progress(0, total, "cancelled", None, None)
            return
        if not api.open_printer(name=printer_name):
            raise RuntimeError(f"无法连接打印机: {printer_name}")
        try:
            for item in items:
                if is_cancelled(task_id):
                    on_progress(completed, total, "cancelled", item, None)
                    return
                on_progress(completed + 1, total, "printing", item, None)
                draw(api, item)
                if is_cancelled(task_id):
                    on_progress(completed, total, "cancelled", item, None)
                    return
                completed += 1
                on_progress(completed, total, "done", item, None)
                time.sleep(0.3)
        finally:
            api.close_printer()
    on_progress(completed, total, "finished", None, None)


def stream(task_id: str) -> StreamingResponse:
    with _lock:
        if task_id not in _tasks:
            raise HTTPException(404, "任务不存在或已过期")
        task = _tasks[task_id]

    async def events():
        cursor = 0
        last_heartbeat = time.monotonic()
        while True:
            with _lock:
                batch = task.events[cursor:]
                terminal = bool(task.finished_at)
            for item in batch:
                cursor += 1
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            if terminal:
                return
            if time.monotonic() - last_heartbeat >= 15:
                yield ": keep-alive\n\n"
                last_heartbeat = time.monotonic()
            await asyncio.sleep(0.1)

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def shutdown():
    global _accepting
    with _lock:
        _accepting = False
        for task in _tasks.values():
            if not task.finished_at:
                task.cancelled = True
    _executor.shutdown(wait=True)
