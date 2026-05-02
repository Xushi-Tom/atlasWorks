#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import threading
from datetime import datetime

try:
    import psutil
    psutilAvailable = True
except ImportError:
    psutilAvailable = False
    print("警告: psutil不可用，将使用默认设置")


def _as_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _env(*names, default=None):
    for name in names:
        value = os.environ.get(name)
        if value is not None:
            return value
    return default

# 全局配置
config = {
    "host": "0.0.0.0",
    "port": _as_int(os.environ.get("PORT"), 18000),
    "debug": _as_bool(os.environ.get("DEBUG"), False),
    "publicBaseUrl": _env("ATLASWORKS_PUBLIC_BASE_URL", "TERRAFORGE_PUBLIC_BASE_URL", default=""),
    "publicBaseMode": _env("ATLASWORKS_PUBLIC_BASE_MODE", "TERRAFORGE_PUBLIC_BASE_MODE", default="auto"),
    "publicBaseHost": _env("ATLASWORKS_PUBLIC_BASE_HOST", "TERRAFORGE_PUBLIC_BASE_HOST", default=""),
    "publicBasePort": _as_int(_env("ATLASWORKS_PUBLIC_BASE_PORT", "TERRAFORGE_PUBLIC_BASE_PORT"), 0),
    "publicBaseScheme": _env("ATLASWORKS_PUBLIC_BASE_SCHEME", "TERRAFORGE_PUBLIC_BASE_SCHEME", default=""),
    "docsAuthUser": _env("ATLASWORKS_DOCS_USER", "TERRAFORGE_DOCS_USER", default=""),
    "docsAuthPassword": _env("ATLASWORKS_DOCS_PASSWORD", "TERRAFORGE_DOCS_PASSWORD", default="Su19960624Xhi"),
    "publicationRequireDb": _as_bool(os.environ.get("TF_PUBLICATION_REQUIRE_DB"), True),
    "dataSourceDir": _env("ATLASWORKS_DATA_SOURCE_DIR", "TERRAFORGE_DATA_SOURCE_DIR", default="/app/dataSource"),
    "dataSourceHostDir": _env("ATLASWORKS_DATA_SOURCE_HOST_DIR", default=""),
    "tilesDir": _env("ATLASWORKS_TILES_DIR", "TERRAFORGE_TILES_DIR", default="/app/tiles"),
    "tilesHostDir": _env("ATLASWORKS_TILES_HOST_DIR", default=""),
    "logDir": _env("ATLASWORKS_LOG_DIR", "TERRAFORGE_LOG_DIR", default="/app/log"),
    "logHostDir": _env("ATLASWORKS_LOG_HOST_DIR", default=""),
    "remoteSourceTimeoutSeconds": max(
        5,
        _as_int(_env("ATLASWORKS_REMOTE_SOURCE_TIMEOUT", "TERRAFORGE_REMOTE_SOURCE_TIMEOUT"), 45),
    ),
    "remoteSourceRetryCount": max(
        0,
        _as_int(_env("ATLASWORKS_REMOTE_SOURCE_RETRIES", "TERRAFORGE_REMOTE_SOURCE_RETRIES"), 1),
    ),
    "remoteSourceDockerHostFallback": _as_bool(
        _env("ATLASWORKS_REMOTE_SOURCE_DOCKER_HOST_FALLBACK", "TERRAFORGE_REMOTE_SOURCE_DOCKER_HOST_FALLBACK"),
        True,
    ),
    "remoteSourceDockerHostFallbackHost": _env(
        "ATLASWORKS_REMOTE_SOURCE_DOCKER_HOST",
        "TERRAFORGE_REMOTE_SOURCE_DOCKER_HOST",
        default="host.docker.internal",
    ),
    "remoteSourceHostAliases": _env(
        "ATLASWORKS_REMOTE_SOURCE_HOST_ALIASES",
        "TERRAFORGE_REMOTE_SOURCE_HOST_ALIASES",
        default="",
    ),
    "maxThreads": psutil.cpu_count() if psutilAvailable else 4,
    "defaultMemoryLimit": "8g",
    "supportedFormats": [
        ".tif",
        ".tiff",
        ".png",
        ".jpg",
        ".jpeg",
        ".txt",
        ".las",
        ".laz",
        ".geojson",
        ".gpkg",
        ".shp",
        ".dbf",
        ".prj",
        ".cpg",
        ".obj",
        ".osgb",
        ".glb",
    ],
    "taskCleanup": {
        "maxTasks": 100
    },
    "database": {
        "enabled": _as_bool(os.environ.get("TF_DB_ENABLED"), False),
        "host": os.environ.get("TF_DB_HOST", "localhost"),
        "port": _as_int(os.environ.get("TF_DB_PORT"), 25432),
        "name": os.environ.get("TF_DB_NAME", "atlasworks"),
        "user": os.environ.get("TF_DB_USER", "postgres"),
        "password": os.environ.get("TF_DB_PASSWORD", "atlasworks"),
        "connectTimeout": _as_int(os.environ.get("TF_DB_CONNECT_TIMEOUT"), 3),
        "sslmode": os.environ.get("TF_DB_SSLMODE", "prefer"),
    },
    "taskSync": {
        "enabled": _as_bool(os.environ.get("TF_TASK_SYNC_ENABLED"), True),
        "intervalSeconds": max(1, _as_int(os.environ.get("TF_TASK_SYNC_INTERVAL"), 2)),
    },
    "taskDispatch": _env("ATLASWORKS_TASK_DISPATCH", default="inline"),
    "worker": {
        "id": _env("ATLASWORKS_WORKER_ID", default="atlasworks-worker"),
        "pollIntervalSeconds": max(1, _as_int(os.environ.get("ATLASWORKS_WORKER_POLL_INTERVAL"), 2)),
        "jobTypes": [
            item.strip()
            for item in _env("ATLASWORKS_WORKER_JOB_TYPES", default="mvt_tiles,geojson_tiles,vector_tiles").split(",")
            if item.strip()
        ],
    },
}

# 任务状态管理
taskStatus = {}
taskProcesses = {}
taskStopFlags = {}
taskLock = threading.Lock()

def getConfig():
    """获取全局配置"""
    return config

def getTaskStatus():
    """获取任务状态"""
    return taskStatus

def getTaskProcesses():
    """获取任务进程"""
    return taskProcesses

def getTaskStopFlags():
    """获取任务停止标记"""
    return taskStopFlags

def getTaskLock():
    """获取任务锁"""
    return taskLock 
