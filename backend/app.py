#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import atexit
import os
import signal
import threading

from flask import Flask, request
from flask_cors import CORS

from api_response import build_json_response, should_wrap_json_response
from config import config, taskLock, taskStatus
from db import flushTaskSnapshots, initializeDatabase, reconcileInterruptedTasks, startTaskSyncWorker
from routeRegistry import registerRoutes
from utils import logMessage


def _resolve_static_folder():
    base_dir = os.path.abspath(os.path.dirname(__file__))
    configured_static_dir = str(os.environ.get("ATLASWORKS_STATIC_DIR", "")).strip()
    candidate_dirs = [
        configured_static_dir,
        os.path.join(base_dir, "static"),
        os.path.abspath(os.path.join(base_dir, "..", "frontend", "dist")),
    ]

    for candidate in candidate_dirs:
        if candidate and os.path.isdir(candidate):
            return candidate
    return candidate_dirs[-1]


app = Flask(__name__, static_folder=_resolve_static_folder(), static_url_path="/static")
CORS(
    app,
    resources={
        r"/api/*": {
            "origins": "*",
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
        },
        r"/published": {
            "origins": "*",
            "methods": ["GET", "HEAD", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization", "Range"],
        },
        r"/published/*": {
            "origins": "*",
            "methods": ["GET", "HEAD", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization", "Range"],
        },
        r"/publication-assets": {
            "origins": "*",
            "methods": ["GET", "HEAD", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization", "Range"],
        },
        r"/publication-assets/.*": {
            "origins": "*",
            "methods": ["GET", "HEAD", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization", "Range"],
        },
        r"/wmts": {
            "origins": "*",
            "methods": ["GET", "HEAD", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
        },
    },
)
app.config["JSON_AS_ASCII"] = False
app.json.ensure_ascii = False

_bootstrap_lock = threading.Lock()
_bootstrap_done = False
_shutdown_hooks_registered = False


def flushTaskSnapshotsNow(reason="manual"):
    try:
        flushTaskSnapshots(taskStatus, taskLock, reason=reason)
    except Exception as exc:
        logMessage(f"任务快照落库触发失败: {exc}", "WARNING")


def _installSignalHandler(signum):
    previous_handler = signal.getsignal(signum)

    def _handler(received_signum, frame):
        flushTaskSnapshotsNow(reason=f"signal:{received_signum}")
        if callable(previous_handler):
            previous_handler(received_signum, frame)
        elif previous_handler == signal.SIG_DFL:
            raise SystemExit(0)

    signal.signal(signum, _handler)


def registerShutdownHooks():
    global _shutdown_hooks_registered
    if _shutdown_hooks_registered:
        return
    _shutdown_hooks_registered = True

    atexit.register(lambda: flushTaskSnapshotsNow(reason="atexit"))
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            _installSignalHandler(signum)
        except Exception as exc:
            logMessage(f"注册退出信号处理器失败({signum}): {exc}", "WARNING")


def bootstrapApplication():
    global _bootstrap_done
    with _bootstrap_lock:
        if _bootstrap_done:
            return

        os.makedirs(config["logDir"], exist_ok=True)
        os.makedirs(config["tilesDir"], exist_ok=True)
        os.makedirs(config["dataSourceDir"], exist_ok=True)
        initializeDatabase()
        reconcileInterruptedTasks()
        startTaskSyncWorker(taskStatus, taskLock)
        registerShutdownHooks()
        _bootstrap_done = True


@app.before_request
def handleOptions():
    if request.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        }
        return ("", 204, headers)


@app.after_request
def normalizeApiJsonResponses(response):
    try:
        if not should_wrap_json_response(request.path, response):
            return response

        payload = response.get_json(silent=True)
        if payload is None:
            return response
        return build_json_response(payload, response)
    except Exception as exc:
        logMessage(f"统一响应封装失败: {exc}", "WARNING")
        return response


bootstrapApplication()
registerRoutes(app)


if __name__ == "__main__":
    bootstrapApplication()
    logMessage("AtlasWorks瓦片服务启动 - 模块化架构")
    logMessage(f"数据源目录: {config['dataSourceDir']}")
    logMessage(f"瓦片目录: {config['tilesDir']}")
    logMessage(f"日志目录: {config['logDir']}")

    port = int(os.environ.get("PORT", config.get("port", 18000)))
    host = os.environ.get("HOST", config.get("host", "0.0.0.0"))
    debug = config.get("debug", False)

    print("AtlasWorks服务启动中...")
    print(f"监听地址: http://{host}:{port}")
    print(f"调试模式: {debug}")
    print(f"工作目录: {os.getcwd()}")
    print("=" * 50)
    app.run(host=host, port=port, debug=debug, threaded=True)
