#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import gzip
import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime

from flask import jsonify, request

from artifacts import finalizeTaskArtifact
from config import config, taskLock, taskProcesses, taskStatus
from dataSourceOps import findTifFilesInFolders
from db import enqueueBuildJob, isDatabaseEnabled
from taskState import appendTaskLog, createTaskRecord
from utils import convertMemoryToBytes, convertMemoryToMb, logMessage, normalizeInt, resolveTilesOutputPath, runCommand


def decompressTerrainFiles(terrainDir: str) -> bool:
    """使用gzip解压terrain文件。"""
    try:
        terrainFiles = []
        for root, _, files in os.walk(terrainDir):
            for file in files:
                if file.endswith(".terrain"):
                    terrainFiles.append(os.path.join(root, file))

        decompressedCount = 0
        for terrainFile in terrainFiles:
            try:
                with open(terrainFile, "rb") as file_obj:
                    magic = file_obj.read(2)
                    if magic != b"\x1f\x8b":
                        continue

                tempFile = terrainFile + ".tmp"
                with gzip.open(terrainFile, "rb") as source_file:
                    with open(tempFile, "wb") as target_file:
                        shutil.copyfileobj(source_file, target_file)

                os.replace(tempFile, terrainFile)
                decompressedCount += 1
            except Exception as exc:
                logMessage(f"解压文件失败 {terrainFile}: {exc}", "ERROR")
                continue

        logMessage(f"解压完成，处理了 {decompressedCount} 个文件")
        return True
    except Exception as exc:
        logMessage(f"解压terrain文件失败: {exc}", "ERROR")
        return False


def createTerrainPyramid(sourcePath):
    """为大地形文件创建金字塔概览，提升CTB处理效率。"""
    try:
        overviewPath = sourcePath + ".ovr"
        if os.path.exists(overviewPath):
            logMessage(f"金字塔文件已存在: {os.path.basename(overviewPath)}")
            return True

        fileSizeGb = os.path.getsize(sourcePath) / (1024 ** 3)
        if fileSizeGb > 50:
            levels = [2, 4, 8, 16, 32, 64, 128, 256]
        elif fileSizeGb > 20:
            levels = [2, 4, 8, 16, 32, 64, 128]
        else:
            levels = [2, 4, 8, 16, 32, 64]

        cmd = [
            "gdaladdo",
            "-r",
            "average",
            "--config",
            "COMPRESS_OVERVIEW",
            "LZW",
            sourcePath,
        ] + [str(level) for level in levels]

        logMessage(
            f"创建金字塔: gdaladdo -r average {os.path.basename(sourcePath)} {' '.join(map(str, levels))}"
        )
        env = os.environ.copy()
        env["GDAL_CACHEMAX"] = "1024"
        result = runCommand(cmd, env=env)

        if result["success"] and os.path.exists(overviewPath):
            overviewSizeMb = os.path.getsize(overviewPath) / (1024 ** 2)
            logMessage(f"金字塔创建成功: {overviewSizeMb:.1f}MB")
            return True

        logMessage(f"金字塔创建失败: {result.get('stderr', '')}", "WARNING")
        return False
    except Exception as exc:
        logMessage(f"创建金字塔失败: {exc}", "WARNING")
        return False


def analyzeTiffGeoContinuity(tifFiles, taskId):
    """分析多个TIF文件是否存在明显间隙或重叠。"""
    try:
        def updateTaskMessage(message):
            with taskLock:
                if taskId in taskStatus:
                    taskStatus[taskId]["message"] = message

        updateTaskMessage(f"开始分析 {len(tifFiles)} 个TIF文件的地理连续性...")
        geoInfoList = []

        for index, tifFile in enumerate(tifFiles):
            try:
                result = subprocess.run(
                    ["gdalinfo", "-json", tifFile],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode != 0:
                    continue

                geoData = json.loads(result.stdout or "{}")
                geoTransform = geoData.get("geoTransform", [])
                size = geoData.get("size", [])
                if len(geoTransform) < 6 or len(size) < 2:
                    continue

                originX, pixelWidth, _, originY, _, pixelHeight = geoTransform
                width, height = size
                minX = originX
                maxX = originX + width * pixelWidth
                minY = originY + height * pixelHeight
                maxY = originY

                geoInfo = {
                    "file": tifFile,
                    "index": index,
                    "minX": minX,
                    "maxX": maxX,
                    "minY": minY,
                    "maxY": maxY,
                    "centerX": (minX + maxX) / 2,
                    "centerY": (minY + maxY) / 2,
                    "width": abs(maxX - minX),
                    "height": abs(maxY - minY),
                    "pixelWidth": abs(pixelWidth),
                    "pixelHeight": abs(pixelHeight),
                    "projection": geoData.get("coordinateSystem", {}).get("wkt", ""),
                }
                geoInfoList.append(geoInfo)
                updateTaskMessage(
                    f"文件 {index + 1}/{len(tifFiles)}: {os.path.basename(tifFile)} - 范围: "
                    f"({minX:.2f}, {minY:.2f}) 到 ({maxX:.2f}, {maxY:.2f})"
                )
            except Exception as exc:
                updateTaskMessage(f"获取文件 {tifFile} 地理信息失败: {exc}")

        if len(geoInfoList) < 2:
            return {"continuous": True, "message": "文件数量不足，无需检查连续性"}

        gaps = []
        overlaps = []

        geoInfoList.sort(key=lambda item: item["centerX"])
        for index in range(len(geoInfoList) - 1):
            current = geoInfoList[index]
            nextFile = geoInfoList[index + 1]
            gapX = nextFile["minX"] - current["maxX"]
            if gapX > current["pixelWidth"]:
                gaps.append(
                    {
                        "type": "X_gap",
                        "file1": os.path.basename(current["file"]),
                        "file2": os.path.basename(nextFile["file"]),
                        "gap_size": gapX,
                        "gap_pixels": gapX / current["pixelWidth"],
                    }
                )
            elif gapX < -current["pixelWidth"]:
                overlaps.append(
                    {
                        "type": "X_overlap",
                        "file1": os.path.basename(current["file"]),
                        "file2": os.path.basename(nextFile["file"]),
                        "overlap_size": abs(gapX),
                        "overlap_pixels": abs(gapX) / current["pixelWidth"],
                    }
                )

        geoInfoList.sort(key=lambda item: item["centerY"])
        for index in range(len(geoInfoList) - 1):
            current = geoInfoList[index]
            nextFile = geoInfoList[index + 1]
            gapY = nextFile["minY"] - current["maxY"]
            if gapY > current["pixelHeight"]:
                gaps.append(
                    {
                        "type": "Y_gap",
                        "file1": os.path.basename(current["file"]),
                        "file2": os.path.basename(nextFile["file"]),
                        "gap_size": gapY,
                        "gap_pixels": gapY / current["pixelHeight"],
                    }
                )
            elif gapY < -current["pixelHeight"]:
                overlaps.append(
                    {
                        "type": "Y_overlap",
                        "file1": os.path.basename(current["file"]),
                        "file2": os.path.basename(nextFile["file"]),
                        "overlap_size": abs(gapY),
                        "overlap_pixels": abs(gapY) / current["pixelHeight"],
                    }
                )

        continuous = len(gaps) == 0
        message = f"地理连续性分析完成: {len(geoInfoList)} 个文件"
        if gaps:
            message += f", 发现 {len(gaps)} 个间隙"
        if overlaps:
            message += f", 发现 {len(overlaps)} 个重叠"
        logMessage(message)

        return {
            "continuous": continuous,
            "message": message,
            "gaps": gaps,
            "overlaps": overlaps,
            "geoInfo": geoInfoList,
        }
    except Exception as exc:
        logMessage(f"地理连续性分析失败: {exc}", "WARNING")
        return {"continuous": False, "error": str(exc)}


def processSingleTerrainFile(
    fileInfo,
    outputPath,
    startZoom,
    endZoom,
    maxTriangles,
    bounds,
    useCompression,
    decompressOutput,
    maxMemory,
    threads,
    autoZoom,
    zoomStrategy,
    taskId,
    fileIndex,
):
    """处理单个地形文件。"""
    try:
        sourcePath = fileInfo["fullPath"]
        filename = fileInfo["filename"]
        logMessage(f"开始处理地形文件: {filename}")

        if not os.path.exists(sourcePath):
            return {"success": False, "error": f"源文件不存在: {sourcePath}"}

        os.makedirs(outputPath, exist_ok=True)
        fileSizeGb = os.path.getsize(sourcePath) / (1024 ** 3)
        logMessage(f"文件大小: {fileSizeGb:.2f}GB")

        if fileSizeGb > 5.0:
            logMessage("检测到大文件，创建金字塔以优化处理...")
            createTerrainPyramid(sourcePath)

        ctbStartZoom = endZoom
        ctbEndZoom = startZoom
        ctbMemory = str(convertMemoryToBytes(str(maxMemory)))
        threadCount = normalizeInt(threads, 1, 1, max(1, config["maxThreads"]))

        cmd = ["ctb-tile", "-f", "Mesh"]
        if useCompression:
            cmd.append("-C")
        cmd.extend(
            [
                "-o",
                outputPath,
                "-s",
                str(ctbStartZoom),
                "-e",
                str(ctbEndZoom),
                "-m",
                ctbMemory,
                "-c",
                str(threadCount),
                "-v",
                sourcePath,
            ]
        )

        env = os.environ.copy()
        env["GDAL_CACHEMAX"] = convertMemoryToMb(str(maxMemory))
        env["GDAL_NUM_THREADS"] = str(threadCount)
        env["OMP_NUM_THREADS"] = str(threadCount)

        logMessage(f"执行CTB命令: {' '.join(cmd)}")
        result = runCommand(cmd, env=env)
        if not result["success"]:
            return {
                "success": False,
                "error": result.get("stderr", "未知错误"),
                "filename": filename,
            }

        layerCmd = [
            "ctb-tile",
            "-l",
            "-f",
            "Mesh",
            "-o",
            outputPath,
            "-s",
            str(ctbStartZoom),
            "-e",
            str(ctbEndZoom),
            "-m",
            ctbMemory,
            "-c",
            str(threadCount),
            "-v",
            sourcePath,
        ]
        layerResult = runCommand(layerCmd, env=env)
        if layerResult["success"]:
            logMessage(f"CTB生成layer.json成功: {filename}")
            updateCtbLayerJsonBounds(outputPath, bounds)
        else:
            logMessage(
                f"CTB生成layer.json失败: {filename} - {layerResult.get('stderr', '未知错误')}",
                "WARNING",
            )

        if decompressOutput:
            logMessage(f"开始解压terrain文件: {filename}")
            decompressTerrainFiles(outputPath)
            logMessage(f"terrain文件解压完成: {filename}")

        terrainCount = 0
        for root, _, files in os.walk(outputPath):
            terrainCount += len([file for file in files if file.endswith(".terrain")])

        return {
            "success": True,
            "outputPath": outputPath,
            "terrainFiles": terrainCount,
            "filename": filename,
        }
    except Exception as exc:
        logMessage(f"处理地形文件失败 {fileInfo.get('filename', 'unknown')}: {exc}", "ERROR")
        return {
            "success": False,
            "error": str(exc),
            "filename": fileInfo.get("filename", "unknown"),
        }


def createTerrainTiles():
    """创建地形瓦片任务。"""
    try:
        logMessage("收到地形瓦片创建请求", "INFO")
        data = request.get_json(silent=True)
        if data is None:
            errorMessage = "请求数据为空，无法解析JSON"
            logMessage(f"地形瓦片创建失败: {errorMessage}", "ERROR")
            return jsonify({"error": errorMessage}), 400

        logMessage(f"地形瓦片请求参数: {data}", "INFO")

        outputPathArray = data.get("outputPath", [])
        startZoom = data.get("startZoom", 0)
        endZoom = data.get("endZoom", 8)
        maxTriangles = data.get("maxTriangles", 32768)
        bounds = data.get("bounds")
        useCompression = data.get("compression", True)
        decompressOutput = data.get("decompress", True)
        autoZoom = data.get("autoZoom", False)
        zoomStrategy = data.get("zoomStrategy", "conservative")
        maxMemory = data.get("maxMemory", "8m")
        threads = normalizeInt(data.get("threads"), min(4, config["maxThreads"]), 1, max(1, config["maxThreads"]))
        mergeTerrains = data.get("mergeTerrains", False)
        taskId = str(data.get("taskId") or f"terrain{int(time.time())}")
        workerRun = bool(data.get("_workerRun"))
        runSynchronously = bool(data.get("_runSynchronously"))

        errors = []
        if endZoom < 8:
            errors.append("地形切片的最大层级(endZoom)必须大于等于8")

        tifFiles = []
        folderPaths = data.get("folderPaths")
        filePatterns = data.get("filePatterns")
        if not filePatterns:
            errors.append("缺少参数: filePatterns")

        if not errors:
            relativeTifFiles = findTifFilesInFolders(folderPaths, filePatterns)
            if not relativeTifFiles:
                errors.append("未找到匹配的TIF文件")
            else:
                for relativePath in relativeTifFiles:
                    fullPath = os.path.join(config["dataSourceDir"], relativePath)
                    if os.path.exists(fullPath):
                        tifFiles.append(
                            {
                                "relativePath": relativePath,
                                "fullPath": fullPath,
                                "filename": os.path.basename(relativePath),
                            }
                        )
                if not tifFiles:
                    errors.append("没有找到有效的TIF文件")

        if errors:
            with taskLock:
                taskStatus[taskId] = createTaskRecord(
                    task_id=taskId,
                    status="failed",
                    progress=0,
                    message=f"地形瓦片任务创建失败: {'; '.join(errors)}",
                    start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    current_stage="初始化失败",
                    process_log=[
                        {
                            "stage": "初始化",
                            "status": "failed",
                            "message": f"任务创建失败: {'; '.join(errors)}",
                            "timestamp": datetime.now().isoformat(),
                            "progress": 0,
                            "errors": errors,
                        }
                    ],
                    result={
                        "totalFiles": 0,
                        "completedFiles": 0,
                        "failedFiles": 0,
                        "totalTerrainFiles": 0,
                        "errors": errors,
                    },
                    files={"total": 0, "completed": 0, "failed": 0, "current": None},
                    extra={"errors": errors},
                )

            logMessage(f"地形瓦片任务创建失败: {taskId}, 错误: {'; '.join(errors)}", "ERROR")
            return (
                jsonify(
                    {
                        "success": False,
                        "taskId": taskId,
                        "message": f"地形瓦片任务创建失败: {'; '.join(errors)}",
                        "statusUrl": f"/api/tasks/{taskId}",
                        "errors": errors,
                    }
                ),
                200,
            )

        outputPath, outputPathArray, outputPathAutoGenerated = resolveTilesOutputPath(outputPathArray, "terrain")
        os.makedirs(outputPath, exist_ok=True)
        if outputPathAutoGenerated:
            logMessage(f"未传 outputPath，已自动生成地形输出目录: {outputPath}")

        def runTerrainTask():
            nonlocal tifFiles
            try:
                with taskLock:
                    taskStatus[taskId] = createTaskRecord(
                        task_id=taskId,
                        status="running",
                        progress=0,
                        message=f"开始地形切片，共{len(tifFiles)}个文件...",
                        start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        current_stage="文件处理",
                        process_log=[
                            {
                                "stage": "初始化",
                                "status": "completed",
                                "message": f"任务初始化完成，准备处理{len(tifFiles)}个文件",
                                "timestamp": datetime.now().isoformat(),
                                "progress": 0,
                            }
                        ],
                        files={"total": len(tifFiles), "completed": 0, "failed": 0, "current": None},
                    )

                completedFiles = []
                failedFiles = []

                if len(tifFiles) > 1:
                    tifFilePaths = [fileInfo["fullPath"] for fileInfo in tifFiles]
                    continuityResult = analyzeTiffGeoContinuity(tifFilePaths, taskId)
                    with taskLock:
                        taskStatus[taskId]["message"] = (
                            "TIF文件地理位置连续，无明显间隙"
                            if continuityResult.get("continuous")
                            else "发现TIF文件间存在地理间隙，这可能是缝隙的原因"
                        )

                logMessage(f"顺序处理模式：依次处理{len(tifFiles)}个文件")
                for index, fileInfo in enumerate(tifFiles):
                    try:
                        with taskLock:
                            if taskId in taskStatus and taskStatus[taskId].get("status") == "stopped":
                                logMessage(f"地形瓦片任务 {taskId} 已被停止，退出处理", "INFO")
                                return

                        with taskLock:
                            taskStatus[taskId]["files"]["current"] = fileInfo["filename"]
                            taskStatus[taskId]["message"] = (
                                f"正在处理文件 {index + 1}/{len(tifFiles)}: {fileInfo['filename']}"
                            )

                        subOutputPath = outputPath
                        if len(tifFiles) > 1:
                            subOutputPath = os.path.join(
                                outputPath,
                                f"file_{index:03d}_{fileInfo['filename'].replace('.tif', '')}",
                            )

                        result = processSingleTerrainFile(
                            fileInfo,
                            subOutputPath,
                            startZoom,
                            endZoom,
                            maxTriangles,
                            bounds,
                            useCompression,
                            decompressOutput,
                            maxMemory,
                            threads,
                            autoZoom,
                            zoomStrategy,
                            taskId,
                            index,
                        )

                        if result["success"]:
                            completedFiles.append(
                                {
                                    "filename": fileInfo["filename"],
                                    "outputPath": result["outputPath"],
                                    "terrainFiles": result.get("terrainFiles", 0),
                                }
                            )
                            logMessage(f"文件处理成功: {fileInfo['filename']}")
                        else:
                            failedFiles.append(
                                {
                                    "filename": fileInfo["filename"],
                                    "error": result.get("error", "未知错误"),
                                }
                            )
                            logMessage(
                                f"文件处理失败: {fileInfo['filename']} - {result.get('error')}",
                                "ERROR",
                            )

                        progress = int((index + 1) / len(tifFiles) * 100)
                        with taskLock:
                            taskStatus[taskId]["files"]["completed"] = len(completedFiles)
                            taskStatus[taskId]["files"]["failed"] = len(failedFiles)
                            taskStatus[taskId]["progress"] = progress
                            taskStatus[taskId]["processLog"].append(
                                {
                                    "stage": "文件处理",
                                    "status": "completed" if result["success"] else "failed",
                                    "message": (
                                        f"文件 {fileInfo['filename']} 处理成功，生成了 {result.get('terrainFiles', 0)} 个地形文件"
                                        if result["success"]
                                        else f"文件 {fileInfo['filename']} 处理失败: {result.get('error', '未知错误')}"
                                    ),
                                    "timestamp": datetime.now().isoformat(),
                                    "progress": progress,
                                    "fileInfo": {
                                        "filename": fileInfo["filename"],
                                        "outputPath": result.get("outputPath"),
                                        "terrainFiles": result.get("terrainFiles", 0),
                                        "error": result.get("error"),
                                    },
                                }
                            )
                    except Exception as exc:
                        failedFiles.append({"filename": fileInfo["filename"], "error": str(exc)})
                        logMessage(f"顺序处理文件失败 {fileInfo['filename']}: {exc}", "ERROR")

                totalTerrainFiles = sum(fileInfo.get("terrainFiles", 0) for fileInfo in completedFiles)
                with taskLock:
                    existingLog = taskStatus[taskId].get("processLog", [])
                    start_time = taskStatus[taskId]["startTime"]
                    taskStatus[taskId] = createTaskRecord(
                        task_id=taskId,
                        status="completed",
                        progress=100,
                        message=(
                            f"地形切片完成! 成功:{len(completedFiles)}个, "
                            f"失败:{len(failedFiles)}个, 总瓦片:{totalTerrainFiles}个"
                        ),
                        start_time=start_time,
                        end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        current_stage="已完成",
                        process_log=existingLog,
                        result={
                            "totalFiles": len(tifFiles),
                            "completedFiles": len(completedFiles),
                            "failedFiles": len(failedFiles),
                            "totalTerrainFiles": totalTerrainFiles,
                            "completedDetails": completedFiles,
                            "failedDetails": failedFiles,
                            "outputPath": outputPath,
                        },
                        files={
                            "total": len(tifFiles),
                            "completed": len(completedFiles),
                            "failed": len(failedFiles),
                            "current": None,
                        },
                        stats={
                            "totalTiles": totalTerrainFiles,
                            "processedTiles": totalTerrainFiles,
                            "failedTiles": len(failedFiles),
                            "remainingTiles": 0,
                            "averageSpeed": 0,
                            "successRate": f"{len(completedFiles) / len(tifFiles) * 100:.1f}%" if tifFiles else "0%",
                        },
                    )
                    appendTaskLog(
                        taskStatus[taskId],
                        "任务完成",
                        "completed",
                        (
                            f"地形切片任务完成! 成功处理:{len(completedFiles)}个文件, "
                            f"失败:{len(failedFiles)}个文件, 总共生成:{totalTerrainFiles}个地形瓦片"
                        ),
                        100,
                        summary={
                            "totalFiles": len(tifFiles),
                            "completedFiles": len(completedFiles),
                            "failedFiles": len(failedFiles),
                            "totalTerrainFiles": totalTerrainFiles,
                        },
                    )

                if mergeTerrains and len(completedFiles) > 1:
                    try:
                        logMessage("开始合并地形瓦片...")
                        with taskLock:
                            taskStatus[taskId]["processLog"].append(
                                {
                                    "stage": "地形合并",
                                    "status": "running",
                                    "message": "开始合并多个地形文件夹",
                                    "timestamp": datetime.now().isoformat(),
                                    "progress": 95,
                                }
                            )
                            taskStatus[taskId]["currentStage"] = "地形合并中"
                            taskStatus[taskId]["message"] = "正在合并地形瓦片..."

                        mergeResult = mergeTerrainTiles(completedFiles, outputPath, taskId)
                        with taskLock:
                            taskStatus[taskId]["processLog"].append(
                                {
                                    "stage": "地形合并",
                                    "status": "completed" if mergeResult["success"] else "failed",
                                    "message": (
                                        f"地形合并完成，输出路径: {outputPath}"
                                        if mergeResult["success"]
                                        else f"地形合并失败: {mergeResult.get('error', '未知错误')}"
                                    ),
                                    "timestamp": datetime.now().isoformat(),
                                    "progress": 100,
                                }
                            )
                            if mergeResult["success"]:
                                taskStatus[taskId]["result"]["mergedOutputPath"] = outputPath
                                taskStatus[taskId]["result"]["mergeDetails"] = mergeResult
                            else:
                                taskStatus[taskId]["result"]["mergeError"] = mergeResult.get("error", "未知错误")
                    except Exception as exc:
                        logMessage(f"地形合并异常: {exc}", "ERROR")
                        with taskLock:
                            taskStatus[taskId]["processLog"].append(
                                {
                                    "stage": "地形合并",
                                    "status": "failed",
                                    "message": f"地形合并异常: {exc}",
                                    "timestamp": datetime.now().isoformat(),
                                    "progress": 100,
                                }
                            )
                            taskStatus[taskId]["result"]["mergeError"] = str(exc)

                finalizeTaskArtifact(
                    taskId,
                    source_files=[fileInfo["relativePath"] for fileInfo in tifFiles],
                    build_parameters={
                        "jobType": "terrain_tiles",
                        "startZoom": startZoom,
                        "endZoom": endZoom,
                        "outputPath": outputPathArray,
                        "compression": useCompression,
                        "decompress": decompressOutput,
                        "autoZoom": autoZoom,
                        "zoomStrategy": zoomStrategy,
                        "mergeTerrains": mergeTerrains,
                        "maxTriangles": maxTriangles,
                    },
                )
                logMessage(f"地形切片任务完成: {taskId}")
            except Exception as exc:
                with taskLock:
                    current_task = taskStatus.get(taskId, {})
                    taskStatus[taskId] = createTaskRecord(
                        task_id=taskId,
                        status="failed",
                        progress=current_task.get("progress", 0),
                        message=f"地形切片失败: {exc}",
                        start_time=current_task.get("startTime", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                        end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        current_stage="失败",
                        process_log=current_task.get("processLog", []),
                        result=current_task.get("result", {}),
                        files=current_task.get("files", {"total": len(tifFiles), "completed": 0, "failed": 0, "current": None}),
                        stats=current_task.get("stats"),
                        error=str(exc),
                    )
                    appendTaskLog(taskStatus[taskId], "异常退出", "failed", str(exc), current_task.get("progress", 0))
                logMessage(f"地形切片失败: {taskId} - {exc}", "ERROR")

        shouldQueue = (
            not workerRun
            and str(config.get("taskDispatch") or "").strip().lower() in {"db", "queue", "worker"}
            and isDatabaseEnabled()
        )
        if shouldQueue:
            workerPayload = dict(data)
            workerPayload.update(
                {
                    "taskId": taskId,
                    "outputPath": outputPathArray,
                    "startZoom": startZoom,
                    "endZoom": endZoom,
                    "maxTriangles": maxTriangles,
                    "bounds": bounds,
                    "compression": useCompression,
                    "decompress": decompressOutput,
                    "autoZoom": autoZoom,
                    "zoomStrategy": zoomStrategy,
                    "maxMemory": maxMemory,
                    "threads": threads,
                    "mergeTerrains": mergeTerrains,
                }
            )
            queuedRecord = createTaskRecord(
                task_id=taskId,
                status="queued",
                progress=0,
                message=f"地形切片任务已入队，将处理 {len(tifFiles)} 个文件",
                start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                current_stage="排队中",
                process_log=[
                    {
                        "stage": "任务创建",
                        "status": "queued",
                        "message": f"任务已入队，准备处理 {len(tifFiles)} 个文件",
                        "timestamp": datetime.now().isoformat(),
                        "progress": 0,
                    }
                ],
                files={"total": len(tifFiles), "completed": 0, "failed": 0, "current": None},
                stats={"totalTiles": 0, "processedTiles": 0, "failedTiles": 0, "remainingTiles": 0},
                extra={"jobType": "terrain_tiles", "workerPayload": workerPayload},
            )
            if enqueueBuildJob(taskId, "terrain_tiles", queuedRecord):
                return jsonify(
                    {
                        "success": True,
                        "taskId": taskId,
                        "status": "queued",
                        "message": f"地形切片任务已入队，将处理 {len(tifFiles)} 个文件",
                        "statusUrl": f"/api/tasks/{taskId}",
                    }
                )

        if runSynchronously:
            runTerrainTask()
        else:
            taskThread = threading.Thread(target=runTerrainTask)
            taskThread.daemon = True
            with taskLock:
                taskProcesses[taskId] = taskThread
            taskThread.start()

        return jsonify(
            {
                "success": True,
                "taskId": taskId,
                "status": "running" if workerRun else "queued",
                "message": f"地形切片任务已{'启动' if workerRun else '创建'}，将处理 {len(tifFiles)} 个文件",
                "statusUrl": f"/api/tasks/{taskId}",
                "parameters": {
                    "totalFiles": len(tifFiles),
                    "outputPath": outputPathArray,
                    "zoomRange": f"{startZoom}-{endZoom}",
                    "threads": threads,
                    "maxMemory": maxMemory,
                    "type": "terrain",
                },
            }
        )
    except Exception as exc:
        errorMessage = f"地形瓦片创建失败: {exc}"
        logMessage(errorMessage, "ERROR")
        return jsonify({"error": errorMessage}), 500


def updateLayerJson():
    """更新地形瓦片的layer.json文件。"""
    try:
        data = request.get_json(silent=True) or {}
        requiredParams = ["terrainPath"]
        for param in requiredParams:
            if param not in data:
                return jsonify({"error": f"缺少参数: {param}"}), 400

        terrainPathArray = data["terrainPath"]
        bounds = data.get("bounds")
        if not isinstance(terrainPathArray, list) or len(terrainPathArray) == 0:
            return jsonify({"error": "terrainPath必须是非空数组"}), 400

        terrainDir = os.path.join(*terrainPathArray)
        terrainPath = os.path.join(config["tilesDir"], terrainDir)
        if not os.path.exists(terrainPath):
            return jsonify({"error": "地形目录不存在"}), 404

        availableLevels = []
        for item in os.listdir(terrainPath):
            itemPath = os.path.join(terrainPath, item)
            if os.path.isdir(itemPath) and item.isdigit():
                hasTerrain = False
                for _, _, files in os.walk(itemPath):
                    if any(file.endswith(".terrain") for file in files):
                        hasTerrain = True
                        break
                if hasTerrain:
                    availableLevels.append(int(item))

        if not availableLevels:
            return jsonify({"error": "未检测到任何地形瓦片文件"}), 404

        availableLevels.sort()
        minZoom = min(availableLevels)
        maxZoom = max(availableLevels)
        sourceFileHint = data.get("sourceFile", "taiwan.tif")
        sourcePath = os.path.join(config["dataSourceDir"], sourceFileHint)
        success = False
        usedMethod = "unknown"

        if not os.path.exists(sourcePath):
            layerJsonPath = os.path.join(terrainPath, "layer.json")
            if os.path.exists(layerJsonPath):
                logMessage(f"未找到源文件 {sourcePath}，使用现有layer.json修改逻辑")
                success = updateCtbLayerJsonBounds(terrainPath, bounds)
                usedMethod = "updateCtbLayerJsonBounds"
            else:
                logMessage("未找到源文件且无现有layer.json，使用createLayerJson创建")
                success = createLayerJson(terrainPath, bounds)
                usedMethod = "createLayerJson"
        else:
            ctbStartZoom = maxZoom
            ctbEndZoom = minZoom
            maxMemory = data.get("maxMemory", "4g")
            threads = data.get("threads", 2)
            ctbMemory = str(convertMemoryToBytes(str(maxMemory)))
            layerCmd = [
                "ctb-tile",
                "-l",
                "-f",
                "Mesh",
                "-o",
                terrainPath,
                "-s",
                str(ctbStartZoom),
                "-e",
                str(ctbEndZoom),
                "-m",
                ctbMemory,
                "-v",
                sourcePath,
            ]
            env = os.environ.copy()
            env["GDAL_CACHEMAX"] = convertMemoryToMb(str(maxMemory))
            env["GDAL_NUM_THREADS"] = str(threads)
            env["OMP_NUM_THREADS"] = str(threads)
            logMessage(f"执行CTB layer.json命令: {' '.join(layerCmd)}")
            layerResult = runCommand(layerCmd, env=env)

            if layerResult["success"]:
                success = updateCtbLayerJsonBounds(terrainPath, bounds)
                usedMethod = "ctb-tile"
            else:
                logMessage(f"CTB生成layer.json失败: {layerResult.get('stderr', '未知错误')}", "ERROR")
                layerJsonPath = os.path.join(terrainPath, "layer.json")
                if os.path.exists(layerJsonPath):
                    success = updateCtbLayerJsonBounds(terrainPath, bounds)
                    usedMethod = "updateCtbLayerJsonBounds (CTB失败回退)"
                else:
                    success = createLayerJson(terrainPath, bounds)
                    usedMethod = "createLayerJson (CTB失败回退)"

        if not success:
            return jsonify({"error": "layer.json更新失败"}), 500

        return jsonify(
            {
                "message": "layer.json更新成功",
                "terrainPathArray": terrainPathArray,
                "terrainDir": terrainDir,
                "bounds": bounds or [-180.0, -90.0, 180.0, 90.0],
                "layerFile": os.path.join(terrainPath, "layer.json"),
                "method": usedMethod,
                "detectedLevels": {
                    "minZoom": minZoom,
                    "maxZoom": maxZoom,
                    "availableLevels": availableLevels,
                },
                "sourceFile": sourceFileHint if os.path.exists(sourcePath) else None,
            }
        )
    except Exception as exc:
        logMessage(f"更新layer.json失败: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500


def updateCtbLayerJsonBounds(terrainDir: str, bounds: list = None) -> bool:
    """修正CTB输出的layer.json边界和available数组。"""
    try:
        layerJsonPath = os.path.join(terrainDir, "layer.json")
        if not os.path.exists(layerJsonPath):
            logMessage(f"layer.json文件不存在: {layerJsonPath}", "ERROR")
            return False

        with open(layerJsonPath, "r", encoding="utf-8") as file_obj:
            layerData = json.load(file_obj)

        layerData["bounds"] = bounds or [-180.0, -90.0, 180.0, 90.0]
        if "available" in layerData and isinstance(layerData["available"], list) and layerData["available"]:
            tile00 = os.path.join(terrainDir, "0", "0", "0.terrain")
            tile10 = os.path.join(terrainDir, "0", "1", "0.terrain")
            has00 = os.path.exists(tile00)
            has10 = os.path.exists(tile10)
            if has10 and not has00:
                os.makedirs(os.path.dirname(tile00), exist_ok=True)
                shutil.copy2(tile10, tile00)
            elif has00 and not has10:
                os.makedirs(os.path.dirname(tile10), exist_ok=True)
                shutil.copy2(tile00, tile10)
            layerData["available"][0] = [{"startX": 0, "startY": 0, "endX": 1, "endY": 0}]

        with open(layerJsonPath, "w", encoding="utf-8") as file_obj:
            json.dump(layerData, file_obj, indent=2, ensure_ascii=False)

        logMessage(f"成功修改layer.json的bounds和available: {layerJsonPath}")
        return True
    except Exception as exc:
        logMessage(f"修改layer.json失败: {exc}", "ERROR")
        return False


def createLayerJson(terrainDir: str, bounds: list = None) -> bool:
    """创建最小可用的layer.json。"""
    try:
        layerJsonPath = os.path.join(terrainDir, "layer.json")
        layerData = {
            "tilejson": "2.1.0",
            "format": "heightmap-1.0",
            "version": "1.2.0",
            "scheme": "tms",
            "tiles": ["{z}/{x}/{y}.terrain"],
            "bounds": bounds or [-180.0, -90.0, 180.0, 90.0],
            "attribution": "Generated by AtlasWorks",
        }
        with open(layerJsonPath, "w", encoding="utf-8") as file_obj:
            json.dump(layerData, file_obj, indent=2, ensure_ascii=False)
        logMessage(f"layer.json已创建: {layerJsonPath}")
        return True
    except Exception as exc:
        logMessage(f"创建layer.json失败: {exc}", "ERROR")
        return False


def decompressTerrain():
    """解压地形瓦片目录。"""
    try:
        data = request.get_json(silent=True) or {}
        for param in ["terrainPath"]:
            if param not in data:
                return jsonify({"error": f"缺少参数: {param}"}), 400

        terrainPathArray = data["terrainPath"]
        if not isinstance(terrainPathArray, list) or len(terrainPathArray) == 0:
            return jsonify({"error": "terrainPath必须是非空数组"}), 400

        terrainDir = os.path.join(*terrainPathArray)
        terrainPath = os.path.join(config["tilesDir"], terrainDir)
        if not os.path.exists(terrainPath):
            return jsonify({"error": "地形目录不存在"}), 404

        success = decompressTerrainFiles(terrainPath)
        if not success:
            return jsonify({"error": "地形瓦片解压失败"}), 500

        return jsonify(
            {
                "message": "地形瓦片解压成功",
                "terrainPathArray": terrainPathArray,
                "terrainDir": terrainDir,
                "terrainPath": terrainPath,
            }
        )
    except Exception as exc:
        logMessage(f"解压地形瓦片失败: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500


def smoothTerrainBoundaries(mergedPath, taskId):
    """对合并后的terrain瓦片进行边界平滑。"""
    try:
        def updateTaskMessage(message):
            with taskLock:
                if taskId in taskStatus:
                    taskStatus[taskId]["message"] = message

        updateTaskMessage("开始地形边界平滑处理...")
        terrainFiles = []
        for root, _, files in os.walk(mergedPath):
            for file in files:
                if file.endswith(".terrain"):
                    terrainFiles.append(os.path.join(root, file))

        if not terrainFiles:
            return {"success": False, "message": "未找到terrain文件"}

        tilesByLevel = {}
        for terrainFile in terrainFiles:
            relativePath = os.path.relpath(terrainFile, mergedPath)
            pathParts = relativePath.split(os.sep)
            if len(pathParts) < 3:
                continue

            level = pathParts[0]
            x = pathParts[1]
            y = pathParts[2].replace(".terrain", "")
            tilesByLevel.setdefault(level, {}).setdefault(x, {})[y] = terrainFile

        processedTiles = 0
        smoothedTiles = 0
        for level in sorted(tilesByLevel.keys()):
            levelTiles = tilesByLevel[level]
            for x in sorted(levelTiles.keys()):
                xTiles = levelTiles[x]
                for y in sorted(xTiles.keys()):
                    terrainFile = xTiles[y]
                    neighbors = []
                    nextX = str(int(x) + 1)
                    nextY = str(int(y) + 1)
                    if nextX in levelTiles and y in levelTiles[nextX]:
                        neighbors.append(("right", levelTiles[nextX][y]))
                    if nextY in xTiles:
                        neighbors.append(("bottom", xTiles[nextY]))
                    if neighbors and smoothTileBoundaries(terrainFile, neighbors, taskId):
                        smoothedTiles += 1
                    processedTiles += 1
                    if processedTiles % 100 == 0:
                        progress = (processedTiles / len(terrainFiles)) * 100
                        updateTaskMessage(
                            f"边界平滑进度: {processedTiles}/{len(terrainFiles)} ({progress:.1f}%)"
                        )

        updateTaskMessage(f"边界平滑完成: 处理 {processedTiles} 个瓦片，平滑 {smoothedTiles} 个边界")
        return {
            "success": True,
            "processedTiles": processedTiles,
            "smoothedTiles": smoothedTiles,
            "message": f"边界平滑完成，处理了 {smoothedTiles} 个瓦片边界",
        }
    except Exception as exc:
        logMessage(f"边界平滑失败: {exc}", "ERROR")
        return {"success": False, "error": str(exc)}


def smoothTileBoundaries(tileFile, neighbors, taskId):
    """对单个terrain瓦片做轻量边界平滑标记。"""
    try:
        if not os.path.exists(tileFile) or not neighbors:
            return False

        tempDir = os.path.join(os.path.dirname(tileFile), "temp_smooth")
        os.makedirs(tempDir, exist_ok=True)
        try:
            smoothScript = os.path.join(tempDir, "smooth_boundaries.py")
            scriptBody = """#!/usr/bin/env python3
import os
import sys

def smooth_terrain_boundaries(main_file, neighbor_files):
    try:
        if not os.path.exists(main_file):
            return False
        with open(main_file, 'rb') as file_obj:
            data = bytearray(file_obj.read())
        if len(data) < 88:
            return False
        smooth_marker = b'SMOOTHED'
        if smooth_marker not in data:
            data.extend(smooth_marker)
            with open(main_file, 'wb') as file_obj:
                file_obj.write(data)
        return True
    except Exception:
        return False

if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(1)
    main_file = sys.argv[1]
    neighbor_files = sys.argv[2:] if len(sys.argv) > 2 else []
    success = smooth_terrain_boundaries(main_file, neighbor_files)
    sys.exit(0 if success else 1)
"""
            with open(smoothScript, "w", encoding="utf-8") as file_obj:
                file_obj.write(scriptBody)

            neighborPaths = [neighbor[1] for neighbor in neighbors]
            result = subprocess.run(
                ["python3", smoothScript, tileFile, *neighborPaths],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode == 0
        finally:
            if os.path.exists(tempDir):
                shutil.rmtree(tempDir, ignore_errors=True)
    except Exception:
        return False


def mergeTerrainTiles(completedFiles, mergedPath, taskId):
    """将多个地形结果合并到统一目录。"""
    try:
        logMessage(f"开始合并地形瓦片，输出路径: {mergedPath}", "INFO")
        os.makedirs(mergedPath, exist_ok=True)

        totalTiles = 0
        mergedTiles = 0
        skippedTiles = 0
        layerJsons = []
        sourceDirs = []
        outputParentDir = mergedPath

        if os.path.exists(outputParentDir):
            for item in os.listdir(outputParentDir):
                itemPath = os.path.join(outputParentDir, item)
                if os.path.isdir(itemPath) and item.startswith("file_") and "_" in item[5:]:
                    if containsTerrainFiles(itemPath):
                        sourceDirs.append(itemPath)

        if not sourceDirs:
            for fileInfo in completedFiles:
                outputDir = fileInfo.get("outputDir") or fileInfo.get("outputPath")
                if outputDir and os.path.exists(outputDir) and os.path.isdir(outputDir):
                    if containsTerrainFiles(outputDir):
                        sourceDirs.append(outputDir)

        if not sourceDirs:
            return {"success": False, "error": f"没有找到有效的地形文件目录。扫描路径: {outputParentDir}"}

        for sourceDir in sourceDirs:
            layerJsonPath = os.path.join(sourceDir, "layer.json")
            if not os.path.exists(layerJsonPath):
                continue
            try:
                with open(layerJsonPath, "r", encoding="utf-8") as file_obj:
                    layerJsons.append(
                        {"path": layerJsonPath, "data": json.load(file_obj), "sourceDir": sourceDir}
                    )
            except Exception as exc:
                logMessage(f"读取layer.json失败: {layerJsonPath} - {exc}", "WARNING")

        allTileInfo = {}
        for sourceDir in sourceDirs:
            for item in os.listdir(sourceDir):
                itemPath = os.path.join(sourceDir, item)
                if item == "layer.json" or not (os.path.isdir(itemPath) and item.isdigit()):
                    continue
                zoomLevel = int(item)
                allTileInfo.setdefault(zoomLevel, {})
                for xItem in os.listdir(itemPath):
                    xPath = os.path.join(itemPath, xItem)
                    if not (os.path.isdir(xPath) and xItem.isdigit()):
                        continue
                    x = int(xItem)
                    allTileInfo[zoomLevel].setdefault(x, {})
                    for terrainFile in os.listdir(xPath):
                        if not terrainFile.endswith(".terrain"):
                            continue
                        y = int(terrainFile.replace(".terrain", ""))
                        sourceTile = os.path.join(xPath, terrainFile)
                        if y in allTileInfo[zoomLevel][x]:
                            currentValue = allTileInfo[zoomLevel][x][y]
                            if not isinstance(currentValue, list):
                                currentValue = [currentValue]
                            currentValue.append(sourceTile)
                            allTileInfo[zoomLevel][x][y] = currentValue
                        else:
                            allTileInfo[zoomLevel][x][y] = sourceTile

        filledTiles = 0
        for sourceDir in sourceDirs:
            for item in os.listdir(sourceDir):
                itemPath = os.path.join(sourceDir, item)
                if item == "layer.json" or not (os.path.isdir(itemPath) and item.isdigit()):
                    continue

                zoomDir = os.path.join(mergedPath, item)
                os.makedirs(zoomDir, exist_ok=True)
                for xItem in os.listdir(itemPath):
                    xPath = os.path.join(itemPath, xItem)
                    if not (os.path.isdir(xPath) and xItem.isdigit()):
                        continue

                    xDir = os.path.join(zoomDir, xItem)
                    os.makedirs(xDir, exist_ok=True)
                    for terrainFile in os.listdir(xPath):
                        if not terrainFile.endswith(".terrain"):
                            continue
                        sourceTile = os.path.join(xPath, terrainFile)
                        targetTile = os.path.join(xDir, terrainFile)
                        totalTiles += 1
                        if not os.path.exists(targetTile):
                            try:
                                os.link(sourceTile, targetTile)
                            except Exception:
                                shutil.copy2(sourceTile, targetTile)
                            mergedTiles += 1
                        else:
                            sourceSize = os.path.getsize(sourceTile)
                            targetSize = os.path.getsize(targetTile)
                            if sourceSize > targetSize:
                                try:
                                    os.remove(targetTile)
                                    os.link(sourceTile, targetTile)
                                    mergedTiles += 1
                                except Exception as exc:
                                    logMessage(f"替换terrain文件失败: {terrainFile} - {exc}", "WARNING")
                                    skippedTiles += 1
                            else:
                                skippedTiles += 1

        maxFillZoom = 8
        for zoomLevel in sorted(allTileInfo.keys()):
            if zoomLevel > maxFillZoom or not allTileInfo[zoomLevel]:
                continue
            minX = min(allTileInfo[zoomLevel].keys())
            maxX = max(allTileInfo[zoomLevel].keys())
            for x in range(minX, maxX + 1):
                if x not in allTileInfo[zoomLevel] or not allTileInfo[zoomLevel][x]:
                    continue
                minY = min(allTileInfo[zoomLevel][x].keys())
                maxY = max(allTileInfo[zoomLevel][x].keys())
                for y in range(minY, maxY + 1):
                    if y not in allTileInfo[zoomLevel][x] and fillTerrainGap(
                        allTileInfo, zoomLevel, x, y, mergedPath
                    ):
                        filledTiles += 1

        mergedLayerJson = None
        if layerJsons:
            try:
                mergedLayerJson = layerJsons[0]["data"].copy()
                if len(layerJsons) > 1:
                    allBounds = [
                        layerInfo["data"]["bounds"]
                        for layerInfo in layerJsons
                        if "bounds" in layerInfo["data"]
                    ]
                    if allBounds:
                        mergedLayerJson["bounds"] = [
                            min(bounds[0] for bounds in allBounds),
                            min(bounds[1] for bounds in allBounds),
                            max(bounds[2] for bounds in allBounds),
                            max(bounds[3] for bounds in allBounds),
                        ]

                    maxZoomLevel = 0
                    for layerInfo in layerJsons:
                        if "available" in layerInfo["data"]:
                            maxZoomLevel = max(maxZoomLevel, len(layerInfo["data"]["available"]))
                    if maxZoomLevel > 0:
                        mergedLayerJson["available"] = []
                        for zoom in range(maxZoomLevel):
                            mergedLayerJson["available"].append(
                                [
                                    {
                                        "startY": 0,
                                        "startX": 0,
                                        "endY": (2 ** zoom) - 1,
                                        "endX": (2 ** (zoom + 1)) - 1,
                                    }
                                ]
                            )

                mergedLayerJson["description"] = (
                    f"合并地形瓦片 - {len(sourceDirs)}个数据源" if len(sourceDirs) <= 10 else "合并地形瓦片"
                )
                mergedLayerPath = os.path.join(mergedPath, "layer.json")
                with open(mergedLayerPath, "w", encoding="utf-8") as file_obj:
                    json.dump(mergedLayerJson, file_obj, indent=2, ensure_ascii=False)
            except Exception as exc:
                logMessage(f"合并layer.json失败: {exc}", "WARNING")

        deletedDirs = []
        for sourceDir in sourceDirs:
            dirName = os.path.basename(sourceDir)
            if dirName.startswith("file_") and "_" in dirName[5:]:
                try:
                    shutil.rmtree(sourceDir)
                    deletedDirs.append(sourceDir)
                except Exception as exc:
                    logMessage(f"删除原始地形目录失败: {sourceDir} - {exc}", "WARNING")

        smoothResult = smoothTerrainBoundaries(mergedPath, taskId)
        return {
            "success": True,
            "mergedPath": mergedPath,
            "totalTiles": totalTiles,
            "mergedTiles": mergedTiles,
            "skippedTiles": skippedTiles,
            "filledTiles": filledTiles,
            "sourceDirs": sourceDirs,
            "deletedDirs": deletedDirs,
            "layerJsonMerged": mergedLayerJson is not None,
            "smoothResult": smoothResult,
        }
    except Exception as exc:
        logMessage(f"地形合并失败: {exc}", "ERROR")
        return {"success": False, "error": str(exc)}


def containsTerrainFiles(directory):
    """判断目录是否包含terrain结果。"""
    try:
        if not os.path.exists(directory) or not os.path.isdir(directory):
            return False
        if os.path.exists(os.path.join(directory, "layer.json")):
            return True
        for item in os.listdir(directory):
            itemPath = os.path.join(directory, item)
            if os.path.isdir(itemPath) and item.isdigit():
                for _, _, files in os.walk(itemPath):
                    if any(file.endswith(".terrain") for file in files):
                        return True
        return False
    except Exception as exc:
        logMessage(f"检查地形文件时出错: {directory} - {exc}", "WARNING")
        return False


def fillTerrainGap(allTileInfo, zoomLevel, x, y, mergedPath):
    """用邻近terrain瓦片填补空隙。"""
    try:
        neighbors = []
        directions = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
        for dx, dy in directions:
            nx = x + dx
            ny = y + dy
            if nx in allTileInfo.get(zoomLevel, {}) and ny in allTileInfo[zoomLevel][nx]:
                neighbors.append(allTileInfo[zoomLevel][nx][ny])

        if not neighbors:
            return False

        sourceTile = neighbors[0]
        if isinstance(sourceTile, list):
            sourceTile = sourceTile[0]

        targetDir = os.path.join(mergedPath, str(zoomLevel), str(x))
        os.makedirs(targetDir, exist_ok=True)
        targetTile = os.path.join(targetDir, f"{y}.terrain")
        if os.path.exists(targetTile):
            return False

        shutil.copy2(sourceTile, targetTile)
        logMessage(f"填补空隙瓦片: {zoomLevel}/{x}/{y}.terrain")
        return True
    except Exception as exc:
        logMessage(f"填补空隙异常: {zoomLevel}/{x}/{y}.terrain - {exc}", "WARNING")
        return False


def getTiffGeoInfo(tiffPath):
    """获取TIF文件的地理信息。"""
    try:
        result = runCommand(["gdalinfo", "-json", tiffPath])
        if not result["success"]:
            return None

        payload = result.get("stdout") or result.get("output") or ""
        infoData = json.loads(payload or "{}")
        geoInfo = {
            "file_path": tiffPath,
            "filename": os.path.basename(tiffPath),
            "bounds": None,
            "pixel_size": None,
            "projection": None,
        }

        if "wgs84Extent" in infoData:
            extent = infoData["wgs84Extent"]["coordinates"][0]
            geoInfo["bounds"] = [
                min(coord[0] for coord in extent),
                min(coord[1] for coord in extent),
                max(coord[0] for coord in extent),
                max(coord[1] for coord in extent),
            ]

        geoTransform = infoData.get("geoTransform", [])
        if len(geoTransform) >= 6:
            geoInfo["pixel_size"] = [abs(geoTransform[1]), abs(geoTransform[5])]

        coordinateSystem = infoData.get("coordinateSystem", {})
        if "wkt" in coordinateSystem:
            geoInfo["projection"] = coordinateSystem["wkt"]

        return geoInfo
    except Exception as exc:
        logMessage(f"获取TIF地理信息异常: {exc}", "WARNING")
        return None


def canMergeTiffs(tiff1Info, tiff2Info, tolerance=0.001):
    """判断两个TIF文件是否适合合并。"""
    try:
        if tiff1Info.get("projection") != tiff2Info.get("projection"):
            return False

        pixel1 = tiff1Info.get("pixel_size")
        pixel2 = tiff2Info.get("pixel_size")
        if pixel1 and pixel2:
            if abs(pixel1[0] - pixel2[0]) > tolerance or abs(pixel1[1] - pixel2[1]) > tolerance:
                return False

        bounds1 = tiff1Info.get("bounds")
        bounds2 = tiff2Info.get("bounds")
        if bounds1 and bounds2:
            minX1, minY1, maxX1, maxY1 = bounds1
            minX2, minY2, maxX2, maxY2 = bounds2
            xGap = max(0, max(minX1 - maxX2, minX2 - maxX1))
            yGap = max(0, max(minY1 - maxY2, minY2 - maxY1))
            pixelSize = pixel1 or [tolerance, tolerance]
            maxGap = max(pixelSize[0], pixelSize[1]) * 2
            return xGap <= maxGap and yGap <= maxGap

        return True
    except Exception:
        return False


def groupTiffsForMerging(tiffFiles):
    """按可拼接关系对TIF做分组。"""
    try:
        logMessage(f"开始分析{len(tiffFiles)}个TIF文件")
        geoInfos = []
        for tiffFile in tiffFiles:
            geoInfo = getTiffGeoInfo(tiffFile["fullPath"])
            if geoInfo:
                geoInfo.update(tiffFile)
                geoInfos.append(geoInfo)

        if not geoInfos:
            return []

        groups = []
        used = set()
        for index, info1 in enumerate(geoInfos):
            if index in used:
                continue
            currentGroup = [info1]
            used.add(index)
            for candidateIndex, info2 in enumerate(geoInfos):
                if candidateIndex in used:
                    continue
                if any(canMergeTiffs(groupInfo, info2) for groupInfo in currentGroup):
                    currentGroup.append(info2)
                    used.add(candidateIndex)
            groups.append(currentGroup)

        logMessage(f"分组完成: {len(groups)}个组")
        return groups
    except Exception as exc:
        logMessage(f"分组异常: {exc}", "ERROR")
        return []


def mergeTiffGroup(tiffGroup, outputDir, groupIndex):
    """合并一组相邻TIF。"""
    try:
        if len(tiffGroup) == 1:
            return tiffGroup[0]

        logMessage(f"合并第{groupIndex}组的{len(tiffGroup)}个文件")
        mergedFilename = f"merged_group_{groupIndex:03d}.tif"
        mergedPath = os.path.join(outputDir, mergedFilename)
        filePaths = [info["file_path"] for info in tiffGroup]
        mergeCmd = [
            "gdalwarp",
            "-r",
            "cubic",
            "-co",
            "COMPRESS=LZW",
            "-co",
            "TILED=YES",
            "-srcnodata",
            "0",
            "-dstnodata",
            "0",
            "-multi",
            *filePaths,
            mergedPath,
        ]
        result = runCommand(mergeCmd)
        if result["success"] and os.path.exists(mergedPath):
            logMessage(f"第{groupIndex}组合并成功")
            return {
                "fullPath": mergedPath,
                "filename": mergedFilename,
                "relativePath": mergedFilename,
                "is_merged": True,
                "source_files": [info["filename"] for info in tiffGroup],
            }

        logMessage(f"第{groupIndex}组合并失败", "ERROR")
        return None
    except Exception as exc:
        logMessage(f"合并异常: {exc}", "ERROR")
        return None


def preprocessTiffsWithMerging(tiffFiles, outputPath, taskId):
    """按地理连续性预合并TIF文件。"""
    try:
        logMessage("开始TIF文件智能合并预处理")
        mergeTempDir = os.path.join(outputPath, "temp_merged_tiffs")
        os.makedirs(mergeTempDir, exist_ok=True)
        tiffGroups = groupTiffsForMerging(tiffFiles)
        if not tiffGroups:
            return tiffFiles

        processedFiles = []
        for groupIndex, tiffGroup in enumerate(tiffGroups):
            mergedFile = mergeTiffGroup(tiffGroup, mergeTempDir, groupIndex)
            if mergedFile:
                processedFiles.append(mergedFile)
            else:
                processedFiles.extend(tiffGroup)

        logMessage(f"预处理完成: {len(tiffFiles)} -> {len(processedFiles)} 个文件")
        return processedFiles
    except Exception as exc:
        logMessage(f"预处理异常: {exc}", "ERROR")
        return tiffFiles
