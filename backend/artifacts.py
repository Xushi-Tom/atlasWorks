#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import subprocess
from datetime import datetime

from config import taskLock, taskStatus
from db import appendJobEvent, syncTaskSnapshot, upsertArtifactRecord
from taskState import normalizeTaskRecord
from utils import logMessage


_TOOL_VERSION_CACHE = {}


def _run_command(command, timeout=15):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, (result.stdout or result.stderr or "").strip()
    except Exception as exc:
        return False, str(exc)


def _get_tool_version(command_key, command):
    if command_key not in _TOOL_VERSION_CACHE:
        success, output = _run_command(command)
        _TOOL_VERSION_CACHE[command_key] = output if success or output else "unknown"
    return _TOOL_VERSION_CACHE[command_key]


def _safe_snapshot(task_snapshot):
    return json.loads(json.dumps(task_snapshot or {}, ensure_ascii=False, default=str))


def _artifact_type_for(job_type):
    mapping = {
        "terrain_tiles": "terrain",
        "terrain": "terrain",
        "indexed_tiles": "xyz_tiles",
        "map_tiles": "xyz_tiles",
        "tile_convert": "xyz_tiles",
    }
    return mapping.get(str(job_type or "").strip().lower(), "unknown")


def _output_format_for(job_type, task_snapshot):
    normalized = str(job_type or "").strip().lower()
    result = task_snapshot.get("result", {}) if isinstance(task_snapshot, dict) else {}
    if normalized in ("terrain", "terrain_tiles"):
        return "quantized-mesh"
    render_options = result.get("renderOptions", {})
    if isinstance(render_options, dict) and render_options.get("imageFormat"):
        return str(render_options["imageFormat"])
    return "xyz"


def _collect_output_stats(output_path):
    file_count = 0
    total_size = 0
    if not output_path or not os.path.exists(output_path):
        return {"fileCount": 0, "totalSize": 0}

    for root, _, files in os.walk(output_path):
        for filename in files:
            full_path = os.path.join(root, filename)
            try:
                file_count += 1
                total_size += os.path.getsize(full_path)
            except OSError:
                continue

    return {"fileCount": file_count, "totalSize": total_size}


def writeArtifactManifest(task_id, task_snapshot, source_files=None, build_parameters=None):
    snapshot = _safe_snapshot(task_snapshot)
    result = snapshot.get("result", {}) if isinstance(snapshot, dict) else {}
    output_path = result.get("mergedOutputPath") or result.get("outputPath")
    if not output_path:
        return None

    os.makedirs(output_path, exist_ok=True)

    requested_job_type = ""
    if isinstance(build_parameters, dict):
        requested_job_type = str(build_parameters.get("jobType", "")).strip()
    job_type = requested_job_type or result.get("method") or snapshot.get("jobType") or "unknown"
    artifact_id = f"artifact-{task_id}"
    artifact_type = _artifact_type_for(job_type)
    output_format = _output_format_for(job_type, snapshot)
    output_stats = _collect_output_stats(output_path)
    manifest_path = os.path.join(output_path, "manifest.json")

    manifest = {
        "manifestVersion": "1.0.0",
        "artifactId": artifact_id,
        "buildJobId": task_id,
        "generatedAt": datetime.now().isoformat(),
        "generator": {
            "name": "AtlasWorks",
            "gdalVersion": _get_tool_version("gdalinfo", ["gdalinfo", "--version"]),
            "ctbVersion": _get_tool_version("ctb-tile", ["ctb-tile", "--version"]),
        },
        "artifact": {
            "type": artifact_type,
            "format": output_format,
            "outputPath": output_path,
            "bounds": result.get("bounds"),
            "fileCount": output_stats["fileCount"],
            "totalSize": output_stats["totalSize"],
            "status": snapshot.get("status"),
        },
        "task": {
            "id": task_id,
            "status": snapshot.get("status"),
            "currentStage": snapshot.get("currentStage"),
            "message": snapshot.get("message"),
            "startTime": snapshot.get("startTime"),
            "endTime": snapshot.get("endTime"),
        },
        "sources": list(source_files or []),
        "buildParameters": build_parameters or {},
        "resultSummary": result,
    }

    with open(manifest_path, "w", encoding="utf-8") as manifest_file:
        json.dump(manifest, manifest_file, ensure_ascii=False, indent=2)

    metadata = {
        "manifestPath": manifest_path,
        "sourceFiles": list(source_files or []),
        "buildParameters": build_parameters or {},
        "resultSummary": result,
        "jobStatus": snapshot.get("status"),
    }
    upsertArtifactRecord(
        artifact_id=artifact_id,
        build_job_id=task_id,
        artifact_type=artifact_type,
        output_path=output_path,
        output_format=output_format,
        bounds=result.get("bounds"),
        metadata=metadata,
    )
    appendJobEvent(
        task_id,
        "artifact.manifest_written",
        {
            "artifactId": artifact_id,
            "artifactType": artifact_type,
            "manifestPath": manifest_path,
            "outputPath": output_path,
            "fileCount": output_stats["fileCount"],
            "totalSize": output_stats["totalSize"],
        },
    )

    logMessage(f"产物 manifest 已生成: {manifest_path}", "INFO")
    return {
        "artifactId": artifact_id,
        "artifactType": artifact_type,
        "manifestPath": manifest_path,
        "outputPath": output_path,
        "fileCount": output_stats["fileCount"],
        "totalSize": output_stats["totalSize"],
    }


def finalizeTaskArtifact(task_id, source_files=None, build_parameters=None):
    try:
        with taskLock:
            task_snapshot = _safe_snapshot(taskStatus.get(task_id, {}))
        if not task_snapshot or task_snapshot.get("status") != "completed":
            return None

        artifact_info = writeArtifactManifest(
            task_id,
            task_snapshot,
            source_files=source_files,
            build_parameters=build_parameters,
        )
        if not artifact_info:
            return None

        snapshot_for_sync = None
        with taskLock:
            current_task = taskStatus.get(task_id)
            if not current_task:
                return artifact_info
            current_task.setdefault("result", {})
            current_task["result"]["artifactId"] = artifact_info["artifactId"]
            current_task["result"]["artifactType"] = artifact_info["artifactType"]
            current_task["result"]["manifestFile"] = artifact_info["manifestPath"]
            current_task["result"]["artifactStats"] = {
                "fileCount": artifact_info["fileCount"],
                "totalSize": artifact_info["totalSize"],
            }
            snapshot_for_sync = _safe_snapshot(current_task)

        if snapshot_for_sync:
            syncTaskSnapshot(task_id, normalizeTaskRecord(task_id, snapshot_for_sync))
        return artifact_info
    except Exception as exc:
        logMessage(f"生成产物 manifest 失败 {task_id}: {exc}", "WARNING")
        return None
