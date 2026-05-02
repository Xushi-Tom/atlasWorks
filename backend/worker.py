#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import signal
import time

from config import config
from db import claimQueuedBuildJob, initializeDatabase, isDatabaseEnabled, reconcileInterruptedTasks
from utils import logMessage
from vectorTilesOps import runVectorTileTask


_RUNNING = True


def _handle_shutdown(signum, frame):
    global _RUNNING
    _RUNNING = False
    logMessage(f"worker 收到退出信号: {signum}", "INFO")


def _dispatch_job(job):
    job_type = str(job.get("jobType") or "").strip().lower()
    snapshot = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    payload = snapshot.get("workerPayload") if isinstance(snapshot.get("workerPayload"), dict) else snapshot
    task_id = job.get("taskId") or payload.get("taskId") or snapshot.get("taskId")
    payload["workerId"] = config.get("worker", {}).get("id")

    if job_type in {"mvt_tiles", "geojson_tiles", "vector_tiles"}:
        runVectorTileTask(task_id, payload)
        return True

    logMessage(f"worker 不支持的任务类型: {job_type}", "WARNING")
    return False


def main():
    worker_config = config.get("worker", {})
    worker_id = str(worker_config.get("id") or "atlasworks-worker")
    poll_interval = max(1, int(worker_config.get("pollIntervalSeconds") or 2))
    job_types = worker_config.get("jobTypes") or []

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, _handle_shutdown)

    os.makedirs(config["logDir"], exist_ok=True)
    os.makedirs(config["tilesDir"], exist_ok=True)
    os.makedirs(config["dataSourceDir"], exist_ok=True)

    initializeDatabase()
    if not isDatabaseEnabled():
        raise RuntimeError("worker 模式需要启用 TF_DB_ENABLED=1")

    reconcileInterruptedTasks()
    logMessage(f"AtlasWorks worker 启动: {worker_id}, jobTypes={','.join(job_types) or '*'}", "INFO")

    while _RUNNING:
        job = claimQueuedBuildJob(worker_id, job_types=job_types)
        if not job:
            time.sleep(poll_interval)
            continue

        logMessage(f"worker 领取任务: {job.get('taskId')} ({job.get('jobType')})", "INFO")
        _dispatch_job(job)

    logMessage("AtlasWorks worker 已退出", "INFO")


if __name__ == "__main__":
    main()
