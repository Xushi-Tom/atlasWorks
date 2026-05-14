#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import copy
import json
import threading
import time
from datetime import date, datetime

from config import config
from taskState import normalizeTaskRecord

try:
    import psycopg2

    _DB_DRIVER = "psycopg2"
except ImportError:
    psycopg2 = None
    _DB_DRIVER = None


_BOOTSTRAP_LOCK = threading.Lock()
_TASK_SYNC_LOCK = threading.Lock()
_TASK_SYNC_THREAD = None
_ACTIVE_TASK_STATUSES = {"queued", "running"}


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS tf_build_jobs (
        id TEXT PRIMARY KEY,
        job_type TEXT NOT NULL DEFAULT 'unknown',
        status TEXT NOT NULL DEFAULT 'unknown',
        progress INTEGER NOT NULL DEFAULT 0,
        current_stage TEXT,
        message TEXT,
        output_path TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        started_at TIMESTAMPTZ,
        finished_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        payload JSONB NOT NULL DEFAULT '{}'::jsonb
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_tf_build_jobs_status ON tf_build_jobs(status)",
    "CREATE INDEX IF NOT EXISTS idx_tf_build_jobs_updated_at ON tf_build_jobs(updated_at DESC)",
    "ALTER TABLE tf_build_jobs ADD COLUMN IF NOT EXISTS lease_owner TEXT",
    "ALTER TABLE tf_build_jobs ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ",
    "ALTER TABLE tf_build_jobs ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0",
    "CREATE INDEX IF NOT EXISTS idx_tf_build_jobs_worker_claim ON tf_build_jobs(status, job_type, updated_at)",
    """
    CREATE TABLE IF NOT EXISTS tf_job_events (
        id BIGSERIAL PRIMARY KEY,
        job_id TEXT NOT NULL REFERENCES tf_build_jobs(id) ON DELETE CASCADE,
        event_type TEXT NOT NULL,
        event_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        details JSONB NOT NULL DEFAULT '{}'::jsonb
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_tf_job_events_job_id ON tf_job_events(job_id, event_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS tf_artifacts (
        id TEXT PRIMARY KEY,
        build_job_id TEXT REFERENCES tf_build_jobs(id) ON DELETE SET NULL,
        artifact_type TEXT NOT NULL,
        version TEXT,
        format TEXT,
        output_path TEXT NOT NULL,
        bounds JSONB,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tf_publications (
        id TEXT PRIMARY KEY,
        artifact_id TEXT REFERENCES tf_artifacts(id) ON DELETE CASCADE,
        publish_type TEXT NOT NULL,
        publish_path TEXT NOT NULL,
        alias TEXT,
        status TEXT NOT NULL DEFAULT 'draft',
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        browser_url TEXT,
        access_url TEXT,
        launch_url TEXT,
        sample_url TEXT,
        public_base_url TEXT,
        published_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "ALTER TABLE tf_publications ADD COLUMN IF NOT EXISTS browser_url TEXT",
    "ALTER TABLE tf_publications ADD COLUMN IF NOT EXISTS access_url TEXT",
    "ALTER TABLE tf_publications ADD COLUMN IF NOT EXISTS launch_url TEXT",
    "ALTER TABLE tf_publications ADD COLUMN IF NOT EXISTS sample_url TEXT",
    "ALTER TABLE tf_publications ADD COLUMN IF NOT EXISTS public_base_url TEXT",
    "ALTER TABLE tf_publications ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    "COMMENT ON COLUMN tf_publications.browser_url IS '发布目录浏览地址。'",
    "COMMENT ON COLUMN tf_publications.access_url IS '发布服务访问地址（可含模板变量）。'",
    "COMMENT ON COLUMN tf_publications.launch_url IS '用于前端快速打开的发布入口地址。'",
    "COMMENT ON COLUMN tf_publications.sample_url IS '样例瓦片地址。'",
    "COMMENT ON COLUMN tf_publications.public_base_url IS '发布地址拼接使用的基础域名或主机地址。'",
    "COMMENT ON COLUMN tf_publications.updated_at IS '发布记录最近更新时间。'",
    """
    CREATE TABLE IF NOT EXISTS tf_source_assets (
        id TEXT PRIMARY KEY,
        asset_type TEXT NOT NULL,
        name TEXT NOT NULL,
        path TEXT NOT NULL,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tf_workspaces (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        parent_id TEXT REFERENCES tf_workspaces(id) ON DELETE SET NULL,
        workspace_type TEXT NOT NULL,
        path TEXT NOT NULL,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
]


def _log_db_message(message, level="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {level}: [db] {message}")


def isDatabaseEnabled():
    return bool(config.get("database", {}).get("enabled"))


def _databaseSettings():
    return config.get("database", {})


def _taskSyncSettings():
    return config.get("taskSync", {})


def _isActiveTaskPayload(task_data):
    if not isinstance(task_data, dict):
        return False
    return str(task_data.get("status") or "").strip().lower() in _ACTIVE_TASK_STATUSES


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _normalize_timestamp(value):
    if value in (None, "", "None"):
        return None
    return str(value)


def _detect_job_type(task_id, payload):
    if isinstance(payload, dict):
        result = payload.get("result")
        if isinstance(result, dict):
            method = result.get("method")
            if method:
                return str(method)

    lowered = str(task_id or "").lower()
    if lowered.startswith("terrain"):
        return "terrain_tiles"
    if lowered.startswith("indexedtiles"):
        return "indexed_tiles"
    if lowered.startswith("tiles3d"):
        return "3dtiles"
    if lowered.startswith("tileconvert"):
        return "tile_convert"
    if lowered.startswith("split"):
        return "file_split"
    return "unknown"


def _extract_output_path(payload):
    if not isinstance(payload, dict):
        return None

    result = payload.get("result")
    if isinstance(result, dict):
        for key in ("outputPath", "mergedOutputPath", "metadataFile"):
            value = result.get(key)
            if value:
                return str(value)

    for key in ("outputPath", "targetPath", "sourcePath"):
        value = payload.get(key)
        if value:
            return str(value)

    return None


def _get_connection():
    if not isDatabaseEnabled():
        return None
    if _DB_DRIVER != "psycopg2" or psycopg2 is None:
        raise RuntimeError("未安装 psycopg2，无法连接 PostgreSQL")

    settings = _databaseSettings()
    conn = psycopg2.connect(
        host=settings.get("host", "localhost"),
        port=settings.get("port", 25432),
        dbname=settings.get("name", "atlasworks"),
        user=settings.get("user", "atlasworks"),
        password=settings.get("password", "atlasworks"),
        connect_timeout=settings.get("connectTimeout", 3),
        sslmode=settings.get("sslmode", "prefer"),
    )
    conn.autocommit = False
    return conn


def initializeDatabase():
    if not isDatabaseEnabled():
        _log_db_message("数据库持久化未启用，跳过初始化", "INFO")
        return False

    with _BOOTSTRAP_LOCK:
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor() as cursor:
                for statement in SCHEMA_STATEMENTS:
                    cursor.execute(statement)
            conn.commit()
            _log_db_message("数据库初始化完成", "INFO")
            return True
        except Exception as exc:
            if conn:
                conn.rollback()
            _log_db_message(f"数据库初始化失败: {exc}", "ERROR")
            return False
        finally:
            if conn:
                conn.close()


def reconcileInterruptedTasks():
    if not isDatabaseEnabled():
        return 0

    interrupted_count = 0
    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, payload::text
                FROM tf_build_jobs
                WHERE status = 'running'
                """
            )
            rows = cursor.fetchall()
        conn.commit()
    except Exception as exc:
        if conn:
            conn.rollback()
        _log_db_message(f"恢复中断任务失败: {exc}", "WARNING")
        return 0
    finally:
        if conn:
            conn.close()

    for task_id, payload_text in rows:
        payload = json.loads(payload_text) if payload_text else {}
        if not isinstance(payload, dict):
            payload = {}
        payload["status"] = "interrupted"
        payload["endTime"] = payload.get("endTime") or datetime.now().isoformat()
        original_message = payload.get("message", "")
        if original_message:
            payload["message"] = f"{original_message} | 服务重启后已标记为 interrupted"
        else:
            payload["message"] = "服务重启后，运行中的任务已标记为 interrupted"
        syncTaskSnapshot(task_id, payload)
        interrupted_count += 1

    if interrupted_count:
        _log_db_message(f"已将 {interrupted_count} 个未完成任务标记为 interrupted", "INFO")
    return interrupted_count


def checkDatabaseHealth():
    health = {
        "enabled": isDatabaseEnabled(),
        "driver": _DB_DRIVER,
        "connected": False,
        "tablesReady": False,
    }

    if not isDatabaseEnabled():
        health["status"] = "disabled"
        return health

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.execute("SELECT to_regclass('public.tf_build_jobs')")
            row = cursor.fetchone()
        conn.commit()
        health["connected"] = True
        health["tablesReady"] = bool(row and row[0])
        health["status"] = "healthy" if health["tablesReady"] else "degraded"
        return health
    except Exception as exc:
        if conn:
            conn.rollback()
        health["status"] = "unavailable"
        health["error"] = str(exc)
        return health
    finally:
        if conn:
            conn.close()


def syncTaskSnapshot(task_id, task_data):
    if not isDatabaseEnabled():
        return False

    payload = _json_safe(task_data if isinstance(task_data, dict) else {})
    status = str(payload.get("status", "unknown"))
    progress = int(payload.get("progress", 0) or 0)
    current_stage = payload.get("currentStage")
    message = payload.get("message")
    output_path = _extract_output_path(payload)
    created_at = _normalize_timestamp(payload.get("startTime") or payload.get("createdAt"))
    started_at = _normalize_timestamp(payload.get("startTime"))
    finished_at = _normalize_timestamp(payload.get("endTime"))
    job_type = _detect_job_type(task_id, payload)

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, current_stage
                FROM tf_build_jobs
                WHERE id = %s
                """,
                (str(task_id),),
            )
            existing_row = cursor.fetchone()

            cursor.execute(
                """
                INSERT INTO tf_build_jobs (
                    id, job_type, status, progress, current_stage, message,
                    output_path, created_at, started_at, finished_at, updated_at, payload
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, COALESCE(%s::timestamptz, NOW()), %s::timestamptz,
                    %s::timestamptz, NOW(), %s::jsonb
                )
                ON CONFLICT (id) DO UPDATE SET
                    job_type = EXCLUDED.job_type,
                    status = EXCLUDED.status,
                    progress = EXCLUDED.progress,
                    current_stage = EXCLUDED.current_stage,
                    message = EXCLUDED.message,
                    output_path = EXCLUDED.output_path,
                    started_at = COALESCE(EXCLUDED.started_at, tf_build_jobs.started_at),
                    finished_at = EXCLUDED.finished_at,
                    updated_at = NOW(),
                    payload = EXCLUDED.payload,
                    lease_owner = CASE
                        WHEN EXCLUDED.status IN ('completed', 'failed', 'stopped', 'interrupted') THEN NULL
                        ELSE tf_build_jobs.lease_owner
                    END,
                    lease_expires_at = CASE
                        WHEN EXCLUDED.status IN ('completed', 'failed', 'stopped', 'interrupted') THEN NULL
                        ELSE tf_build_jobs.lease_expires_at
                    END
                """,
                (
                    str(task_id),
                    job_type,
                    status,
                    max(0, min(progress, 100)),
                    current_stage,
                    message,
                    output_path,
                    created_at,
                    started_at,
                    finished_at,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )

            if not existing_row:
                _insert_job_event(
                    cursor,
                    task_id,
                    "task.created",
                    {
                        "status": status,
                        "currentStage": current_stage,
                        "message": message,
                    },
                )
            else:
                previous_status = existing_row[0]
                previous_stage = existing_row[1]
                if previous_status != status:
                    _insert_job_event(
                        cursor,
                        task_id,
                        "task.status_changed",
                        {
                            "previousStatus": previous_status,
                            "status": status,
                            "currentStage": current_stage,
                            "message": message,
                        },
                    )
                elif previous_stage != current_stage:
                    _insert_job_event(
                        cursor,
                        task_id,
                        "task.stage_changed",
                        {
                            "previousStage": previous_stage,
                            "currentStage": current_stage,
                            "status": status,
                            "message": message,
                        },
                    )
        conn.commit()
        return True
    except Exception as exc:
        if conn:
            conn.rollback()
        _log_db_message(f"同步任务快照失败 {task_id}: {exc}", "WARNING")
        return False
    finally:
        if conn:
            conn.close()


def _insert_job_event(cursor, task_id, event_type, details):
    cursor.execute(
        """
        INSERT INTO tf_job_events (job_id, event_type, details)
        VALUES (%s, %s, %s::jsonb)
        """,
        (
            str(task_id),
            str(event_type),
            json.dumps(_json_safe(details or {}), ensure_ascii=False),
        ),
    )


def appendJobEvent(task_id, event_type, details=None):
    if not isDatabaseEnabled():
        return False

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            _insert_job_event(cursor, task_id, event_type, details or {})
        conn.commit()
        return True
    except Exception as exc:
        if conn:
            conn.rollback()
        _log_db_message(f"写入任务事件失败 {task_id}/{event_type}: {exc}", "WARNING")
        return False
    finally:
        if conn:
            conn.close()


def deleteTaskSnapshot(task_id):
    if not isDatabaseEnabled():
        return False

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM tf_build_jobs WHERE id = %s", (str(task_id),))
            deleted_rows = cursor.rowcount
        conn.commit()
        return deleted_rows > 0
    except Exception as exc:
        if conn:
            conn.rollback()
        _log_db_message(f"删除任务快照失败 {task_id}: {exc}", "WARNING")
        return False
    finally:
        if conn:
            conn.close()


def pruneTaskSnapshots(max_tasks=100):
    if not isDatabaseEnabled():
        return 0

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM tf_build_jobs
                WHERE id IN (
                    SELECT id FROM tf_build_jobs
                    ORDER BY updated_at DESC
                    OFFSET %s
                )
                """,
                (max_tasks,),
            )
            deleted_rows = cursor.rowcount
        conn.commit()
        return max(0, deleted_rows)
    except Exception as exc:
        if conn:
            conn.rollback()
        _log_db_message(f"清理历史任务快照失败: {exc}", "WARNING")
        return 0
    finally:
        if conn:
            conn.close()


def fetchTaskSnapshot(task_id):
    if not isDatabaseEnabled():
        return None

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT payload::text
                FROM tf_build_jobs
                WHERE id = %s
                """,
                (str(task_id),),
            )
            row = cursor.fetchone()
        conn.commit()
        if not row:
            return None

        payload = json.loads(row[0]) if row[0] else {}
        if isinstance(payload, dict):
            payload["taskId"] = str(task_id)
        return payload
    except Exception as exc:
        if conn:
            conn.rollback()
        _log_db_message(f"读取任务快照失败 {task_id}: {exc}", "WARNING")
        return None
    finally:
        if conn:
            conn.close()


def listTaskSnapshots(limit=50):
    if not isDatabaseEnabled():
        return []

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, payload::text
                FROM tf_build_jobs
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()
        conn.commit()

        snapshots = []
        for task_id, payload_text in rows:
            payload = json.loads(payload_text) if payload_text else {}
            if isinstance(payload, dict):
                payload["taskId"] = str(task_id)
                snapshots.append(payload)
        return snapshots
    except Exception as exc:
        if conn:
            conn.rollback()
        _log_db_message(f"列出任务快照失败: {exc}", "WARNING")
        return []
    finally:
        if conn:
            conn.close()


def getTaskSnapshotStats():
    stats = {
        "total": 0,
        "running": 0,
        "queued": 0,
        "completed": 0,
        "failed": 0,
        "stopped": 0,
        "interrupted": 0,
        "unknown": 0,
        "byStatus": {},
    }

    if not isDatabaseEnabled():
        return stats

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COALESCE(NULLIF(TRIM(LOWER(status)), ''), 'unknown') AS normalized_status,
                       COUNT(*)
                FROM tf_build_jobs
                GROUP BY normalized_status
                """
            )
            rows = cursor.fetchall()
        conn.commit()

        by_status = {}
        total = 0
        for status, count in rows:
            normalized_status = str(status or "unknown").strip().lower() or "unknown"
            item_count = int(count or 0)
            by_status[normalized_status] = item_count
            total += item_count

        stats["total"] = total
        stats["byStatus"] = by_status
        for status, count in by_status.items():
            if status in stats:
                stats[status] = count
        return stats
    except Exception as exc:
        if conn:
            conn.rollback()
        _log_db_message(f"统计任务快照失败: {exc}", "WARNING")
        return stats
    finally:
        if conn:
            conn.close()


def listTaskEvents(task_id, limit=100):
    if not isDatabaseEnabled():
        return []

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, event_type, event_at::text, details::text
                FROM tf_job_events
                WHERE job_id = %s
                ORDER BY event_at DESC, id DESC
                LIMIT %s
                """,
                (str(task_id), limit),
            )
            rows = cursor.fetchall()
        conn.commit()

        events = []
        for row in rows:
            events.append(
                {
                    "id": row[0],
                    "eventType": row[1],
                    "eventAt": row[2],
                    "details": json.loads(row[3]) if row[3] else {},
                }
            )
        return events
    except Exception as exc:
        if conn:
            conn.rollback()
        _log_db_message(f"读取任务事件失败 {task_id}: {exc}", "WARNING")
        return []
    finally:
        if conn:
            conn.close()


def upsertArtifactRecord(artifact_id, build_job_id, artifact_type, output_path, output_format=None, bounds=None, metadata=None):
    if not isDatabaseEnabled():
        return False

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tf_artifacts (
                    id, build_job_id, artifact_type, version, format, output_path, bounds, metadata, created_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, NOW()
                )
                ON CONFLICT (id) DO UPDATE SET
                    build_job_id = EXCLUDED.build_job_id,
                    artifact_type = EXCLUDED.artifact_type,
                    format = EXCLUDED.format,
                    output_path = EXCLUDED.output_path,
                    bounds = EXCLUDED.bounds,
                    metadata = EXCLUDED.metadata
                """,
                (
                    str(artifact_id),
                    str(build_job_id) if build_job_id is not None else None,
                    str(artifact_type),
                    "v1",
                    output_format,
                    output_path,
                    json.dumps(_json_safe(bounds), ensure_ascii=False),
                    json.dumps(_json_safe(metadata or {}), ensure_ascii=False),
                ),
            )
        conn.commit()
        return True
    except Exception as exc:
        if conn:
            conn.rollback()
        _log_db_message(f"同步产物记录失败 {artifact_id}: {exc}", "WARNING")
        return False
    finally:
        if conn:
            conn.close()


def listArtifactRecords(limit=50):
    if not isDatabaseEnabled():
        return []

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, build_job_id, artifact_type, version, format, output_path, bounds::text, metadata::text, created_at::text
                FROM tf_artifacts
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()
        conn.commit()

        results = []
        for row in rows:
            results.append(
                {
                    "id": row[0],
                    "buildJobId": row[1],
                    "artifactType": row[2],
                    "version": row[3],
                    "format": row[4],
                    "outputPath": row[5],
                    "bounds": json.loads(row[6]) if row[6] else None,
                    "metadata": json.loads(row[7]) if row[7] else {},
                    "createdAt": row[8],
                }
            )
        return results
    except Exception as exc:
        if conn:
            conn.rollback()
        _log_db_message(f"列出产物记录失败: {exc}", "WARNING")
        return []
    finally:
        if conn:
            conn.close()


def fetchArtifactRecord(artifact_id):
    if not isDatabaseEnabled():
        return None

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, build_job_id, artifact_type, version, format, output_path, bounds::text, metadata::text, created_at::text
                FROM tf_artifacts
                WHERE id = %s
                """,
                (str(artifact_id),),
            )
            row = cursor.fetchone()
        conn.commit()
        if not row:
            return None
        return {
            "id": row[0],
            "buildJobId": row[1],
            "artifactType": row[2],
            "version": row[3],
            "format": row[4],
            "outputPath": row[5],
            "bounds": json.loads(row[6]) if row[6] else None,
            "metadata": json.loads(row[7]) if row[7] else {},
            "createdAt": row[8],
        }
    except Exception as exc:
        if conn:
            conn.rollback()
        _log_db_message(f"读取产物记录失败 {artifact_id}: {exc}", "WARNING")
        return None
    finally:
        if conn:
            conn.close()


def upsertPublicationRecord(
    publication_id,
    artifact_id,
    publish_type,
    publish_path,
    alias=None,
    status="draft",
    metadata=None,
    published_at=None,
    browser_url=None,
    access_url=None,
    launch_url=None,
    sample_url=None,
    public_base_url=None,
):
    if not isDatabaseEnabled():
        return False

    artifact_ref = str(artifact_id).strip() if artifact_id is not None else ""
    artifact_ref = artifact_ref or None

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tf_publications (
                    id, artifact_id, publish_type, publish_path, alias, status, metadata,
                    browser_url, access_url, launch_url, sample_url, public_base_url,
                    published_at, created_at, updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s::jsonb,
                    %s, %s, %s, %s, %s,
                    %s::timestamptz, NOW(), NOW()
                )
                ON CONFLICT (id) DO UPDATE SET
                    artifact_id = EXCLUDED.artifact_id,
                    publish_type = EXCLUDED.publish_type,
                    publish_path = EXCLUDED.publish_path,
                    alias = EXCLUDED.alias,
                    status = EXCLUDED.status,
                    metadata = EXCLUDED.metadata,
                    browser_url = EXCLUDED.browser_url,
                    access_url = EXCLUDED.access_url,
                    launch_url = EXCLUDED.launch_url,
                    sample_url = EXCLUDED.sample_url,
                    public_base_url = EXCLUDED.public_base_url,
                    published_at = EXCLUDED.published_at,
                    updated_at = NOW()
                """,
                (
                    str(publication_id),
                    artifact_ref,
                    str(publish_type),
                    str(publish_path),
                    alias,
                    status,
                    json.dumps(_json_safe(metadata or {}), ensure_ascii=False),
                    browser_url,
                    access_url,
                    launch_url,
                    sample_url,
                    public_base_url,
                    published_at,
                ),
            )
        conn.commit()
        return True
    except Exception as exc:
        if conn:
            conn.rollback()
        _log_db_message(f"同步发布记录失败 {publication_id}: {exc}", "WARNING")
        return False
    finally:
        if conn:
            conn.close()


def listPublicationRecords(limit=50):
    if not isDatabaseEnabled():
        return []

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, artifact_id, publish_type, publish_path, alias, status, metadata::text,
                       browser_url, access_url, launch_url, sample_url, public_base_url,
                       published_at::text, created_at::text, updated_at::text
                FROM tf_publications
                ORDER BY COALESCE(published_at, created_at) DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()
        conn.commit()

        results = []
        for row in rows:
            results.append(
                {
                    "id": row[0],
                    "artifactId": row[1],
                    "publishType": row[2],
                    "publishPath": row[3],
                    "alias": row[4],
                    "status": row[5],
                    "metadata": json.loads(row[6]) if row[6] else {},
                    "browserUrl": row[7],
                    "accessUrl": row[8],
                    "launchUrl": row[9],
                    "sampleUrl": row[10],
                    "publicBaseUrl": row[11],
                    "publishedAt": row[12],
                    "createdAt": row[13],
                    "updatedAt": row[14],
                }
            )
        return results
    except Exception as exc:
        if conn:
            conn.rollback()
        _log_db_message(f"列出发布记录失败: {exc}", "WARNING")
        return []
    finally:
        if conn:
            conn.close()


def fetchPublicationRecord(publication_id):
    if not isDatabaseEnabled():
        return None

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, artifact_id, publish_type, publish_path, alias, status, metadata::text,
                       browser_url, access_url, launch_url, sample_url, public_base_url,
                       published_at::text, created_at::text, updated_at::text
                FROM tf_publications
                WHERE id = %s
                """,
                (str(publication_id),),
            )
            row = cursor.fetchone()
        conn.commit()
        if not row:
            return None
        return {
            "id": row[0],
            "artifactId": row[1],
            "publishType": row[2],
            "publishPath": row[3],
            "alias": row[4],
            "status": row[5],
            "metadata": json.loads(row[6]) if row[6] else {},
            "browserUrl": row[7],
            "accessUrl": row[8],
            "launchUrl": row[9],
            "sampleUrl": row[10],
            "publicBaseUrl": row[11],
            "publishedAt": row[12],
            "createdAt": row[13],
            "updatedAt": row[14],
        }
    except Exception as exc:
        if conn:
            conn.rollback()
        _log_db_message(f"读取发布记录失败 {publication_id}: {exc}", "WARNING")
        return None
    finally:
        if conn:
            conn.close()


def enqueueBuildJob(task_id, job_type, payload):
    if not isDatabaseEnabled():
        return False

    job_payload = _json_safe(payload if isinstance(payload, dict) else {})
    job_payload["taskId"] = str(task_id)
    job_payload["jobType"] = str(job_type)
    job_payload["status"] = "queued"
    job_payload["progress"] = int(job_payload.get("progress", 0) or 0)
    job_payload.setdefault("message", "任务已入队，等待 worker 执行")
    job_payload.setdefault("currentStage", "排队中")
    job_payload.setdefault("createdAt", datetime.now().isoformat())

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tf_build_jobs (
                    id, job_type, status, progress, current_stage, message,
                    output_path, created_at, updated_at, payload,
                    lease_owner, lease_expires_at, attempt_count
                )
                VALUES (
                    %s, %s, 'queued', %s, %s, %s,
                    %s, NOW(), NOW(), %s::jsonb,
                    NULL, NULL, 0
                )
                ON CONFLICT (id) DO UPDATE SET
                    job_type = EXCLUDED.job_type,
                    status = 'queued',
                    progress = EXCLUDED.progress,
                    current_stage = EXCLUDED.current_stage,
                    message = EXCLUDED.message,
                    output_path = EXCLUDED.output_path,
                    updated_at = NOW(),
                    payload = EXCLUDED.payload,
                    lease_owner = NULL,
                    lease_expires_at = NULL
                """,
                (
                    str(task_id),
                    str(job_type),
                    max(0, min(int(job_payload.get("progress", 0) or 0), 100)),
                    job_payload.get("currentStage"),
                    job_payload.get("message"),
                    _extract_output_path(job_payload),
                    json.dumps(job_payload, ensure_ascii=False),
                ),
            )
            _insert_job_event(
                cursor,
                task_id,
                "task.queued",
                {"jobType": job_type, "message": job_payload.get("message")},
            )
        conn.commit()
        return True
    except Exception as exc:
        if conn:
            conn.rollback()
        _log_db_message(f"任务入队失败 {task_id}: {exc}", "WARNING")
        return False
    finally:
        if conn:
            conn.close()


def claimQueuedBuildJob(worker_id, job_types=None, lease_seconds=300):
    if not isDatabaseEnabled():
        return None

    normalized_job_types = [str(item).strip() for item in (job_types or []) if str(item).strip()]
    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            if normalized_job_types:
                cursor.execute(
                    """
                    SELECT id, job_type, payload::text
                    FROM tf_build_jobs
                    WHERE status = 'queued'
                      AND job_type = ANY(%s)
                    ORDER BY updated_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """,
                    (normalized_job_types,),
                )
            else:
                cursor.execute(
                    """
                    SELECT id, job_type, payload::text
                    FROM tf_build_jobs
                    WHERE status = 'queued'
                    ORDER BY updated_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """
                )
            row = cursor.fetchone()
            if not row:
                conn.commit()
                return None

            task_id, job_type, payload_text = row
            payload = json.loads(payload_text) if payload_text else {}
            if not isinstance(payload, dict):
                payload = {}
            payload["status"] = "running"
            payload["message"] = "worker 已领取任务，准备执行"
            payload["currentStage"] = "准备执行"
            payload["workerId"] = str(worker_id)

            cursor.execute(
                """
                UPDATE tf_build_jobs
                SET status = 'running',
                    progress = %s,
                    current_stage = %s,
                    message = %s,
                    started_at = COALESCE(started_at, NOW()),
                    updated_at = NOW(),
                    payload = %s::jsonb,
                    lease_owner = %s,
                    lease_expires_at = NOW() + (%s || ' seconds')::interval,
                    attempt_count = attempt_count + 1
                WHERE id = %s
                """,
                (
                    max(0, min(int(payload.get("progress", 0) or 0), 100)),
                    payload.get("currentStage"),
                    payload.get("message"),
                    json.dumps(_json_safe(payload), ensure_ascii=False),
                    str(worker_id),
                    int(lease_seconds),
                    str(task_id),
                ),
            )
            _insert_job_event(
                cursor,
                task_id,
                "task.claimed",
                {"workerId": worker_id, "jobType": job_type},
            )
        conn.commit()
        return {"taskId": str(task_id), "jobType": str(job_type), "payload": payload}
    except Exception as exc:
        if conn:
            conn.rollback()
        _log_db_message(f"领取队列任务失败: {exc}", "WARNING")
        return None
    finally:
        if conn:
            conn.close()


def flushTaskSnapshots(task_status, task_lock, reason="manual"):
    if not isDatabaseEnabled():
        return 0

    flushed = 0
    try:
        snapshot_items = []
        with task_lock:
            for task_id, task_data in task_status.items():
                try:
                    snapshot_items.append((task_id, copy.deepcopy(task_data)))
                except Exception:
                    snapshot_items.append((task_id, dict(task_data)))

        for task_id, task_data in snapshot_items:
            if syncTaskSnapshot(task_id, normalizeTaskRecord(task_id, task_data)):
                flushed += 1

        _log_db_message(f"任务快照主动落库完成: {flushed} 条，触发原因: {reason}", "INFO")
        return flushed
    except Exception as exc:
        _log_db_message(f"任务快照主动落库失败: {exc}", "WARNING")
        return flushed


def deletePublicationRecord(publication_id):
    if not isDatabaseEnabled():
        return False

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM tf_publications
                WHERE id = %s
                """,
                (str(publication_id),),
            )
            deleted_rows = cursor.rowcount
        conn.commit()
        return deleted_rows > 0
    except Exception as exc:
        if conn:
            conn.rollback()
        _log_db_message(f"删除发布记录失败 {publication_id}: {exc}", "WARNING")
        return False
    finally:
        if conn:
            conn.close()


def countTableRows(table_name):
    if not isDatabaseEnabled():
        return 0

    allowed_tables = {"tf_build_jobs", "tf_job_events", "tf_artifacts", "tf_publications"}
    if table_name not in allowed_tables:
        return 0

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            row = cursor.fetchone()
        conn.commit()
        return int(row[0]) if row else 0
    except Exception as exc:
        if conn:
            conn.rollback()
        _log_db_message(f"统计数据表失败 {table_name}: {exc}", "WARNING")
        return 0
    finally:
        if conn:
            conn.close()


def _syncLoop(task_status, task_lock, interval_seconds):
    _log_db_message(f"任务同步线程已启动，同步间隔 {interval_seconds}s", "INFO")
    while True:
        try:
            snapshot_items = []
            with task_lock:
                for task_id, task_data in task_status.items():
                    try:
                        snapshot_items.append((task_id, copy.deepcopy(task_data)))
                    except Exception:
                        snapshot_items.append((task_id, dict(task_data)))

            synced_inactive_task_ids = []
            for task_id, task_data in snapshot_items:
                normalized_task = normalizeTaskRecord(task_id, task_data)
                if syncTaskSnapshot(task_id, normalized_task) and not _isActiveTaskPayload(normalized_task):
                    synced_inactive_task_ids.append(task_id)

            if synced_inactive_task_ids:
                with task_lock:
                    for task_id in synced_inactive_task_ids:
                        current_task = task_status.get(task_id)
                        if current_task is not None and not _isActiveTaskPayload(current_task):
                            del task_status[task_id]
        except Exception as exc:
            _log_db_message(f"任务同步线程异常: {exc}", "WARNING")

        time.sleep(interval_seconds)


def startTaskSyncWorker(task_status, task_lock):
    global _TASK_SYNC_THREAD

    if not isDatabaseEnabled():
        _log_db_message("数据库持久化未启用，跳过任务同步线程启动", "INFO")
        return False

    if not _taskSyncSettings().get("enabled", True):
        _log_db_message("任务同步线程已禁用", "INFO")
        return False

    with _TASK_SYNC_LOCK:
        if _TASK_SYNC_THREAD and _TASK_SYNC_THREAD.is_alive():
            return True

        interval_seconds = _taskSyncSettings().get("intervalSeconds", 2)
        _TASK_SYNC_THREAD = threading.Thread(
            target=_syncLoop,
            args=(task_status, task_lock, interval_seconds),
            daemon=True,
            name="task-db-sync",
        )
        _TASK_SYNC_THREAD.start()
        return True
