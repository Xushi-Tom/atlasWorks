#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import copy
from datetime import datetime


def _safe_copy(value, default):
    try:
        return copy.deepcopy(value)
    except Exception:
        return copy.deepcopy(default)


def _default_stats():
    return {
        "totalTiles": 0,
        "processedTiles": 0,
        "failedTiles": 0,
        "remainingTiles": 0,
        "averageSpeed": 0,
        "successRate": "0%",
    }


def _default_files():
    return {
        "total": 0,
        "completed": 0,
        "failed": 0,
        "current": None,
    }


def createTaskRecord(
    task_id=None,
    status="queued",
    progress=0,
    message="",
    start_time=None,
    end_time=None,
    current_stage=None,
    process_log=None,
    result=None,
    stats=None,
    files=None,
    processing_info=None,
    error=None,
    extra=None,
):
    record = {
        "taskId": task_id,
        "status": status,
        "progress": max(0, min(int(progress or 0), 100)),
        "message": message or "",
        "startTime": start_time,
        "endTime": end_time,
        "currentStage": current_stage or "",
        "processLog": _safe_copy(process_log or [], []),
        "result": _safe_copy(result or {}, {}),
        "stats": _safe_copy(stats or _default_stats(), _default_stats()),
        "files": _safe_copy(files or _default_files(), _default_files()),
        "processingInfo": _safe_copy(processing_info or {}, {}),
    }
    if error:
        record["error"] = str(error)
    if extra and isinstance(extra, dict):
        record.update(_safe_copy(extra, {}))
    return record


def appendTaskLog(record, stage, status, message, progress=None, **details):
    if not isinstance(record, dict):
        return record
    record.setdefault("processLog", [])
    entry = {
        "stage": stage,
        "status": status,
        "message": message,
        "timestamp": datetime.now().isoformat(),
        "progress": record.get("progress", 0) if progress is None else progress,
    }
    if details:
        entry.update(details)
    record["processLog"].append(entry)
    return record


def normalizeTaskRecord(task_id, payload):
    data = _safe_copy(payload or {}, {})
    if not isinstance(data, dict):
        data = {}

    normalized = createTaskRecord(
        task_id=task_id or data.get("taskId"),
        status=data.get("status", "unknown"),
        progress=data.get("progress", 0),
        message=data.get("message", ""),
        start_time=data.get("startTime"),
        end_time=data.get("endTime"),
        current_stage=data.get("currentStage") or data.get("stage") or "",
        process_log=data.get("processLog", []),
        result=data.get("result", {}),
        stats=data.get("stats") if isinstance(data.get("stats"), dict) else _default_stats(),
        files=data.get("files") if isinstance(data.get("files"), dict) else _default_files(),
        processing_info=data.get("processingInfo", {}),
        error=data.get("error"),
        extra={},
    )

    normalized["taskId"] = normalized.get("taskId") or task_id

    top_level_total = data.get("totalTiles")
    top_level_processed = data.get("processedTiles")
    top_level_failed = data.get("failedTiles")
    if isinstance(top_level_total, int):
        normalized["stats"]["totalTiles"] = top_level_total
    if isinstance(top_level_processed, int):
        normalized["stats"]["processedTiles"] = top_level_processed
    if isinstance(top_level_failed, int):
        normalized["stats"]["failedTiles"] = top_level_failed

    result = normalized.get("result", {})
    if isinstance(result, dict):
        if isinstance(result.get("totalTiles"), int):
            normalized["stats"]["totalTiles"] = result.get("totalTiles")
        if isinstance(result.get("processedTiles"), int):
            normalized["stats"]["processedTiles"] = result.get("processedTiles")
        if isinstance(result.get("failedTiles"), int):
            normalized["stats"]["failedTiles"] = result.get("failedTiles")

    total_tiles = normalized["stats"].get("totalTiles", 0) or 0
    processed_tiles = normalized["stats"].get("processedTiles", 0) or 0
    failed_tiles = normalized["stats"].get("failedTiles", 0) or 0
    remaining_tiles = max(0, total_tiles - processed_tiles - failed_tiles)
    normalized["stats"]["remainingTiles"] = normalized["stats"].get("remainingTiles", remaining_tiles)
    if total_tiles > 0 and "successRate" not in normalized["stats"]:
        normalized["stats"]["successRate"] = f"{processed_tiles / total_tiles * 100:.1f}%"

    normalized["processLog"] = normalized.get("processLog") or []
    normalized["result"] = normalized.get("result") or {}
    normalized["files"] = normalized.get("files") or _default_files()
    normalized["processingInfo"] = normalized.get("processingInfo") or {}
    return normalized
