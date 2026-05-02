#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import signal
import time

from flask import Flask

from config import config, taskLock, taskStatus
from db import claimQueuedBuildJob, initializeDatabase, isDatabaseEnabled, reconcileInterruptedTasks, startTaskSyncWorker
from indexedTilesOps import createIndexedTiles
from utils import logMessage


_RUNNING = True
_APP = Flask(__name__)


def _handle_shutdown(signum, frame):
    global _RUNNING
    _RUNNING = False
    logMessage(f"栅格切片 worker 收到退出信号: {signum}", "INFO")


def _worker_payload(job):
    snapshot = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    extra = snapshot.get("extra") if isinstance(snapshot.get("extra"), dict) else {}
    payload = snapshot.get("workerPayload") if isinstance(snapshot.get("workerPayload"), dict) else None
    if payload is None:
        payload = extra.get("workerPayload") if isinstance(extra.get("workerPayload"), dict) else snapshot
    payload = dict(payload or {})
    payload["taskId"] = job.get("taskId") or payload.get("taskId") or snapshot.get("taskId")
    payload["workerId"] = config.get("worker", {}).get("id")
    payload["_workerRun"] = True
    payload["_runSynchronously"] = True
    return payload


def _dispatch_job(job):
    job_type = str(job.get("jobType") or "").strip().lower()
    try:
        if job_type in {"indexed_tiles", "map_tiles"}:
            with _APP.test_request_context(json=_worker_payload(job)):
                createIndexedTiles()
            return True
    except Exception as exc:
        logMessage(f"栅格切片 worker 执行任务失败: {job.get('taskId')} - {exc}", "ERROR")
        return False

    logMessage(f"栅格切片 worker 当前尚未接入该任务类型: {job_type}", "WARNING")
    return False


def main():
    worker_config = config.get("worker", {})
    worker_id = str(worker_config.get("id") or "atlasworks-raster-worker")
    poll_interval = max(1, int(worker_config.get("pollIntervalSeconds") or 2))
    job_types = worker_config.get("jobTypes") or []

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, _handle_shutdown)

    os.makedirs(config["logDir"], exist_ok=True)
    os.makedirs(config["tilesDir"], exist_ok=True)
    os.makedirs(config["dataSourceDir"], exist_ok=True)
    if str(os.environ.get("ATLASWORKS_WORKER_SKIP_DB_INIT", "")).strip().lower() not in {"1", "true", "yes", "on"}:
        initializeDatabase()
    if not isDatabaseEnabled():
        raise RuntimeError("worker 模式需要启用 TF_DB_ENABLED=1")

    reconcileInterruptedTasks()
    startTaskSyncWorker(taskStatus, taskLock)
    logMessage(f"AtlasWorks 栅格切片 worker 启动: {worker_id}, jobTypes={','.join(job_types) or '*'}", "INFO")

    while _RUNNING:
        job = claimQueuedBuildJob(worker_id, job_types=job_types)
        if not job:
            time.sleep(poll_interval)
            continue

        logMessage(f"栅格切片 worker 领取任务: {job.get('taskId')} ({job.get('jobType')})", "INFO")
        _dispatch_job(job)
        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
