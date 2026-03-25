#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from datetime import datetime

from flask import jsonify

from config import taskLock, taskProcesses, taskStatus
from db import deleteTaskSnapshot
from db import fetchTaskSnapshot, listTaskEvents, listTaskSnapshots, pruneTaskSnapshots
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


def getTaskStatus(taskId):
    try:
        logMessage(f"收到任务状态查询请求: {taskId}", "INFO")
        with taskLock:
            if taskId in taskStatus:
                task_info = normalizeTaskRecord(taskId, taskStatus[taskId])
                logMessage(f"任务状态查询成功: {taskId}, 状态: {task_info.get('status', 'unknown')}", "INFO")
                return jsonify(task_info)

        persisted_task = fetchTaskSnapshot(taskId)
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
    with taskLock:
        in_memory_tasks = {
            task_id: buildSimplifiedTaskInfo(task_id, task_info)
            for task_id, task_info in taskStatus.items()
        }

    persisted_tasks = {}
    for task_info in listTaskSnapshots(limit=50):
        task_id = task_info.get("taskId") if isinstance(task_info, dict) else None
        if task_id:
            persisted_tasks[task_id] = buildSimplifiedTaskInfo(task_id, task_info)

    merged_tasks = dict(persisted_tasks)
    merged_tasks.update(in_memory_tasks)

    def extract_timestamp(task_id):
        try:
            match = re.search(r"\d+$", task_id)
            return int(match.group()) if match else 0
        except Exception:
            return 0

    sorted_task_ids = sorted(merged_tasks.keys(), key=extract_timestamp, reverse=True)[:50]
    tasks_with_ids = {task_id: merged_tasks[task_id] for task_id in sorted_task_ids}

    return jsonify({
        "tasks": tasks_with_ids,
        "count": len(tasks_with_ids),
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

        logMessage(f"任务停止失败: 任务不存在或无法停止 {taskId}", "WARNING")
        return jsonify({"error": "任务不存在或无法停止"}), 404
    except Exception as exc:
        logMessage(f"停止任务异常: {taskId}, 错误: {str(exc)}", "ERROR")
        return jsonify({"error": str(exc)}), 500


def deleteTask(taskId):
    try:
        logMessage(f"收到删除任务请求: {taskId}", "INFO")
        with taskLock:
            if taskId not in taskStatus:
                logMessage(f"删除任务失败: 任务不存在 {taskId}", "WARNING")
                return jsonify({"error": "任务不存在"}), 404

            if taskStatus[taskId].get("status") == "running":
                stopTaskProcess(taskId)
                taskStatus[taskId]["status"] = "stopped"
                taskStatus[taskId]["message"] = "任务已停止并删除"
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
            deleteTaskSnapshot(taskId)

        logMessage(f"任务删除成功: {taskId}", "INFO")
        return jsonify({
            "success": True,
            "message": "任务已删除",
            "taskId": taskId,
        })
    except Exception as exc:
        logMessage(f"删除任务异常: {taskId}, 错误: {str(exc)}", "ERROR")
        return jsonify({"error": str(exc)}), 500
