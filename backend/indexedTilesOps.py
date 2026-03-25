#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import hashlib
import json
import math
import os
import random
import re
import subprocess
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime

from flask import jsonify, request

from artifacts import finalizeTaskArtifact
from config import config, taskLock, taskProcesses, taskStatus
from dataSourceOps import findTifFilesInFolders, getSourceBandInfoCached, hasHttpSourcesInPatterns
from taskState import appendTaskLog, createTaskRecord
from utils import (
    logMessage,
    normalizeBandMismatchPolicy,
    normalizeFloat,
    normalizeImageFormat,
    normalizeInt,
    normalizeProjection,
    normalizeTileScheme,
    parseMemoryToGb,
    runCommand,
)


_bandStatsCache = {}
_cpu_for_slots = os.cpu_count() or 4
MAX_INDEXED_TASK_SLOTS = max(1, min(3, _cpu_for_slots // 8 + 1))
indexedTaskSemaphore = threading.Semaphore(MAX_INDEXED_TASK_SLOTS)


def deg2tile(latDeg, lonDeg, zoom):
    latRad = math.radians(latDeg)
    n = 2.0 ** zoom
    x = int((lonDeg + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(latRad)) / math.pi) / 2.0 * n)
    return (x, y)


def tile2deg(x, y, zoom):
    n = 2.0 ** zoom
    lonDeg = x / n * 360.0 - 180.0
    latRad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    latDeg = math.degrees(latRad)
    return (lonDeg, latDeg)


def createTileGridIndex(tifFiles, outputPath, minZoom, maxZoom, tileSize=256):
    """基于源文件地理范围创建瓦片网格索引。"""
    try:
        logMessage(f"开始创建瓦片网格索引：{len(tifFiles)} 个文件，级别 {minZoom}-{maxZoom}")
        allBounds = []
        for tifFile in tifFiles:
            bounds = getFileGeographicBounds(tifFile)
            if bounds and "west" in bounds:
                allBounds.append(
                    {
                        "file": tifFile,
                        "west": bounds["west"],
                        "south": bounds["south"],
                        "east": bounds["east"],
                        "north": bounds["north"],
                    }
                )
                logMessage(
                    f"文件边界: {os.path.basename(tifFile)} "
                    f"[{bounds['west']:.6f}, {bounds['south']:.6f}, {bounds['east']:.6f}, {bounds['north']:.6f}]"
                )

        if not allBounds:
            return {"success": False, "error": "无法获取任何文件的地理边界"}

        totalWest = min(item["west"] for item in allBounds)
        totalSouth = min(item["south"] for item in allBounds)
        totalEast = max(item["east"] for item in allBounds)
        totalNorth = max(item["north"] for item in allBounds)
        tileIndex = []

        for zoom in range(minZoom, maxZoom + 1):
            minTileX, minTileY = deg2tile(totalNorth, totalWest, zoom)
            maxTileX, maxTileY = deg2tile(totalSouth, totalEast, zoom)
            minTileX = max(0, min(minTileX, maxTileX))
            maxTileX = min((1 << zoom) - 1, max(minTileX, maxTileX))
            minTileY = max(0, min(minTileY, maxTileY))
            maxTileY = min((1 << zoom) - 1, max(minTileY, maxTileY))
            logMessage(f"级别 {zoom}: 瓦片范围 X({minTileX}-{maxTileX}) Y({minTileY}-{maxTileY})")

            for tileX in range(minTileX, maxTileX + 1):
                for tileY in range(minTileY, maxTileY + 1):
                    tileWest, tileNorth = tile2deg(tileX, tileY, zoom)
                    tileEast, tileSouth = tile2deg(tileX + 1, tileY + 1, zoom)
                    intersectingFiles = []
                    for fileInfo in allBounds:
                        if (
                            fileInfo["west"] <= tileEast
                            and fileInfo["east"] >= tileWest
                            and fileInfo["south"] <= tileNorth
                            and fileInfo["north"] >= tileSouth
                        ):
                            intersectingFiles.append(
                                {
                                    "file": fileInfo["file"],
                                    "bounds": [
                                        fileInfo["west"],
                                        fileInfo["south"],
                                        fileInfo["east"],
                                        fileInfo["north"],
                                    ],
                                    "filename": os.path.basename(fileInfo["file"]),
                                }
                            )
                    if intersectingFiles:
                        tileIndex.append(
                            {
                                "z": zoom,
                                "x": tileX,
                                "y": tileY,
                                "bounds": [tileWest, tileSouth, tileEast, tileNorth],
                                "sourceFiles": intersectingFiles,
                                "sourceCount": len(intersectingFiles),
                                "tileSize": tileSize,
                                "area": (tileEast - tileWest) * (tileNorth - tileSouth),
                            }
                        )

        logMessage(f"瓦片网格索引创建完成：总计 {len(tileIndex)} 个有效瓦片")
        return {
            "success": True,
            "tileIndex": tileIndex,
            "totalTiles": len(tileIndex),
            "totalBounds": [totalWest, totalSouth, totalEast, totalNorth],
            "zoomLevels": f"{minZoom}-{maxZoom}",
            "sourceFiles": len(tifFiles),
        }
    except Exception as exc:
        logMessage(f"创建瓦片网格索引失败: {exc}", "ERROR")
        return {"success": False, "error": str(exc)}


def countRunningHeavyTasks(excludeTaskId=None):
    running = 0
    queued = 0
    with taskLock:
        for taskId, taskInfo in taskStatus.items():
            if taskId == excludeTaskId:
                continue
            if not (str(taskId).startswith("indexedTiles") or str(taskId).startswith("terrain")):
                continue
            status = str(taskInfo.get("status", "")).lower()
            if status == "running":
                running += 1
            elif status == "queued":
                queued += 1
    return running, queued


def recommendIndexedConcurrency(requestedProcesses, requestedThreads, maxMemory, currentTaskId=None):
    cpuCount = os.cpu_count() or 4
    try:
        import psutil

        availableMemoryGb = psutil.virtual_memory().available / (1024 ** 3)
    except Exception:
        availableMemoryGb = 8.0

    runningTasks, queuedTasks = countRunningHeavyTasks(currentTaskId)
    concurrentTasks = runningTasks + 1
    usableCpu = max(1, int(cpuCount * 0.9))
    perTaskCpuBudget = max(1, usableCpu // concurrentTasks)
    requestedProc = normalizeInt(requestedProcesses, max(1, min(4, perTaskCpuBudget)), 1, max(1, cpuCount))
    requestedThr = normalizeInt(requestedThreads, 2, 1, 64)
    processes = min(requestedProc, perTaskCpuBudget)
    threadCapByCpu = max(1, perTaskCpuBudget // max(1, processes))
    threads = min(requestedThr, threadCapByCpu)
    memoryLimitGb = parseMemoryToGb(maxMemory, 8.0)
    perTaskMemoryBudgetGb = max(1.0, min(memoryLimitGb, (availableMemoryGb * 0.75) / concurrentTasks))
    estMemoryPerProcessGb = 0.6 + 0.25 * threads
    maxProcByMemory = max(1, int(perTaskMemoryBudgetGb / max(estMemoryPerProcessGb, 0.1)))
    if processes > maxProcByMemory:
        processes = maxProcByMemory
        threadCapByCpu = max(1, perTaskCpuBudget // max(1, processes))
        threads = min(threads, threadCapByCpu)
    if processes * threads > perTaskCpuBudget:
        threads = max(1, perTaskCpuBudget // max(1, processes))

    summary = (
        f"运行中重任务 {runningTasks} 个，排队 {queuedTasks} 个，"
        f"CPU预算 {perTaskCpuBudget}，内存预算 {perTaskMemoryBudgetGb:.2f}GB，"
        f"推荐 processes={max(1, processes)}, threads={max(1, threads)}"
    )
    return {
        "processes": max(1, processes),
        "threads": max(1, threads),
        "runningHeavyTasks": runningTasks,
        "queuedHeavyTasks": queuedTasks,
        "cpuBudget": perTaskCpuBudget,
        "memoryBudgetGb": round(perTaskMemoryBudgetGb, 2),
        "summary": summary,
    }


def getTileOutputPath(tilesDir, zoom, tileX, tileY, renderOptions):
    tileScheme = normalizeTileScheme((renderOptions or {}).get("tileScheme", "tms"))
    imageFormat = normalizeImageFormat((renderOptions or {}).get("imageFormat", "png"))
    outputY = tileY if tileScheme == "google" else (1 << int(zoom)) - int(tileY) - 1
    extension = "jpg" if imageFormat == "jpeg" else "png"
    tileDir = os.path.join(tilesDir, str(zoom), str(tileX))
    os.makedirs(tileDir, exist_ok=True)
    tileFile = os.path.join(tileDir, f"{outputY}.{extension}")
    return tileFile, outputY, extension


def getNodataArgs(renderOptions):
    if renderOptions is None:
        return ["-srcnodata", "0", "-dstnodata", "0"]
    srcNodata = renderOptions.get("srcNodata")
    dstNodata = renderOptions.get("dstNodata")
    args = []
    if srcNodata is not None:
        args.extend(["-srcnodata", str(srcNodata)])
    if dstNodata is not None:
        args.extend(["-dstnodata", str(dstNodata)])
    if not args:
        args = ["-srcnodata", "0", "-dstnodata", "0"]
    return args


def getThreadSettings(renderOptions):
    if renderOptions is None:
        return 4
    return normalizeInt(renderOptions.get("threads"), 4, 1, 64)


def getSourceBandStatsCached(filePath):
    if filePath in _bandStatsCache:
        return _bandStatsCache[filePath]
    stats = []
    try:
        result = subprocess.run(["gdalinfo", "-json", "-stats", filePath], capture_output=True, text=True, timeout=45)
        if result.returncode == 0:
            info = json.loads(result.stdout)
            for band in info.get("bands", []):
                stats.append({"minimum": band.get("minimum"), "maximum": band.get("maximum")})
    except Exception:
        stats = []
    _bandStatsCache[filePath] = stats
    return stats


def preprocessMultibandSource(sourceFile, tempDir="/tmp", renderOptions=None):
    try:
        options = renderOptions or {}
        redBand = normalizeInt(options.get("redBand"), 1, 1)
        greenBand = normalizeInt(options.get("greenBand"), 2, 1)
        blueBand = normalizeInt(options.get("blueBand"), 3, 1)
        stretchType = str(options.get("stretchType", "none")).strip().lower()
        stretchLowPercent = normalizeFloat(options.get("stretchLowPercent"), 2.0)
        stretchHighPercent = normalizeFloat(options.get("stretchHighPercent"), 98.0)
        bandMismatchPolicy = normalizeBandMismatchPolicy(options.get("bandMismatchPolicy", "auto"))

        bandInfo = getSourceBandInfoCached(sourceFile)
        bandCount = bandInfo["bandCount"]
        hasAlpha = bandInfo["hasAlpha"]
        selectedBands = [redBand, greenBand, blueBand]

        if max(selectedBands) > bandCount:
            if bandMismatchPolicy == "strict":
                raise ValueError(
                    f"波段不匹配: {os.path.basename(sourceFile)} 仅有 {bandCount} 个波段，但请求了 {selectedBands}"
                )
            if bandMismatchPolicy == "skip":
                logMessage(f"跳过波段不匹配文件: {os.path.basename(sourceFile)}", "WARNING")
                return None
            if bandCount <= 0:
                return None
            if bandCount == 1:
                selectedBands = [1, 1, 1]
            elif bandCount == 2:
                selectedBands = [1, 2, 2]
            else:
                selectedBands = [1, 2, 3]

        needBandRemap = selectedBands != [1, 2, 3]
        needStretch = stretchType in ("minmax", "percent")
        needMultibandReduce = bandCount > 3 and not hasAlpha
        needForceRgb = bandCount < 3
        if not (needBandRemap or needStretch or needMultibandReduce or needForceRgb):
            return sourceFile

        optionHashBase = (
            f"{sourceFile}|{selectedBands}|{stretchType}|{stretchLowPercent}|{stretchHighPercent}|{bandMismatchPolicy}"
        )
        fileHash = hashlib.md5(optionHashBase.encode()).hexdigest()[:12]
        rgbFile = os.path.join(tempDir, f"rgb_{fileHash}.tif")
        lockFile = f"{rgbFile}.lock"
        tempRgbFile = f"{rgbFile}.{os.getpid()}.tmp.tif"

        if os.path.exists(rgbFile) and os.path.getsize(rgbFile) > 0:
            return rgbFile

        deadline = time.time() + 180
        while time.time() < deadline:
            if os.path.exists(rgbFile) and os.path.getsize(rgbFile) > 0:
                return rgbFile

            lockFd = None
            try:
                lockFd = os.open(lockFile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                time.sleep(0.2)
                continue

            try:
                cmd = [
                    "gdal_translate",
                    "-b",
                    str(selectedBands[0]),
                    "-b",
                    str(selectedBands[1]),
                    "-b",
                    str(selectedBands[2]),
                    "-co",
                    "TILED=YES",
                    "-co",
                    "COMPRESS=LZW",
                    sourceFile,
                    tempRgbFile,
                ]
                if stretchType == "minmax":
                    cmd = cmd[:1] + ["-scale_1", "-scale_2", "-scale_3", "-ot", "Byte"] + cmd[1:]
                elif stretchType == "percent":
                    bandStats = getSourceBandStatsCached(sourceFile)
                    scaleArgs = []
                    for index, bandNo in enumerate(selectedBands, start=1):
                        stat = bandStats[bandNo - 1] if bandStats and bandNo - 1 < len(bandStats) else None
                        if stat and stat.get("minimum") is not None and stat.get("maximum") is not None:
                            bandMin = float(stat["minimum"])
                            bandMax = float(stat["maximum"])
                            low = bandMin + (bandMax - bandMin) * (stretchLowPercent / 100.0)
                            high = bandMin + (bandMax - bandMin) * (stretchHighPercent / 100.0)
                            if high <= low:
                                low, high = bandMin, bandMax
                            scaleArgs += [f"-scale_{index}", str(low), str(high), "0", "255"]
                        else:
                            scaleArgs += [f"-scale_{index}"]
                    cmd = cmd[:1] + scaleArgs + ["-ot", "Byte"] + cmd[1:]

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
                if result.returncode == 0 and os.path.exists(tempRgbFile) and os.path.getsize(tempRgbFile) > 0:
                    os.replace(tempRgbFile, rgbFile)
                    return rgbFile
                if os.path.exists(tempRgbFile):
                    os.remove(tempRgbFile)
                break
            finally:
                try:
                    if lockFd is not None:
                        os.close(lockFd)
                except Exception:
                    pass
                try:
                    if os.path.exists(lockFile):
                        os.remove(lockFile)
                except Exception:
                    pass

        logMessage(f"预处理未生成有效缓存文件，回退源文件: {os.path.basename(sourceFile)}", "WARNING")
    except Exception as exc:
        policy = normalizeBandMismatchPolicy((renderOptions or {}).get("bandMismatchPolicy", "auto"))
        if policy == "skip":
            logMessage(f"预处理失败，按 skip 策略跳过文件 {os.path.basename(sourceFile)}: {exc}", "WARNING")
            return None
        raise
    return sourceFile


def calculateOptimalBatchSize(tileCount, maxWorkers, targetSpeed=1000):
    tilesPerWorkerPerSec = targetSpeed / maxWorkers
    optimalBatchTime = 3.0
    batchSize = int(tilesPerWorkerPerSec * optimalBatchTime)
    if tileCount < 100:
        batchSize = min(batchSize, 10)
    elif tileCount < 1000:
        batchSize = min(batchSize, 50)
    elif tileCount < 10000:
        batchSize = min(batchSize, 100)
    else:
        batchSize = min(batchSize, 200)
    return max(batchSize, 5)


def processSingleTileOptimized(tileInfo, tilesDir, resampling="near", temp_dir=None, render_options=None):
    try:
        zoom, tileX, tileY = tileInfo["z"], tileInfo["x"], tileInfo["y"]
        tileBounds = tileInfo["bounds"]
        sourceFiles = tileInfo["sourceFiles"]
        renderOptions = render_options or {}
        tileFile, outputY, _ = getTileOutputPath(tilesDir, zoom, tileX, tileY, renderOptions)
        if os.path.exists(tileFile) and os.path.getsize(tileFile) > 0:
            return {"success": True, "tileFile": tileFile, "skipped": True, "tilePath": f"{zoom}/{tileX}/{outputY}"}

        sourceFileList = []
        for sourceFile in sourceFiles:
            filePath = sourceFile["file"] if isinstance(sourceFile, dict) else sourceFile
            if not os.path.isabs(filePath):
                filePath = os.path.join(config["dataSourceDir"], filePath)
            preparedFile = preprocessMultibandSource(filePath, renderOptions=renderOptions)
            if preparedFile:
                sourceFileList.append(preparedFile)
        if not sourceFileList:
            return {"success": False, "error": "没有可用于当前瓦片的有效源文件"}

        tempTileFile = os.path.join(temp_dir, f"tile_{zoom}_{tileX}_{tileY}.tif") if temp_dir else os.path.splitext(tileFile)[0] + "_temp.tif"
        projection = normalizeProjection(renderOptions.get("projection", "EPSG:3857"))
        threadCount = getThreadSettings(renderOptions)
        cmd1 = [
            "gdalwarp",
            "-te",
            str(tileBounds[0]),
            str(tileBounds[1]),
            str(tileBounds[2]),
            str(tileBounds[3]),
            "-te_srs",
            "EPSG:4326",
            "-ts",
            "256",
            "256",
            "-r",
            resampling,
            "-t_srs",
            projection,
            "-of",
            "GTiff",
            "-co",
            "TILED=YES",
            "-co",
            "COMPRESS=LZW",
            "-dstalpha",
            "-multi",
            "-wo",
            f"NUM_THREADS={threadCount}",
            "-wm",
            "128",
            "-q",
        ] + getNodataArgs(renderOptions) + sourceFileList + [tempTileFile]
        env = os.environ.copy()
        env["GDAL_NUM_THREADS"] = str(threadCount)
        env["OMP_NUM_THREADS"] = str(threadCount)
        result1 = subprocess.run(cmd1, capture_output=True, text=True, timeout=90, env=env)
        if result1.returncode != 0:
            return {"success": False, "error": f"gdalwarp 失败: {result1.stderr}"}

        imageFormat = normalizeImageFormat(renderOptions.get("imageFormat", "png"))
        outputFormat = "JPEG" if imageFormat == "jpeg" else "PNG"
        cmd2 = ["gdal_translate", "-of", outputFormat, "-co", "WORLDFILE=NO"]
        stretchType = str(renderOptions.get("stretchType", "none")).strip().lower()
        if stretchType not in ("minmax", "percent"):
            cmd2 += ["-ot", "Byte", "-scale_1", "-scale_2", "-scale_3"]
        if imageFormat == "jpeg":
            jpegQuality = normalizeInt(renderOptions.get("jpegQuality"), 85, 1, 100)
            cmd2 += ["-co", f"QUALITY={jpegQuality}", "-co", "PROGRESSIVE=ON", "-b", "1", "-b", "2", "-b", "3"]
        else:
            pngCompression = normalizeInt(renderOptions.get("pngCompression"), 6, 0, 9)
            cmd2 += ["-co", f"ZLEVEL={pngCompression}"]
        cmd2 += [tempTileFile, tileFile]
        result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=90, env=env)
        if os.path.exists(tempTileFile):
            os.remove(tempTileFile)
        if result2.returncode == 0:
            return {
                "success": True,
                "tileFile": tileFile,
                "sourceCount": len(sourceFileList),
                "method": "gdalwarp+gdal_translate",
                "tilePath": f"{zoom}/{tileX}/{outputY}",
            }
        return {"success": False, "error": f"gdal_translate 失败: {result2.stderr}"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def processSingleTileFromIndex(tileInfo, tilesDir, resampling="near", render_options=None):
    try:
        zoom, tileX, tileY = tileInfo["z"], tileInfo["x"], tileInfo["y"]
        tileBounds = tileInfo["bounds"]
        sourceFiles = tileInfo["sourceFiles"]
        renderOptions = render_options or {}
        tileFile, outputY, _ = getTileOutputPath(tilesDir, zoom, tileX, tileY, renderOptions)

        sourceFileList = []
        for sourceFile in sourceFiles:
            filePath = sourceFile["file"] if isinstance(sourceFile, dict) else sourceFile
            if not os.path.isabs(filePath):
                filePath = os.path.join(config["dataSourceDir"], filePath)
            preparedFile = preprocessMultibandSource(filePath, renderOptions=renderOptions)
            if preparedFile:
                sourceFileList.append(preparedFile)
        if not sourceFileList:
            return {"success": False, "error": "没有可用于当前瓦片的有效源文件"}

        tempTileFile = os.path.splitext(tileFile)[0] + "_temp.tif"
        west, south, east, north = tileBounds
        overlap = 0.0001
        expandedBounds = [west - overlap, south - overlap, east + overlap, north + overlap]
        projection = normalizeProjection(renderOptions.get("projection", "EPSG:3857"))
        threadCount = getThreadSettings(renderOptions)
        cmd = [
            "gdalwarp",
            "-te",
            str(expandedBounds[0]),
            str(expandedBounds[1]),
            str(expandedBounds[2]),
            str(expandedBounds[3]),
            "-te_srs",
            "EPSG:4326",
            "-ts",
            "256",
            "256",
            "-r",
            resampling,
            "-t_srs",
            projection,
            "-of",
            "GTiff",
            "-co",
            "TILED=YES",
            "-co",
            "COMPRESS=LZW",
            "-co",
            "BIGTIFF=IF_SAFER",
            "-dstalpha",
            "-multi",
            "-wo",
            f"NUM_THREADS={threadCount}",
        ] + getNodataArgs(renderOptions) + sourceFileList + [tempTileFile]
        env = os.environ.copy()
        env["GDAL_NUM_THREADS"] = str(threadCount)
        env["OMP_NUM_THREADS"] = str(threadCount)
        warpProcess = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
        if warpProcess.returncode != 0:
            return {"success": False, "error": f"gdalwarp 失败: {warpProcess.stderr}"}

        imageFormat = normalizeImageFormat(renderOptions.get("imageFormat", "png"))
        outputFormat = "JPEG" if imageFormat == "jpeg" else "PNG"
        cmd2 = ["gdal_translate", "-of", outputFormat, "-co", "WORLDFILE=NO"]
        stretchType = str(renderOptions.get("stretchType", "none")).strip().lower()
        if stretchType not in ("minmax", "percent"):
            cmd2 += ["-ot", "Byte", "-scale_1", "-scale_2", "-scale_3"]
        if imageFormat == "jpeg":
            jpegQuality = normalizeInt(renderOptions.get("jpegQuality"), 85, 1, 100)
            cmd2 += ["-co", f"QUALITY={jpegQuality}", "-co", "PROGRESSIVE=ON", "-b", "1", "-b", "2", "-b", "3"]
        else:
            pngCompression = normalizeInt(renderOptions.get("pngCompression"), 6, 0, 9)
            cmd2 += ["-co", f"ZLEVEL={pngCompression}"]
        cmd2 += [tempTileFile, tileFile]
        translateProcess = subprocess.run(cmd2, capture_output=True, text=True, timeout=120, env=env)
        if os.path.exists(tempTileFile):
            os.remove(tempTileFile)
        if translateProcess.returncode == 0:
            return {
                "success": True,
                "tileFile": tileFile,
                "sourceCount": len(sourceFileList),
                "method": "indexed-gdalwarp+gdal_translate",
                "tilePath": f"{zoom}/{tileX}/{outputY}",
            }
        return {"success": False, "error": f"gdal_translate 失败: {translateProcess.stderr}"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def processTileBatch(tiles, outputPath, resampling, batchIdx, stop_flag_file=None, render_options=None):
    processed = 0
    failed = 0
    errors = []
    for tile in tiles:
        if stop_flag_file and os.path.exists(stop_flag_file):
            return {"processed": processed, "failed": failed, "batch_idx": batchIdx, "stopped": True, "errors": errors}
        try:
            result = processSingleTileOptimized(tile, outputPath, resampling, render_options=render_options)
            if result["success"]:
                processed += 1
            else:
                failed += 1
                if len(errors) < 3:
                    tilePath = f"{tile.get('z', '?')}/{tile.get('x', '?')}/{tile.get('y', '?')}"
                    errors.append(f"{tilePath}: {result.get('error', '未知错误')}")
        except Exception as exc:
            failed += 1
            if len(errors) < 3:
                tilePath = f"{tile.get('z', '?')}/{tile.get('x', '?')}/{tile.get('y', '?')}"
                errors.append(f"{tilePath}: {exc}")
    return {"processed": processed, "failed": failed, "batch_idx": batchIdx, "stopped": False, "errors": errors}


def processHighPerformanceTiles(tileIndex, outputPath, resampling="near", max_workers=None, batch_size=50, user_processes=None, taskId=None, render_options=None):
    import multiprocessing as mp

    totalTiles = len(tileIndex)
    startTime = time.time()
    if max_workers is None:
        cpuCount = mp.cpu_count()
        if user_processes and user_processes > 0:
            max_workers = user_processes
        elif totalTiles < 100:
            max_workers = min(4, cpuCount)
        elif totalTiles < 1000:
            max_workers = min(cpuCount, 32)
        else:
            max_workers = min(cpuCount * 2, 32)

    stopFlagFile = f"/tmp/stop_flag_{taskId}.txt" if taskId else None
    if taskId:
        def stop_checker():
            while True:
                try:
                    with taskLock:
                        taskData = taskStatus.get(taskId)
                    if taskData and taskData.get("status") == "stopped":
                        if stopFlagFile:
                            with open(stopFlagFile, "w", encoding="utf-8") as file_obj:
                                file_obj.write("STOP")
                        break
                    time.sleep(1)
                except Exception:
                    time.sleep(1)

        threading.Thread(target=stop_checker, daemon=True).start()

    batch_size = calculateOptimalBatchSize(totalTiles, max_workers)
    batches = []
    for index in range(0, totalTiles, batch_size):
        batches.append({"tiles": tileIndex[index : index + batch_size], "batch_idx": index // batch_size, "stop_flag_file": stopFlagFile})

    processedTiles = 0
    failedTiles = 0
    batchResults = []
    errorSamples = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futureToBatch = {
            executor.submit(
                processTileBatch,
                batch["tiles"],
                outputPath,
                resampling,
                batch["batch_idx"],
                batch["stop_flag_file"],
                render_options,
            ): batch
            for batch in batches
        }
        for future in as_completed(futureToBatch):
            batch = futureToBatch[future]
            try:
                result = future.result()
                processedTiles += result["processed"]
                failedTiles += result["failed"]
                batchResults.append(result)
                if result.get("errors"):
                    remain = 5 - len(errorSamples)
                    if remain > 0:
                        errorSamples.extend(result["errors"][:remain])
                if result.get("stopped", False):
                    for pendingFuture in futureToBatch:
                        if not pendingFuture.done():
                            pendingFuture.cancel()
                    break
            except Exception as exc:
                failedTiles += len(batch["tiles"])
                if len(errorSamples) < 5:
                    errorSamples.append(f"batch {batch['batch_idx']}: {exc}")

    if stopFlagFile and os.path.exists(stopFlagFile):
        os.remove(stopFlagFile)

    totalTime = time.time() - startTime
    averageSpeed = processedTiles / totalTime if totalTime > 0 else 0
    if processedTiles == 0 and failedTiles > 0:
        errorMessage = " | ".join(errorSamples[:3]) if errorSamples else "所有批次都处理失败"
        return {
            "success": False,
            "error": f"批处理失败: {errorMessage}",
            "processed_tiles": processedTiles,
            "failed_tiles": failedTiles,
            "total_tiles": totalTiles,
            "batch_results": batchResults,
            "error_samples": errorSamples,
            "average_speed": averageSpeed,
            "total_time": totalTime,
            "batch_size": batch_size,
            "max_workers": max_workers,
        }

    return {
        "success": True,
        "processed_tiles": processedTiles,
        "failed_tiles": failedTiles,
        "total_tiles": totalTiles,
        "batch_results": batchResults,
        "error_samples": errorSamples,
        "average_speed": averageSpeed,
        "total_time": totalTime,
        "batch_size": batch_size,
        "max_workers": max_workers,
    }


def processUltraHighPerformanceTiles(
    tileIndex,
    outputPath,
    resampling="near",
    max_workers=None,
    enable_memory_cache=True,
    enable_async_io=True,
    user_processes=None,
    user_memory_gb=None,
    render_options=None,
):
    """
    极致高性能瓦片处理。

    当前主流程默认仍走常规高性能批处理，但这里保留 ultra 模式实现，
    方便后续在资源充足场景下单独启用或做 A/B 对比。
    """
    import concurrent.futures
    import multiprocessing as mp

    try:
        import psutil

        system_memory_gb = psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        system_memory_gb = 8.0

    total_tiles = len(tileIndex)
    cpu_count = mp.cpu_count()
    effective_memory_gb = user_memory_gb if user_memory_gb is not None else system_memory_gb
    render_options = dict(render_options or {})
    transparency_threshold = normalizeFloat(render_options.get("transparencyThreshold"), 0.1)

    logMessage("启动极致高性能瓦片处理")
    logMessage(f"系统配置: {cpu_count} 核 CPU, {system_memory_gb:.1f}GB 内存")
    if user_memory_gb is not None:
        logMessage(f"使用用户指定内存: {user_memory_gb:.1f}GB (系统内存: {system_memory_gb:.1f}GB)")
    else:
        logMessage(f"使用系统内存: {system_memory_gb:.1f}GB")
    logMessage(f"处理目标: {total_tiles} 瓦片")

    if max_workers is None:
        if user_processes and user_processes > 0:
            max_workers = user_processes
            logMessage(f"ultra 模式使用用户指定进程数: {max_workers}")
        else:
            max_workers = min(cpu_count * 3, 128)
            logMessage(f"ultra 模式自动计算进程数: {max_workers}")

    ultra_batch_size = calculateUltraBatchSize(total_tiles, max_workers, effective_memory_gb)
    logMessage(f"ultra 参数: {max_workers} 进程, 超级批量 {ultra_batch_size}")

    memory_cache = {}
    if enable_memory_cache and effective_memory_gb > 32:
        logMessage("启动内存缓存策略，预加载 TIF 到内存")
        memory_cache = preloadTifFilesToMemory(tileIndex, effective_memory_gb)
        logMessage(f"内存缓存完成: {len(memory_cache)} 个文件已缓存")

    start_time = time.time()
    stats = {
        "processed": 0,
        "failed": 0,
        "start_time": start_time,
        "batches_completed": 0,
        "current_speed": 0.0,
        "average_speed": 0.0,
        "peak_speed": 0.0,
        "memory_cache_enabled": enable_memory_cache,
        "async_io_enabled": enable_async_io,
    }

    tile_ultra_batches = []
    for index in range(0, total_tiles, ultra_batch_size):
        tile_ultra_batches.append(tileIndex[index : index + ultra_batch_size])

    logMessage(f"超级批量分组: {len(tile_ultra_batches)} 个批次")

    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_batch = {}
            for batch_idx, tile_batch in enumerate(tile_ultra_batches):
                future = executor.submit(
                    processUltraTileBatch,
                    tile_batch,
                    outputPath,
                    resampling,
                    transparency_threshold,
                    batch_idx,
                    memory_cache,
                    enable_async_io,
                    render_options,
                )
                future_to_batch[future] = batch_idx

            completed_batches = 0
            last_update_time = start_time
            for future in concurrent.futures.as_completed(future_to_batch):
                batch_idx = future_to_batch[future]
                try:
                    result = future.result()
                    stats["processed"] += result["processed"]
                    stats["failed"] += result["failed"]
                    completed_batches += 1

                    current_time = time.time()
                    elapsed = current_time - start_time
                    current_speed = stats["processed"] / elapsed if elapsed > 0 else 0
                    stats["peak_speed"] = max(stats["peak_speed"], current_speed)
                    stats["current_speed"] = current_speed
                    stats["average_speed"] = current_speed
                    stats["batches_completed"] = completed_batches

                    if current_time - last_update_time >= 1.0:
                        logMessage(
                            f"ultra 实时性能: {current_speed:.1f} 瓦片/秒 | "
                            f"已完成: {stats['processed']}/{total_tiles}"
                        )
                        last_update_time = current_time
                except Exception as exc:
                    logMessage(f"ultra 批次 {batch_idx} 处理失败: {exc}", "ERROR")
                    stats["failed"] += len(tile_ultra_batches[batch_idx])

        total_time = time.time() - start_time
        final_speed = stats["processed"] / total_time if total_time > 0 else 0
        baseline_speed = 25
        improvement_factor = final_speed / baseline_speed if baseline_speed > 0 else 0

        logMessage("极致性能处理完成")
        logMessage(f"最终统计: {stats['processed']} 成功, {stats['failed']} 失败")
        logMessage(f"性能指标: 平均 {final_speed:.1f} 瓦片/秒, 峰值 {stats['peak_speed']:.1f} 瓦片/秒")
        logMessage(f"总耗时: {total_time:.2f} 秒")
        logMessage(f"性能提升: {improvement_factor:.1f} 倍 (相对基准 {baseline_speed} 瓦片/秒)")

        stats["final_speed"] = final_speed
        stats["total_time"] = total_time
        stats["improvement_factor"] = improvement_factor
    finally:
        if memory_cache:
            logMessage("清理内存缓存")
            memory_cache.clear()

    return stats


def calculateUltraBatchSize(total_tiles, max_workers, memory_gb):
    """计算 ultra 模式的超级批量大小。"""
    base_batch = max(50, total_tiles // max(1, max_workers * 4))
    if memory_gb >= 64:
        memory_factor = min(4.0, memory_gb / 32)
        ultra_batch = int(base_batch * memory_factor)
    elif memory_gb >= 32:
        ultra_batch = int(base_batch * 2)
    else:
        ultra_batch = base_batch
    ultra_batch = max(20, min(ultra_batch, 500))
    logMessage(f"超级批量计算: 基础 {base_batch} -> 超级 {ultra_batch} (内存因子: {memory_gb / 32:.1f})")
    return ultra_batch


def preloadTifFilesToMemory(tileIndex, memory_gb):
    """将部分源 TIF 预加载到内存，优先用内存换吞吐。"""
    memory_cache = {}
    available_memory_gb = memory_gb * 0.75
    if available_memory_gb < 8:
        logMessage("内存不足，跳过 TIF 预加载", "WARNING")
        return memory_cache

    logMessage(f"开始预加载 TIF 文件，可用内存: {available_memory_gb:.1f}GB")
    source_files = set()
    for tile_info in tileIndex:
        for source_file in tile_info.get("sourceFiles", []):
            source_files.add(source_file["file"])

    source_files = list(source_files)
    total_files = len(source_files)
    loaded_files = 0
    used_memory_gb = 0.0
    logMessage(f"发现 {total_files} 个唯一 TIF 文件需要预加载")

    for file_path in source_files:
        try:
            file_size_gb = os.path.getsize(file_path) / (1024 ** 3)
            if used_memory_gb + file_size_gb > available_memory_gb:
                logMessage(f"达到内存限制，停止预加载。已加载: {loaded_files}/{total_files}")
                break

            with open(file_path, "rb") as file_obj:
                memory_cache[file_path] = file_obj.read()

            used_memory_gb += file_size_gb
            loaded_files += 1
            if loaded_files % 10 == 0:
                logMessage(
                    f"预加载进度: {loaded_files}/{total_files}, "
                    f"内存使用: {used_memory_gb:.1f}GB/{available_memory_gb:.1f}GB"
                )
        except Exception as exc:
            logMessage(f"预加载文件失败: {file_path} - {exc}", "WARNING")

    cache_efficiency = (loaded_files / total_files) * 100 if total_files > 0 else 0
    logMessage(f"TIF 预加载完成: {loaded_files}/{total_files} ({cache_efficiency:.1f}%)")
    logMessage(f"缓存统计: {used_memory_gb:.1f}GB 内存, {len(memory_cache)} 个文件")
    return memory_cache


def processUltraTileBatch(
    tile_batch,
    outputPath,
    resampling,
    transparency_threshold,
    batch_idx,
    memory_cache=None,
    enable_async_io=True,
    render_options=None,
):
    """在子进程中处理一组 ultra 批次瓦片。"""
    import concurrent.futures
    import tempfile

    processed = 0
    failed = 0
    batch_start_time = time.time()
    render_options = dict(render_options or {})

    with tempfile.TemporaryDirectory(prefix=f"ultra_batch_{batch_idx}_") as temp_dir:
        if enable_async_io:
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as io_executor:
                prep_futures = []
                for tile_info in tile_batch:
                    future = io_executor.submit(prepareTileDataAsync, tile_info, memory_cache, temp_dir)
                    prep_futures.append((future, tile_info))

                for future, tile_info in prep_futures:
                    try:
                        prepared_data = future.result()
                        if not prepared_data["success"]:
                            failed += 1
                            continue

                        result = processSingleTileVectorized(
                            tile_info,
                            outputPath,
                            resampling,
                            transparency_threshold,
                            prepared_data,
                            temp_dir,
                            render_options=render_options,
                        )
                        if result["success"]:
                            processed += 1
                        else:
                            failed += 1
                    except Exception:
                        failed += 1
        else:
            for tile_info in tile_batch:
                try:
                    result = processSingleTileOptimized(
                        tile_info,
                        outputPath,
                        resampling,
                        temp_dir=temp_dir,
                        render_options=render_options,
                    )
                    if result["success"]:
                        processed += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1

    batch_time = time.time() - batch_start_time
    batch_speed = processed / batch_time if batch_time > 0 else 0
    return {
        "processed": processed,
        "failed": failed,
        "batch_idx": batch_idx,
        "batch_time": batch_time,
        "batch_speed": batch_speed,
    }


def prepareTileDataAsync(tile_info, memory_cache, temp_dir):
    """预先准备瓦片渲染所需的输入文件。"""
    try:
        source_files = tile_info.get("sourceFiles", [])
        if not source_files:
            return {"success": False, "error": "没有源文件"}

        prepared_files = []
        for source_file in source_files:
            file_path = source_file["file"]
            if memory_cache and file_path in memory_cache:
                temp_file = os.path.join(temp_dir, f"cached_{os.path.basename(file_path)}")
                with open(temp_file, "wb") as file_obj:
                    file_obj.write(memory_cache[file_path])
                prepared_files.append({"file": temp_file, "source": "memory_cache"})
            else:
                prepared_files.append({"file": file_path, "source": "disk"})

        return {
            "success": True,
            "prepared_files": prepared_files,
            "tile_info": tile_info,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def processSingleTileVectorized(
    tile_info,
    tiles_dir,
    resampling,
    transparency_threshold,
    prepared_data,
    temp_dir,
    render_options=None,
):
    """
    Render one tile in the ultra-high-performance pipeline.

    prepared_data is produced by prepareTileDataAsync and may reference files
    staged from memory cache or directly from disk.
    """
    try:
        zoom, tileX, tileY = tile_info["z"], tile_info["x"], tile_info["y"]
        tileBounds = tile_info["bounds"]
        prepared_files = prepared_data["prepared_files"]
        renderOptions = render_options or {}
        tileFile, outputY, _ = getTileOutputPath(tiles_dir, zoom, tileX, tileY, renderOptions)
        if os.path.exists(tileFile) and os.path.getsize(tileFile) > 0:
            return {
                "success": True,
                "tileFile": tileFile,
                "skipped": True,
                "method": "vectorized(existing)",
            }

        sourceFileList = []
        for prepared_file in prepared_files:
            filePath = prepared_file["file"] if isinstance(prepared_file, dict) else prepared_file
            if not os.path.isabs(filePath):
                filePath = os.path.join(config["dataSourceDir"], filePath)
            preparedFile = preprocessMultibandSource(filePath, renderOptions=renderOptions)
            if preparedFile:
                sourceFileList.append(preparedFile)
        if not sourceFileList:
            return {"success": False, "error": "向量化路径没有可用于当前瓦片的有效源文件"}

        tempTileFile = os.path.join(temp_dir, f"vec_tile_{zoom}_{tileX}_{tileY}.tif")
        projection = normalizeProjection(renderOptions.get("projection", "EPSG:3857"))
        threadCount = getThreadSettings(renderOptions)
        cmd = [
            "gdalwarp",
            "-te",
            str(tileBounds[0]),
            str(tileBounds[1]),
            str(tileBounds[2]),
            str(tileBounds[3]),
            "-te_srs",
            "EPSG:4326",
            "-ts",
            "256",
            "256",
            "-r",
            resampling,
            "-t_srs",
            projection,
            "-of",
            "GTiff",
            "-co",
            "TILED=YES",
            "-co",
            "COMPRESS=LZW",
            "-dstalpha",
            "-multi",
            "-wm",
            "256",
            "-wo",
            f"NUM_THREADS={threadCount}",
            "-q",
        ] + getNodataArgs(renderOptions) + sourceFileList + [tempTileFile]
        env = os.environ.copy()
        env["GDAL_NUM_THREADS"] = str(threadCount)
        env["OMP_NUM_THREADS"] = str(threadCount)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
        if result.returncode != 0 or not os.path.exists(tempTileFile):
            return {"success": False, "error": f"向量化 gdalwarp 失败: {result.stderr}"}

        imageFormat = normalizeImageFormat(renderOptions.get("imageFormat", "png"))
        outputFormat = "JPEG" if imageFormat == "jpeg" else "PNG"
        translateCmd = ["gdal_translate", "-of", outputFormat, "-co", "WORLDFILE=NO"]
        stretchType = str(renderOptions.get("stretchType", "none")).strip().lower()
        if stretchType not in ("minmax", "percent"):
            translateCmd += ["-ot", "Byte", "-scale_1", "-scale_2", "-scale_3"]
        if imageFormat == "jpeg":
            jpegQuality = normalizeInt(renderOptions.get("jpegQuality"), 85, 1, 100)
            translateCmd += ["-co", f"QUALITY={jpegQuality}", "-co", "PROGRESSIVE=ON", "-b", "1", "-b", "2", "-b", "3"]
        else:
            pngCompression = normalizeInt(renderOptions.get("pngCompression"), 6, 0, 9)
            translateCmd += ["-co", f"ZLEVEL={pngCompression}"]
        translateCmd += [tempTileFile, tileFile]
        translateResult = subprocess.run(translateCmd, capture_output=True, text=True, timeout=120, env=env)
        try:
            if os.path.exists(tempTileFile):
                os.remove(tempTileFile)
        except Exception:
            pass
        if translateResult.returncode != 0:
            return {"success": False, "error": f"向量化 gdal_translate 失败: {translateResult.stderr}"}

        return {
            "success": True,
            "tileFile": tileFile,
            "sourceCount": len(sourceFileList),
            "method": "vectorized-gdalwarp+gdal_translate",
            "tilePath": f"{zoom}/{tileX}/{outputY}",
            "transparencyThreshold": transparency_threshold,
        }
    except Exception as exc:
        return {"success": False, "error": f"向量化瓦片处理异常: {exc}"}


def checkTileHasNodata(tileFile, transparencyThreshold=0.1):
    try:
        from PIL import Image
        import numpy as np

        threshold = normalizeFloat(transparencyThreshold, 0.1)
        if threshold > 1:
            threshold = threshold / 100.0
        threshold = max(0.0, min(1.0, threshold))
        with Image.open(tileFile) as img:
            if img.size != (256, 256):
                return True
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            alphaChannel = np.array(img)[:, :, 3]
            transparentMask = alphaChannel < 255
            transparentCount = int(np.count_nonzero(transparentMask))
            transparentRatio = transparentCount / float(transparentMask.size)
            if threshold <= 0:
                return transparentCount > 0
            return transparentRatio >= threshold
    except Exception:
        try:
            result = subprocess.run(["gdalinfo", "-stats", tileFile], capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return True
            output = result.stdout
            hasNodata = "NoData Value=" in output
            hasAlphaTransparency = "ColorInterp=Alpha" in output and ("Min=0" in output or "Minimum=0" in output)
            return hasNodata or hasAlphaTransparency
        except Exception:
            return True


def deleteNodataTilesInternal(tilesPath, includeDetails=True, transparencyThreshold=0.1):
    try:
        fullTilesPath = os.path.join(config["tilesDir"], tilesPath)
        if not os.path.exists(fullTilesPath):
            return {"success": False, "error": f"瓦片目录不存在: {fullTilesPath}"}

        threshold = normalizeFloat(transparencyThreshold, 0.1)
        if threshold > 1:
            threshold = threshold / 100.0
        threshold = max(0.0, min(1.0, threshold))

        totalChecked = 0
        deletedCount = 0
        errorCount = 0
        deletedFiles = []
        for root, _, files in os.walk(fullTilesPath):
            for file in files:
                if not file.lower().endswith(".png"):
                    continue
                filePath = os.path.join(root, file)
                totalChecked += 1
                try:
                    if checkTileHasNodata(filePath, threshold):
                        os.remove(filePath)
                        deletedCount += 1
                        if includeDetails:
                            deletedFiles.append(os.path.relpath(filePath, fullTilesPath))
                except Exception:
                    errorCount += 1

        cleanedDirs = 0
        for root, dirs, _ in os.walk(fullTilesPath, topdown=False):
            for dirName in dirs:
                dirPath = os.path.join(root, dirName)
                try:
                    os.rmdir(dirPath)
                    cleanedDirs += 1
                except OSError:
                    pass

        result = {
            "success": True,
            "summary": {
                "total_checked": totalChecked,
                "deleted_count": deletedCount,
                "error_count": errorCount,
                "cleaned_dirs": cleanedDirs,
                "transparency_threshold": threshold,
            },
            "message": f"删除完成！检查了 {totalChecked} 个瓦片，删除了 {deletedCount} 个达到透明阈值的瓦片，清理了 {cleanedDirs} 个空目录",
        }
        if includeDetails:
            result["deleted_files"] = deletedFiles
        return result
    except Exception as exc:
        return {"success": False, "error": f"删除透明瓦片时发生错误: {exc}"}


def deleteNodataTiles():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "缺少请求参数"}), 400
        tilesPath = data.get("tilesPath")
        if not tilesPath:
            return jsonify({"error": "缺少瓦片目录路径参数 tilesPath"}), 400
        includeDetails = data.get("includeDetails", True)
        transparencyThreshold = data.get("transparencyThreshold", 0.1)
        result = deleteNodataTilesInternal(tilesPath, includeDetails, transparencyThreshold)
        if result["success"]:
            return jsonify(result)
        return jsonify(result), 400
    except Exception as exc:
        errorMessage = f"删除透明瓦片请求处理失败: {exc}"
        logMessage(errorMessage, "ERROR")
        return jsonify({"error": errorMessage}), 500


def scanNodataTiles():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "缺少请求参数"}), 400
        tilesPath = data.get("tilesPath")
        if not tilesPath:
            return jsonify({"error": "缺少瓦片目录路径参数 tilesPath"}), 400

        fullTilesPath = os.path.join(config["tilesDir"], tilesPath)
        if not os.path.exists(fullTilesPath):
            return jsonify({"error": f"瓦片目录不存在: {fullTilesPath}"}), 404

        threshold = normalizeFloat(data.get("transparencyThreshold", 0.1), 0.1)
        if threshold > 1:
            threshold = threshold / 100.0
        threshold = max(0.0, min(1.0, threshold))

        totalChecked = 0
        nodataCount = 0
        validCount = 0
        errorCount = 0
        nodataFiles = []
        zoomStats = {}

        for root, _, files in os.walk(fullTilesPath):
            for file in files:
                if not file.lower().endswith(".png"):
                    continue
                filePath = os.path.join(root, file)
                totalChecked += 1
                relPath = os.path.relpath(filePath, fullTilesPath)
                pathParts = relPath.split(os.sep)
                zoomLevel = pathParts[0] if pathParts and pathParts[0].isdigit() else "unknown"
                try:
                    if checkTileHasNodata(filePath, threshold):
                        nodataCount += 1
                        nodataFiles.append(relPath)
                        zoomStats.setdefault(zoomLevel, {"total": 0, "nodata": 0})
                        zoomStats[zoomLevel]["nodata"] += 1
                    else:
                        validCount += 1
                    zoomStats.setdefault(zoomLevel, {"total": 0, "nodata": 0})
                    zoomStats[zoomLevel]["total"] += 1
                except Exception:
                    errorCount += 1

        result = {
            "success": True,
            "summary": {
                "totalChecked": totalChecked,
                "nodataTiles": nodataCount,
                "validTiles": validCount,
                "errors": errorCount,
                "nodataPercentage": round((nodataCount / totalChecked * 100), 2) if totalChecked > 0 else 0,
                "transparencyThreshold": threshold,
            },
            "zoomLevelStats": zoomStats,
            "message": f"扫描完成！检查了 {totalChecked} 个瓦片，发现 {nodataCount} 个达到透明阈值的瓦片",
        }
        if data.get("includeDetails", False) and nodataFiles:
            result["nodataFiles"] = nodataFiles[:100]
            if len(nodataFiles) > 100:
                result["note"] = f"透明文件过多，仅显示前100个，总共发现 {len(nodataFiles)} 个透明文件"
        return jsonify(result)
    except Exception as exc:
        errorMessage = f"扫描透明瓦片失败: {exc}"
        logMessage(errorMessage, "ERROR")
        return jsonify({"error": errorMessage}), 500


def generateShapefileIndex(tileIndex, outputPath, generateShp=True):
    try:
        indexKey = [f"{tile['z']}/{tile['x']}/{tile['y']}" for tile in tileIndex]
        currentHash = hashlib.md5("|".join(sorted(indexKey)).encode("utf-8")).hexdigest()
        geojsonFile = os.path.join(outputPath, "tile_index.geojson")
        shpFile = os.path.join(outputPath, "tile_index.shp")
        hashFile = os.path.join(outputPath, ".tile_index_hash")
        canReuse = False
        if os.path.exists(hashFile):
            try:
                with open(hashFile, "r", encoding="utf-8") as file_obj:
                    existingHash = file_obj.read().strip()
                if existingHash == currentHash:
                    if os.path.exists(geojsonFile) and os.path.exists(shpFile):
                        canReuse = True
                    elif os.path.exists(geojsonFile):
                        canReuse = "geojson_only"
            except Exception:
                canReuse = False
        if canReuse is True:
            return {"success": True, "shpFile": shpFile, "geojsonFile": geojsonFile, "totalFeatures": len(tileIndex), "reused": True}

        features = []
        for tile in tileIndex:
            tileBounds = tile.get("bounds", [])
            if not tileBounds or len(tileBounds) != 4:
                try:
                    z, x, y = tile["z"], tile["x"], tile["y"]
                    west, north = tile2deg(x, y, z)
                    east, south = tile2deg(x + 1, y + 1, z)
                    tileBounds = [west, south, east, north]
                except Exception:
                    continue
            west, south, east, north = tileBounds
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "z": tile["z"],
                        "x": tile["x"],
                        "y": tile["y"],
                        "sourceCount": tile["sourceCount"],
                        "area": tile.get("area", 0),
                        "tileSize": tile.get("tileSize", 256),
                        "sourceFiles": [sourceFile["filename"] for sourceFile in tile["sourceFiles"]],
                        "tilePath": f"{tile['z']}/{tile['x']}/{tile['y']}.png",
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
                    },
                }
            )
        geojson = {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
            "features": features,
        }
        if canReuse != "geojson_only":
            with open(geojsonFile, "w", encoding="utf-8") as file_obj:
                json.dump(geojson, file_obj, indent=2, ensure_ascii=False)
        result = runCommand(["ogr2ogr", "-f", "ESRI Shapefile", "-overwrite", shpFile, geojsonFile])
        with open(hashFile, "w", encoding="utf-8") as file_obj:
            file_obj.write(currentHash)
        if result["success"]:
            return {"success": True, "shpFile": shpFile, "geojsonFile": geojsonFile, "totalFeatures": len(features), "reused": False}
        return {
            "success": True,
            "shpFile": None,
            "geojsonFile": geojsonFile,
            "totalFeatures": len(features),
            "warning": f"SHP转换失败: {result.get('stderr', '未知错误')}",
            "reused": False,
        }
    except Exception as exc:
        logMessage(f"生成Shapefile索引失败: {exc}", "ERROR")
        return {"success": False, "error": str(exc)}


def verifyTilesIntegrity(outputPath, metadata):
    try:
        if not os.path.exists(outputPath):
            return False
        processedTiles = metadata.get("processedTiles", 0)
        if processedTiles == 0:
            return False
        successRate = float(str(metadata.get("successRate", "0%")).replace("%", ""))
        if successRate < 50:
            return False
        tileIndex = metadata.get("tileIndex", [])
        if not tileIndex:
            return False
        sampleSize = min(10, len(tileIndex))
        sampleTiles = random.sample(tileIndex, sampleSize)
        missingCount = 0
        for tile in sampleTiles:
            tilePath = os.path.join(outputPath, str(tile["z"]), str(tile["x"]), f"{tile['y']}.png")
            if not os.path.exists(tilePath):
                missingCount += 1
        return (missingCount / sampleSize) <= 0.3
    except Exception:
        return False


def extractGeographicBounds(gdalinfoOutput: str) -> dict:
    try:
        lines = gdalinfoOutput.split("\n")
        bounds = {}
        coordinateSystemType = None
        for line in lines:
            line = line.strip()
            if line.startswith("PROJCS["):
                coordinateSystemType = "projected"
                break
            if line.startswith("GEOGCS[") or line.startswith("GEOGCRS["):
                coordinateSystemType = "geographic"
                break
        if coordinateSystemType is None:
            return None

        def parseDmsCoordinate(coordStr):
            match = re.search(r"(\d+)d\s*(\d+)'(\d+\.?\d*)\"([EWNS])", coordStr)
            if not match:
                return None
            degrees = float(match.group(1))
            minutes = float(match.group(2))
            seconds = float(match.group(3))
            direction = match.group(4)
            decimalDegrees = degrees + minutes / 60 + seconds / 3600
            if direction in ["W", "S"]:
                decimalDegrees = -decimalDegrees
            return decimalDegrees

        def parseDecimalCoordinate(coordStr):
            numbers = re.findall(r"(-?\d+\.?\d*)", coordStr)
            if len(numbers) >= 2:
                return float(numbers[0]), float(numbers[1])
            return None, None

        cornerSection = False
        for line in lines:
            line = line.strip()
            if line.startswith("Corner Coordinates:"):
                cornerSection = True
                continue
            if cornerSection and line.startswith("Upper Left"):
                parts = line.split(")")
                if coordinateSystemType == "projected" and len(parts) >= 2:
                    coordSection = parts[1].strip().replace("(", "").replace(")", "")
                    if "," in coordSection:
                        lonStr, latStr = coordSection.split(",", 1)
                        lon = parseDmsCoordinate(lonStr.strip())
                        lat = parseDmsCoordinate(latStr.strip())
                        if lon is not None and lat is not None:
                            bounds["upperLeftLon"] = lon
                            bounds["upperLeftLat"] = lat
                elif coordinateSystemType == "geographic" and len(parts) >= 1:
                    coordSection = parts[0].split("(")[1].strip() if "(" in parts[0] else parts[0].strip()
                    lon, lat = parseDecimalCoordinate(coordSection)
                    if lon is not None and lat is not None:
                        bounds["upperLeftLon"] = lon
                        bounds["upperLeftLat"] = lat
            elif cornerSection and line.startswith("Lower Right"):
                parts = line.split(")")
                if coordinateSystemType == "projected" and len(parts) >= 2:
                    coordSection = parts[1].strip().replace("(", "").replace(")", "")
                    if "," in coordSection:
                        lonStr, latStr = coordSection.split(",", 1)
                        lon = parseDmsCoordinate(lonStr.strip())
                        lat = parseDmsCoordinate(latStr.strip())
                        if lon is not None and lat is not None:
                            bounds["lowerRightLon"] = lon
                            bounds["lowerRightLat"] = lat
                elif coordinateSystemType == "geographic" and len(parts) >= 1:
                    coordSection = parts[0].split("(")[1].strip() if "(" in parts[0] else parts[0].strip()
                    lon, lat = parseDecimalCoordinate(coordSection)
                    if lon is not None and lat is not None:
                        bounds["lowerRightLon"] = lon
                        bounds["lowerRightLat"] = lat
        if "upperLeftLon" in bounds and "lowerRightLon" in bounds:
            west = bounds["upperLeftLon"]
            east = bounds["lowerRightLon"]
            north = bounds["upperLeftLat"]
            south = bounds["lowerRightLat"]
            widthDegrees = east - west
            heightDegrees = north - south
            if widthDegrees < 0:
                widthDegrees += 360
            if heightDegrees < 0:
                heightDegrees = abs(heightDegrees)
            bounds.update({"west": west, "east": east, "north": north, "south": south, "widthDegrees": widthDegrees, "heightDegrees": heightDegrees})
        return bounds if bounds else None
    except Exception as exc:
        logMessage(f"提取地理边界失败: {exc}", "ERROR")
        return None


def getFileGeographicBounds(filePath: str) -> dict:
    try:
        result = runCommand(["gdalinfo", filePath])
        if not result["success"]:
            return None
        return extractGeographicBounds(result["stdout"])
    except Exception as exc:
        logMessage(f"获取文件地理边界失败: {filePath}, 错误: {exc}", "ERROR")
        return None


def processIndexedTilesInternal(folderPaths, filePatterns, outputPath, minZoom, maxZoom, tileSize, processes, maxMemory, resampling, generateShpIndex, enableIncrementalUpdate, transparencyThreshold, skipNodataTiles, taskId, renderOptions=None):
    try:
        renderOptions = dict(renderOptions or {})
        relativeTifFiles = findTifFilesInFolders(folderPaths, filePatterns)
        if not relativeTifFiles:
            return {"success": False, "error": "未找到匹配的 TIF 文件"}

        tifFiles = []
        for relativePath in relativeTifFiles:
            fullPath = os.path.join(config["dataSourceDir"], relativePath)
            if os.path.exists(fullPath):
                tifFiles.append(fullPath)
        if not tifFiles:
            return {"success": False, "error": "找到的 TIF 文件都不存在"}

        totalBounds = None
        for filePath in tifFiles:
            fileBounds = getFileGeographicBounds(filePath)
            if not fileBounds or not all(key in fileBounds for key in ["west", "east", "north", "south"]):
                continue
            boundsArray = [fileBounds["west"], fileBounds["south"], fileBounds["east"], fileBounds["north"]]
            if totalBounds is None:
                totalBounds = boundsArray
            else:
                totalBounds = [
                    min(totalBounds[0], boundsArray[0]),
                    min(totalBounds[1], boundsArray[1]),
                    max(totalBounds[2], boundsArray[2]),
                    max(totalBounds[3], boundsArray[3]),
                ]

        indexResult = createTileGridIndex(tifFiles, outputPath, minZoom, maxZoom, tileSize)
        if not indexResult["success"]:
            return {"success": False, "error": f"创建瓦片网格索引失败: {indexResult['error']}"}

        tileIndex = indexResult["tileIndex"]
        totalTiles = len(tileIndex)
        shpResult = generateShapefileIndex(tileIndex, outputPath, generateShpIndex)
        if not shpResult["success"]:
            logMessage(f"生成索引文件失败: {shpResult['error']}", "WARNING")

        requestedThreads = renderOptions.get("threads", 2)
        resourcePlan = recommendIndexedConcurrency(processes, requestedThreads, maxMemory, taskId)
        renderOptions["threads"] = resourcePlan["threads"]

        metadata = {
            "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sourceFiles": [os.path.relpath(filePath, config["dataSourceDir"]) for filePath in tifFiles],
            "totalSourceFiles": len(tifFiles),
            "zoomLevels": f"{minZoom}-{maxZoom}",
            "tileSize": tileSize,
            "totalTiles": totalTiles,
            "processedTiles": 0,
            "failedTiles": 0,
            "successRate": "0%",
            "tileIndex": tileIndex,
            "bounds": totalBounds,
            "method": "indexedTiles-grid-index",
            "resampling": resampling,
            "generateShpIndex": generateShpIndex,
            "enableIncrementalUpdate": enableIncrementalUpdate,
            "transparencyThreshold": transparencyThreshold,
            "renderOptions": renderOptions,
            "resourcePlan": resourcePlan,
        }
        metadataFile = os.path.join(outputPath, "tile_metadata.json")
        with open(metadataFile, "w", encoding="utf-8") as file_obj:
            json.dump(metadata, file_obj, indent=2, ensure_ascii=False)

        batchSize = calculateOptimalBatchSize(totalTiles, resourcePlan["processes"], targetSpeed=1000)
        hpResult = processHighPerformanceTiles(
            tileIndex,
            outputPath,
            resampling,
            max_workers=resourcePlan["processes"],
            batch_size=batchSize,
            user_processes=resourcePlan["processes"],
            taskId=taskId,
            render_options=renderOptions,
        )
        if not hpResult["success"]:
            return {
                "success": False,
                "error": hpResult.get("error", "瓦片批处理失败"),
                "totalTiles": totalTiles,
                "sourceFiles": metadata["sourceFiles"],
                "resourcePlan": resourcePlan,
                "renderOptions": renderOptions,
                "metadataFile": metadataFile,
            }

        processedTiles = hpResult["processed_tiles"]
        failedTiles = hpResult["failed_tiles"]
        deletedNodataTiles = 0
        if skipNodataTiles:
            cleanupResult = deleteNodataTilesInternal(
                os.path.relpath(outputPath, config["tilesDir"]),
                includeDetails=False,
                transparencyThreshold=transparencyThreshold,
            )
            deletedNodataTiles = cleanupResult.get("deleted_count", cleanupResult.get("deletedTiles", 0))

        performanceStats = {
            "averageSpeed": hpResult.get("average_speed", 0),
            "totalTime": hpResult.get("total_time", 0),
            "batchSize": hpResult.get("batch_size", batchSize),
            "maxWorkers": hpResult.get("max_workers", resourcePlan["processes"]),
            "batchCount": len(hpResult.get("batch_results", [])),
        }
        metadata["processedTiles"] = processedTiles
        metadata["failedTiles"] = failedTiles
        metadata["successRate"] = f"{processedTiles / totalTiles * 100:.1f}%" if totalTiles > 0 else "0%"
        metadata["completedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        metadata["deletedNodataTiles"] = deletedNodataTiles
        metadata["performanceStats"] = performanceStats
        metadata["batchResults"] = hpResult.get("batch_results", [])
        metadata["errorSamples"] = hpResult.get("error_samples", [])
        with open(metadataFile, "w", encoding="utf-8") as file_obj:
            json.dump(metadata, file_obj, indent=2, ensure_ascii=False)

        return {
            "success": True,
            "processedTiles": processedTiles,
            "failedTiles": failedTiles,
            "totalTiles": totalTiles,
            "deletedNodataTiles": deletedNodataTiles,
            "outputPath": outputPath,
            "metadataFile": metadataFile,
            "sourceFiles": metadata["sourceFiles"],
            "resourcePlan": resourcePlan,
            "renderOptions": renderOptions,
            "bounds": totalBounds,
            "performanceStats": performanceStats,
            "batchResults": hpResult.get("batch_results", []),
            "errorSamples": hpResult.get("error_samples", []),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def createIndexedTiles():
    try:
        data = request.get_json(silent=True) or {}
        taskId = f"indexedTiles{int(time.time())}"
        folderPaths = data.get("folderPaths", [])
        filePatterns = data.get("filePatterns", [])
        outputPathArray = data.get("outputPath", [])
        minZoom = normalizeInt(data.get("minZoom"), 0, 0)
        maxZoom = normalizeInt(data.get("maxZoom"), 12, minZoom)
        tileSize = normalizeInt(data.get("tileSize"), 256, 64)
        processes = normalizeInt(data.get("processes"), 4, 1, 128)
        threads = normalizeInt(data.get("threads"), 4, 1, 64)
        maxMemory = data.get("maxMemory", "8g")
        resampling = data.get("resampling", "near")
        projection = normalizeProjection(data.get("projection", "EPSG:3857"))
        dataFormat = data.get("dataFormat", "xyz")
        imageFormat = normalizeImageFormat(data.get("imageFormat", "png"))
        tileScheme = normalizeTileScheme(data.get("tileScheme", "tms"))
        redBand = normalizeInt(data.get("redBand"), 1, 1)
        greenBand = normalizeInt(data.get("greenBand"), 2, 1)
        blueBand = normalizeInt(data.get("blueBand"), 3, 1)
        nodataValue = data.get("nodataValue")
        srcNodataValue = normalizeFloat(data.get("srcNodataValue", nodataValue), normalizeFloat(nodataValue, 0.0))
        dstNodataValue = normalizeFloat(data.get("dstNodataValue", nodataValue), normalizeFloat(nodataValue, 0.0))
        stretchType = data.get("stretchType", "none")
        stretchLowPercent = normalizeFloat(data.get("stretchLowPercent"), 2.0)
        stretchHighPercent = normalizeFloat(data.get("stretchHighPercent"), 98.0)
        jpegQuality = normalizeInt(data.get("jpegQuality"), 85, 1, 100)
        pngCompression = normalizeInt(data.get("pngCompression"), 6, 0, 9)
        transparencyThreshold = normalizeFloat(data.get("transparencyThreshold"), 0.1)
        bandMismatchPolicy = normalizeBandMismatchPolicy(data.get("bandMismatchPolicy", "auto"))
        generateShpIndex = bool(data.get("generateShpIndex", True))
        enableIncrementalUpdate = bool(data.get("enableIncrementalUpdate", False))
        skipNodataTiles = bool(data.get("skipNodataTiles", False))
        if skipNodataTiles and imageFormat != "png":
            logMessage("skipNodataTiles 仅在 PNG 输出下生效，已自动禁用", "WARNING")
            skipNodataTiles = False

        renderOptions = {
            "projection": projection,
            "dataFormat": dataFormat,
            "imageFormat": imageFormat,
            "tileScheme": tileScheme,
            "redBand": redBand,
            "greenBand": greenBand,
            "blueBand": blueBand,
            "nodataValue": nodataValue,
            "srcNodata": srcNodataValue,
            "dstNodata": dstNodataValue,
            "stretchType": stretchType,
            "stretchLowPercent": stretchLowPercent,
            "stretchHighPercent": stretchHighPercent,
            "jpegQuality": jpegQuality,
            "pngCompression": pngCompression,
            "transparencyThreshold": transparencyThreshold,
            "bandMismatchPolicy": bandMismatchPolicy,
            "threads": threads,
        }

        errors = []
        if not folderPaths and not hasHttpSourcesInPatterns(filePatterns):
            errors.append("缺少参数: folderPaths")
        if not outputPathArray:
            errors.append("缺少参数: outputPath")

        tifFiles = []
        if not errors:
            relativeTifFiles = findTifFilesInFolders(folderPaths, filePatterns)
            if not relativeTifFiles:
                errors.append("未找到匹配的 TIF 文件")
            else:
                for relativePath in relativeTifFiles:
                    fullPath = os.path.join(config["dataSourceDir"], relativePath)
                    if os.path.exists(fullPath):
                        tifFiles.append(fullPath)
                if not tifFiles:
                    errors.append("匹配结果存在，但源文件都不可用")

        if errors:
            with taskLock:
                taskStatus[taskId] = createTaskRecord(
                    task_id=taskId,
                    status="failed",
                    progress=0,
                    message=f"任务参数校验失败: {'; '.join(errors)}",
                    start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    current_stage="参数校验失败",
                    process_log=[
                        {
                            "stage": "参数校验",
                            "status": "failed",
                            "message": f"任务参数校验失败: {'; '.join(errors)}",
                            "timestamp": datetime.now().isoformat(),
                            "progress": 0,
                            "errors": errors,
                        }
                    ],
                    stats={"totalTiles": 0, "processedTiles": 0, "failedTiles": 0, "remainingTiles": 0, "successRate": "0%"},
                    extra={"errors": errors},
                )
            return jsonify({"success": False, "taskId": taskId, "message": f"任务参数校验失败: {'; '.join(errors)}", "statusUrl": f"/api/tasks/{taskId}", "errors": errors}), 200

        if isinstance(outputPathArray, str):
            outputPath = os.path.join(config["tilesDir"], outputPathArray)
        elif isinstance(outputPathArray, list):
            outputPath = os.path.join(config["tilesDir"], *outputPathArray)
        else:
            outputPath = os.path.join(config["tilesDir"], str(outputPathArray))
        os.makedirs(outputPath, exist_ok=True)
        previewResourcePlan = recommendIndexedConcurrency(processes, threads, maxMemory, taskId)

        def finalize_from_existing_metadata(existingMetadata):
            processedTiles = existingMetadata.get("processedTiles", 0)
            failedTiles = existingMetadata.get("failedTiles", 0)
            totalTiles = existingMetadata.get("totalTiles", 0)
            with taskLock:
                if taskId not in taskStatus:
                    return
                current_task = taskStatus[taskId]
                taskStatus[taskId] = createTaskRecord(
                    task_id=taskId,
                    status="completed",
                    progress=100,
                    message=f"增量模式命中，直接复用已有结果 {processedTiles}/{totalTiles}",
                    start_time=current_task.get("startTime"),
                    end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    current_stage="增量复用完成",
                    process_log=current_task.get("processLog", []),
                    result={
                        "outputPath": outputPath,
                        "outputPathArray": outputPathArray,
                        "metadataFile": os.path.join(outputPath, "tile_metadata.json"),
                        "sourceFiles": existingMetadata.get("sourceFiles", []),
                        "totalSourceFiles": existingMetadata.get("totalSourceFiles", len(tifFiles)),
                        "totalTiles": totalTiles,
                        "processedTiles": processedTiles,
                        "failedTiles": failedTiles,
                        "successRate": existingMetadata.get("successRate", "0%"),
                        "zoomLevels": f"{minZoom}-{maxZoom}",
                        "tileSize": tileSize,
                        "method": "indexedTiles-grid-index",
                        "resourcePlan": existingMetadata.get("resourcePlan", previewResourcePlan),
                        "renderOptions": existingMetadata.get("renderOptions", renderOptions),
                    },
                    stats={
                        "totalTiles": totalTiles,
                        "processedTiles": processedTiles,
                        "failedTiles": failedTiles,
                        "remainingTiles": 0,
                        "averageSpeed": 0,
                        "successRate": existingMetadata.get("successRate", "0%"),
                        "estimatedTimeRemaining": "已完成",
                        "estimatedTimeRemainingSeconds": 0,
                    },
                    processing_info=current_task.get("processingInfo", {}),
                )
                appendTaskLog(taskStatus[taskId], "增量复用", "completed", "检测到完全匹配的元数据与瓦片目录，直接复用历史结果", 100)
            finalizeTaskArtifact(taskId, source_files=existingMetadata.get("sourceFiles", []), build_parameters={"jobType": "indexed_tiles", "minZoom": minZoom, "maxZoom": maxZoom, "tileSize": tileSize, "enableIncrementalUpdate": enableIncrementalUpdate, "reusedExistingMetadata": True})

        def runIndexedTileTask():
            slotAcquired = False
            try:
                with taskLock:
                    taskStatus[taskId] = createTaskRecord(
                        task_id=taskId,
                        status="queued",
                        progress=0,
                        message=f"任务已进入排队，当前重任务并发槽位上限为 {MAX_INDEXED_TASK_SLOTS}",
                        start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        current_stage="排队中",
                        process_log=[
                            {
                                "stage": "任务创建",
                                "status": "completed",
                                "message": f"任务创建完成，已解析到 {len(tifFiles)} 个源文件",
                                "timestamp": datetime.now().isoformat(),
                                "progress": 0,
                                "fileCount": len(tifFiles),
                            }
                        ],
                        stats={
                            "totalTiles": 0,
                            "processedTiles": 0,
                            "failedTiles": 0,
                            "remainingTiles": 0,
                            "currentSpeed": 0,
                            "averageSpeed": 0,
                            "estimatedTimeRemaining": "等待调度",
                            "estimatedTimeRemainingSeconds": 0,
                            "batchesCompleted": 0,
                            "totalBatches": 0,
                            "successRate": "0%",
                        },
                        processing_info=previewResourcePlan,
                    )
                while not slotAcquired:
                    with taskLock:
                        currentTask = taskStatus.get(taskId)
                        if not currentTask:
                            return
                        if currentTask.get("status") == "stopped":
                            return
                    slotAcquired = indexedTaskSemaphore.acquire(timeout=1)
                with taskLock:
                    currentTask = taskStatus.get(taskId)
                    if not currentTask or currentTask.get("status") == "stopped":
                        return
                    currentTask["status"] = "running"
                    currentTask["message"] = "任务已获得执行槽位，开始构建索引与切片"
                    currentTask["currentStage"] = "初始化"
                    appendTaskLog(currentTask, "任务调度", "completed", "任务已获得执行槽位，开始正式执行", 1)

                if enableIncrementalUpdate:
                    metadataFile = os.path.join(outputPath, "tile_metadata.json")
                    if os.path.exists(metadataFile):
                        with open(metadataFile, "r", encoding="utf-8") as file_obj:
                            existingMetadata = json.load(file_obj)
                        existingSourceFiles = set(existingMetadata.get("sourceFiles", []))
                        currentSourceFiles = set(os.path.relpath(filePath, config["dataSourceDir"]) for filePath in tifFiles)
                        if existingSourceFiles == currentSourceFiles and existingMetadata.get("zoomLevels") == f"{minZoom}-{maxZoom}" and existingMetadata.get("tileSize") == tileSize and existingMetadata.get("resampling") == resampling and verifyTilesIntegrity(outputPath, existingMetadata):
                            finalize_from_existing_metadata(existingMetadata)
                            return

                result = processIndexedTilesInternal(folderPaths, filePatterns, outputPath, minZoom, maxZoom, tileSize, processes, maxMemory, resampling, generateShpIndex, enableIncrementalUpdate, transparencyThreshold, skipNodataTiles, taskId, renderOptions)
                with taskLock:
                    currentTask = taskStatus.get(taskId)
                if not currentTask:
                    return
                if result.get("success"):
                    processedTiles = result.get("processedTiles", 0)
                    failedTiles = result.get("failedTiles", 0)
                    totalTiles = result.get("totalTiles", 0)
                    deletedNodataTiles = result.get("deletedNodataTiles", 0)
                    startTimeStr = currentTask.get("startTime")
                    totalSeconds = 0.0
                    if startTimeStr:
                        totalSeconds = max(0.0, (datetime.now() - datetime.strptime(startTimeStr, "%Y-%m-%d %H:%M:%S")).total_seconds())
                    averageSpeed = processedTiles / totalSeconds if totalSeconds > 0 else 0
                    successRate = f"{processedTiles / totalTiles * 100:.1f}%" if totalTiles > 0 else "0%"
                    with taskLock:
                        if taskId not in taskStatus:
                            return
                        taskStatus[taskId] = createTaskRecord(
                            task_id=taskId,
                            status="completed",
                            progress=100,
                            message=f"切片完成 {processedTiles}/{totalTiles}" + (f"，删除空瓦片 {deletedNodataTiles} 个" if deletedNodataTiles > 0 else ""),
                            start_time=startTimeStr,
                            end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            current_stage="完成",
                            process_log=currentTask.get("processLog", []),
                            result={
                                "outputPath": result.get("outputPath"),
                                "outputPathArray": outputPathArray,
                                "metadataFile": result.get("metadataFile"),
                                "sourceFiles": result.get("sourceFiles", []),
                                "totalSourceFiles": len(result.get("sourceFiles", [])),
                                "totalTiles": totalTiles,
                                "processedTiles": processedTiles,
                                "failedTiles": failedTiles,
                                "deletedNodataTiles": deletedNodataTiles,
                                "skipNodataTiles": skipNodataTiles,
                                "successRate": successRate,
                                "zoomLevels": f"{minZoom}-{maxZoom}",
                                "tileSize": tileSize,
                                "method": "indexedTiles-grid-index",
                                "resourcePlan": result.get("resourcePlan", previewResourcePlan),
                                "renderOptions": result.get("renderOptions", renderOptions),
                                "performanceStats": result.get("performanceStats", {}),
                                "bounds": result.get("bounds"),
                            },
                            stats={
                                "totalTiles": totalTiles,
                                "processedTiles": processedTiles,
                                "failedTiles": failedTiles,
                                "deletedNodataTiles": deletedNodataTiles,
                                "remainingTiles": 0,
                                "averageSpeed": round(averageSpeed, 1),
                                "successRate": successRate,
                                "estimatedTimeRemaining": "已完成",
                                "estimatedTimeRemainingSeconds": 0,
                            },
                            processing_info={
                                "previewResourcePlan": previewResourcePlan,
                                "resourcePlan": result.get("resourcePlan", previewResourcePlan),
                                "performanceStats": result.get("performanceStats", {}),
                            },
                        )
                        appendTaskLog(taskStatus[taskId], "切片完成", "completed", f"任务完成，成功 {processedTiles}，失败 {failedTiles}", 100)
                    finalizeTaskArtifact(taskId, source_files=result.get("sourceFiles", []), build_parameters={"jobType": "indexed_tiles", "minZoom": minZoom, "maxZoom": maxZoom, "tileSize": tileSize, "processes": previewResourcePlan["processes"], "threads": previewResourcePlan["threads"], "maxMemory": maxMemory, "resampling": resampling, "skipNodataTiles": skipNodataTiles, "generateShpIndex": generateShpIndex, "enableIncrementalUpdate": enableIncrementalUpdate, "outputPath": outputPathArray})
                else:
                    with taskLock:
                        if taskId not in taskStatus:
                            return
                        taskStatus[taskId] = createTaskRecord(
                            task_id=taskId,
                            status="failed",
                            progress=currentTask.get("progress", 0),
                            message=f"切片失败: {result.get('error', '未知错误')}",
                            start_time=currentTask.get("startTime"),
                            end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            current_stage="失败",
                            process_log=currentTask.get("processLog", []),
                            error=result.get("error", "未知错误"),
                            processing_info=currentTask.get("processingInfo", {}),
                        )
                        appendTaskLog(taskStatus[taskId], "切片失败", "failed", result.get("error", "未知错误"), currentTask.get("progress", 0))
            except Exception as exc:
                with taskLock:
                    if taskId in taskStatus:
                        currentTask = taskStatus.get(taskId, {})
                        taskStatus[taskId] = createTaskRecord(
                            task_id=taskId,
                            status="failed",
                            progress=currentTask.get("progress", 0),
                            message=f"切片任务异常: {exc}",
                            start_time=currentTask.get("startTime"),
                            end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            current_stage="异常退出",
                            process_log=currentTask.get("processLog", []),
                            error=str(exc),
                            processing_info=currentTask.get("processingInfo", {}),
                        )
                        appendTaskLog(taskStatus[taskId], "异常退出", "failed", str(exc), currentTask.get("progress", 0))
                logMessage(f"indexedTiles 任务异常: {taskId} - {exc}", "ERROR")
            finally:
                if slotAcquired:
                    indexedTaskSemaphore.release()
                with taskLock:
                    taskProcesses.pop(taskId, None)

        taskThread = threading.Thread(target=runIndexedTileTask, daemon=True)
        with taskLock:
            taskProcesses[taskId] = taskThread
        taskThread.start()
        return jsonify({
            "success": True,
            "taskId": taskId,
            "status": "queued",
            "message": f"切图任务已创建，识别到 {len(tifFiles)} 个源文件",
            "statusUrl": f"/api/tasks/{taskId}",
            "method": "indexedTiles-grid-index",
            "indexInfo": {
                "totalFiles": len(tifFiles),
                "zoomLevels": f"{minZoom}-{maxZoom}",
                "tileSize": tileSize,
                "projection": projection,
                "dataFormat": dataFormat,
                "imageFormat": imageFormat,
                "tileScheme": tileScheme,
                "bands": {"red": redBand, "green": greenBand, "blue": blueBand},
                "nodataValue": nodataValue,
                "srcNodataValue": srcNodataValue,
                "dstNodataValue": dstNodataValue,
                "stretchType": stretchType,
                "stretchLowPercent": stretchLowPercent,
                "stretchHighPercent": stretchHighPercent,
                "jpegQuality": jpegQuality,
                "pngCompression": pngCompression,
                "bandMismatchPolicy": bandMismatchPolicy,
                "generateShpIndex": generateShpIndex,
                "enableIncrementalUpdate": enableIncrementalUpdate,
                "skipNodataTiles": skipNodataTiles,
                "transparencyThreshold": transparencyThreshold,
            },
            "processingInfo": {
                "autoTuneEnabled": True,
                "maxIndexedTaskSlots": MAX_INDEXED_TASK_SLOTS,
                "requestedProcesses": processes,
                "requestedThreads": threads,
                "previewResourcePlan": previewResourcePlan,
                "processes": previewResourcePlan["processes"],
                "threads": previewResourcePlan["threads"],
                "maxMemory": maxMemory,
                "resampling": resampling,
                "renderOptions": renderOptions,
                "outputPathArray": outputPathArray,
            },
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
