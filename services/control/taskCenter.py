#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from datetime import datetime

from flask import jsonify, request

from config import taskLock, taskProcesses, taskStatus
from db import countTableRows, deleteTaskSnapshot, syncTaskSnapshot
from db import fetchTaskSnapshot, listTaskEvents, listTaskSnapshots, pruneTaskSnapshots
from pagination import paginate_items, parse_pagination_args
from taskState import normalizeTaskRecord
from utils import logMessage, stopTaskProcess


def cleanupTasksByCount(maxTasks=100):
    """按数量清理任务，删除最旧的任务以控制内存使用。"""
    try:
        deleted_count = 0
        with taskLock:
            task_ids = list(taskStatus.keys())
            if len(task_ids) > maxTasks:
                task_ids.sort(key=lambda tid: taskStatus[tid].get("startTime", ""))
                to_delete = task_ids[:-maxTasks]

                for task_id in to_delete:
                    if task_id in taskProcesses:
                        try:
                            taskProcesses[task_id].terminate()
                            del taskProcesses[task_id]
                        except Exception:
                            pass

                    if task_id in taskStatus:
                        del taskStatus[task_id]

                deleted_count = len(to_delete)
                logMessage(f"清理了 {deleted_count} 个旧任务", "INFO")

        pruneTaskSnapshots(maxTasks)
        return deleted_count
    except Exception as exc:
        logMessage(f"清理任务失败: {exc}", "ERROR")
        return 0


def buildSimplifiedTaskInfo(taskId, taskInfo):
    if not isinstance(taskInfo, dict):
        return normalizeTaskRecord(taskId, {"status": "unknown"})

    taskInfo = normalizeTaskRecord(taskId, taskInfo)

    result = taskInfo.get("result")
    simplified_result = None
    if isinstance(result, dict):
        simplified_result = {
            "completedFiles": result.get("completedFiles", 0),
            "failedFiles": result.get("failedFiles", 0),
            "totalFiles": result.get("totalFiles", 0),
            "totalTerrainFiles": result.get("totalTerrainFiles", 0),
            "outputPath": result.get("outputPath"),
            "mergedOutputPath": result.get("mergedOutputPath"),
            "deletedNodataTiles": result.get("deletedNodataTiles", 0),
            "method": result.get("method"),
            "artifactId": result.get("artifactId"),
            "artifactType": result.get("artifactType"),
            "manifestFile": result.get("manifestFile"),
        }

    return {
        "taskId": taskId,
        "status": taskInfo.get("status"),
        "progress": taskInfo.get("progress"),
        "message": taskInfo.get("message"),
        "startTime": taskInfo.get("startTime"),
        "endTime": taskInfo.get("endTime"),
        "currentStage": taskInfo.get("currentStage"),
        "result": simplified_result,
        "stats": taskInfo.get("stats"),
        "files": taskInfo.get("files"),
    }


def _parse_datetime_value(value, end_of_day=False):
    raw_value = str(value or "").strip()
    if not raw_value:
        return None

    candidates = [raw_value]
    if len(raw_value) == 10 and raw_value.count("-") == 2:
        suffix = "23:59:59" if end_of_day else "00:00:00"
        candidates.insert(0, f"{raw_value} {suffix}")

    for candidate in candidates:
        normalized = candidate.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone().replace(tzinfo=None)
            return parsed.replace(microsecond=0)
        except ValueError:
            pass

        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue
    return None


def _matches_task_filters(task, keyword="", date_from=None, date_to=None, status_filter=""):
    task_start = _parse_datetime_value(task.get("startTime"))
    if date_from and (task_start is None or task_start < date_from):
        return False
    if date_to and (task_start is None or task_start > date_to):
        return False

    normalized_status = str(task.get("status") or "").strip().lower()
    if status_filter and normalized_status != status_filter:
        return False

    normalized_keyword = str(keyword or "").strip().lower()
    if not normalized_keyword:
        return True

    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    search_pool = [
        task.get("taskId"),
        task.get("status"),
        task.get("currentStage"),
        task.get("message"),
        result.get("outputPath"),
        result.get("mergedOutputPath"),
        result.get("artifactId"),
        result.get("artifactType"),
        result.get("method"),
    ]
    return any(normalized_keyword in str(item or "").lower() for item in search_pool)


def getTaskStatus(taskId):
    try:
        logMessage(f"收到任务状态查询请求: {taskId}", "INFO")
        persisted_task = fetchTaskSnapshot(taskId)
        if persisted_task:
            persisted_status = str(persisted_task.get("status") or "").lower()
            if persisted_status not in {"queued", ""}:
                logMessage(f"任务状态查询命中数据库快照: {taskId}", "INFO")
                return jsonify(normalizeTaskRecord(taskId, persisted_task))

        with taskLock:
            if taskId in taskStatus:
                task_info = normalizeTaskRecord(taskId, taskStatus[taskId])
                logMessage(f"任务状态查询成功: {taskId}, 状态: {task_info.get('status', 'unknown')}", "INFO")
                return jsonify(task_info)

        if persisted_task:
            logMessage(f"任务状态查询命中数据库快照: {taskId}", "INFO")
            return jsonify(normalizeTaskRecord(taskId, persisted_task))

        logMessage(f"任务状态查询失败: 任务不存在 {taskId}", "WARNING")
        return jsonify({"error": "任务不存在"}), 404
    except Exception as exc:
        logMessage(f"任务状态查询异常: {taskId}, 错误: {str(exc)}", "ERROR")
        return jsonify({"error": str(exc)}), 500


def listTaskEventStream(taskId):
    try:
        events = listTaskEvents(taskId, limit=200)
        if events:
            return jsonify({
                "success": True,
                "taskId": taskId,
                "source": "database",
                "count": len(events),
                "events": events,
            })

        with taskLock:
            task_info = normalizeTaskRecord(taskId, taskStatus.get(taskId, {}))
            process_log = list(task_info.get("processLog", [])) if task_info else []

        fallback_events = []
        for index, item in enumerate(reversed(process_log), 1):
            if not isinstance(item, dict):
                continue
            fallback_events.append(
                {
                    "id": index,
                    "eventType": f"processLog.{item.get('status', 'info')}",
                    "eventAt": item.get("timestamp"),
                    "details": item,
                }
            )

        if fallback_events:
            return jsonify({
                "success": True,
                "taskId": taskId,
                "source": "memory",
                "count": len(fallback_events),
                "events": fallback_events,
            })

        return jsonify({"error": "任务不存在或暂无事件"}), 404
    except Exception as exc:
        logMessage(f"读取任务事件失败: {taskId} - {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500


def listTasks():
    page, page_size = parse_pagination_args(request.args, default_page_size=10, max_page_size=500)
    keyword = request.args.get("keyword", "")
    status_filter = str(request.args.get("status", "")).strip().lower()
    date_from = _parse_datetime_value(request.args.get("dateFrom"))
    date_to = _parse_datetime_value(request.args.get("dateTo"), end_of_day=True)

    with taskLock:
        in_memory_tasks = {
            task_id: buildSimplifiedTaskInfo(task_id, task_info)
            for task_id, task_info in taskStatus.items()
        }

    persisted_tasks = {}
    persisted_count = countTableRows("tf_build_jobs")
    for task_info in listTaskSnapshots(limit=max(50, persisted_count or 0)):
        task_id = task_info.get("taskId") if isinstance(task_info, dict) else None
        if task_id:
            persisted_tasks[task_id] = buildSimplifiedTaskInfo(task_id, task_info)

    merged_tasks = dict(persisted_tasks)
    merged_tasks.update(in_memory_tasks)

    def extract_start_time(task_id):
        task = merged_tasks.get(task_id, {})
        parsed = _parse_datetime_value(task.get("startTime"))
        return parsed if parsed is not None else datetime.min

    def task_sort_key(task_id):
        task = merged_tasks.get(task_id, {})
        normalized_status = str(task.get("status") or "").strip().lower()
        running_rank = 0 if normalized_status == "running" else 1
        start_time = extract_start_time(task_id)
        if start_time == datetime.min:
            start_rank = float("inf")
        else:
            start_rank = -(
                start_time.toordinal() * 86400
                + start_time.hour * 3600
                + start_time.minute * 60
                + start_time.second
            )
        return (running_rank, start_rank)

    sorted_task_ids = sorted(merged_tasks.keys(), key=task_sort_key)
    filtered_tasks = [
        merged_tasks[task_id]
        for task_id in sorted_task_ids
        if _matches_task_filters(
            merged_tasks[task_id],
            keyword=keyword,
            date_from=date_from,
            date_to=date_to,
            status_filter=status_filter,
        )
    ]
    status_summary = {}
    for task in filtered_tasks:
        status = str(task.get("status") or "unknown").strip().lower() or "unknown"
        status_summary[status] = status_summary.get(status, 0) + 1
    paged_tasks, pagination = paginate_items(filtered_tasks, page, page_size)
    tasks_with_ids = {task["taskId"]: task for task in paged_tasks if task.get("taskId")}

    return jsonify({
        "tasks": tasks_with_ids,
        "stats": {
            "total": len(filtered_tasks),
            "running": status_summary.get("running", 0),
            "queued": status_summary.get("queued", 0),
            "completed": status_summary.get("completed", 0),
            "failed": status_summary.get("failed", 0),
            "stopped": status_summary.get("stopped", 0),
            "unknown": status_summary.get("unknown", 0),
            "byStatus": status_summary,
        },
        **pagination,
    })


def cleanupTasks():
    try:
        cleanupTasksByCount()
        with taskLock:
            return jsonify({
                "success": True,
                "message": "任务清理完成",
                "remainingTasks": len(taskStatus),
            })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def stopTask(taskId):
    try:
        logMessage(f"收到停止任务请求: {taskId}", "INFO")
        success = stopTaskProcess(taskId)
        if success:
            with taskLock:
                if taskId in taskStatus:
                    taskStatus[taskId]["status"] = "stopped"
                    taskStatus[taskId]["message"] = "任务已停止"
                    taskStatus[taskId]["endTime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            logMessage(f"任务停止成功: {taskId}", "INFO")
            return jsonify({
                "success": True,
                "message": "任务已停止",
                "taskId": taskId,
            })

        persisted_task = fetchTaskSnapshot(taskId)
        if persisted_task and persisted_task.get("status") in {"queued", "running"}:
            persisted_task["status"] = "stopped"
            persisted_task["message"] = "任务已停止"
            persisted_task["endTime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            persisted_task["currentStage"] = "已停止"
            syncTaskSnapshot(taskId, persisted_task)
            return jsonify({
                "success": True,
                "message": "任务已标记为停止",
                "taskId": taskId,
                "remote": True,
            })

        logMessage(f"任务停止失败: 任务不存在或无法停止 {taskId}", "WARNING")
        return jsonify({"error": "任务不存在或无法停止"}), 404
    except Exception as exc:
        logMessage(f"停止任务异常: {taskId}, 错误: {str(exc)}", "ERROR")
        return jsonify({"error": str(exc)}), 500


def deleteTask(taskId):
    try:
        logMessage(f"收到删除任务请求: {taskId}", "INFO")
        deleted_from_memory = False
        deleted_from_database = False

        with taskLock:
            task_info = taskStatus.get(taskId)
            if task_info is not None:
                if task_info.get("status") == "running":
                    stopTaskProcess(taskId)
                    task_info["status"] = "stopped"
                    task_info["message"] = "任务已停止并删除"
                    logMessage(f"正在运行的任务 {taskId} 已标记为停止", "INFO")

                try:
                    if taskId in taskProcesses:
                        process_or_thread = taskProcesses[taskId]
                        if hasattr(process_or_thread, "terminate"):
                            process_or_thread.terminate()
                        del taskProcesses[taskId]
                        logMessage(f"任务进程已终止: {taskId}", "INFO")
                except Exception as exc:
                    logMessage(f"终止任务进程时出错: {taskId}, 错误: {str(exc)}", "WARNING")

                del taskStatus[taskId]
                deleted_from_memory = True

        # 列表会合并内存与数据库任务，因此删除时需要同时覆盖数据库快照。
        deleted_from_database = deleteTaskSnapshot(taskId)

        if not deleted_from_memory and not deleted_from_database:
            logMessage(f"删除任务失败: 任务不存在 {taskId}", "WARNING")
            return jsonify({"error": "任务不存在"}), 404

        logMessage(
            f"任务删除成功: {taskId} (memory={deleted_from_memory}, database={deleted_from_database})",
            "INFO",
        )
        return jsonify({
            "success": True,
            "message": "任务已删除",
            "taskId": taskId,
            "deletedFromMemory": deleted_from_memory,
            "deletedFromDatabase": deleted_from_database,
        })
    except Exception as exc:
        logMessage(f"删除任务异常: {taskId}, 错误: {str(exc)}", "ERROR")
        return jsonify({"error": str(exc)}), 500
