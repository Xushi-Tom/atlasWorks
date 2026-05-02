#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import signal
import time

from config import config
from db import initializeDatabase, isDatabaseEnabled
from utils import logMessage


_RUNNING = True


def _handle_shutdown(signum, frame):
    global _RUNNING
    _RUNNING = False
    logMessage(f"栅格切片 worker 收到退出信号: {signum}", "INFO")


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
    initializeDatabase()
    if not isDatabaseEnabled():
        raise RuntimeError("worker 模式需要启用 TF_DB_ENABLED=1")

    logMessage(
        f"AtlasWorks 栅格切片 worker 启动: {worker_id}, jobTypes={','.join(job_types) or '*'}；"
        "当前仅作为独立服务边界运行，任务执行仍由控制面接入",
        "INFO",
    )

    while _RUNNING:
        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
