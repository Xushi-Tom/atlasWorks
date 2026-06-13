<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { ElMessageBox } from 'element-plus';

import ResizableDrawer from '../components/ResizableDrawer.vue';
import { api } from '../services/api';
import { formatDateTime } from '../utils/formatters';
import { pushToast } from '../composables/useToast';
import { setNavigationIntent } from '../utils/navigationIntent';

const emit = defineEmits(['navigate']);

const tasks = ref([]);
const statusFilter = ref('');
const dateRange = ref([]);
const currentPage = ref(1);
const pageSize = ref(20);
const totalTasks = ref(0);
const detailVisible = ref(false);
const detailLoading = ref(false);
const selectedTask = ref(null);
const taskEvents = ref([]);
const detailTab = ref('summary');
let loadTimer = null;

const statusLabelMap = {
    queued: '排队中',
    running: '运行中',
    completed: '已完成',
    failed: '失败',
    stopped: '已停止',
    unknown: '未知'
};

const statusTagTypeMap = {
    queued: 'info',
    running: 'warning',
    completed: 'success',
    failed: 'danger',
    stopped: 'info',
    unknown: 'info'
};

function normalizeTaskDate(value) {
    if (!value) return null;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
}

function compareTaskOrder(left, right) {
    const leftStatus = String(left?.status || '').toLowerCase();
    const rightStatus = String(right?.status || '').toLowerCase();
    const leftRunningRank = leftStatus === 'running' ? 0 : 1;
    const rightRunningRank = rightStatus === 'running' ? 0 : 1;
    if (leftRunningRank !== rightRunningRank) {
        return leftRunningRank - rightRunningRank;
    }

    const leftTime = normalizeTaskDate(left?.startTime)?.getTime() || 0;
    const rightTime = normalizeTaskDate(right?.startTime)?.getTime() || 0;
    if (leftTime !== rightTime) {
        return rightTime - leftTime;
    }

    return String(right?.taskId || '').localeCompare(String(left?.taskId || ''));
}

function getStatusLabel(status) {
    return statusLabelMap[String(status || 'unknown').toLowerCase()] || '未知';
}

function getStatusTagType(status) {
    return statusTagTypeMap[String(status || 'unknown').toLowerCase()] || 'info';
}

function inferTaskType(task) {
    const artifactType = String(task?.result?.artifactType || '').toLowerCase();
    const stage = String(task?.currentStage || '').toLowerCase();
    if (artifactType.includes('terrain') || stage.includes('terrain') || Number(task?.result?.totalTerrainFiles || 0) > 0) {
        return '地形切片';
    }
    if (artifactType.includes('vector') || String(task?.result?.method || '').includes('mvt') || task?.result?.totalTiles !== undefined) {
        return '二维矢量切片';
    }
    if (artifactType.includes('map') || artifactType.includes('imagery') || stage.includes('raster') || task?.result?.totalFiles !== undefined) {
        return '地图切片';
    }
    return '生产任务';
}

function formatProgress(progress) {
    const value = Number(progress || 0);
    if (!Number.isFinite(value)) return 0;
    return Math.max(0, Math.min(100, Math.round(value)));
}

function formatEventType(eventType) {
    const raw = String(eventType || '').trim();
    if (!raw) return '过程回传';
    return raw
        .split('.')
        .filter(Boolean)
        .map(item => item.replace(/[-_]/g, ' '))
        .join(' / ');
}

function getTaskMeta(task) {
    const result = task?.result || {};
    const parts = [inferTaskType(task)];
    if (result?.artifactId) {
        parts.push(`产物 ${result.artifactId}`);
    }
    return parts.join(' · ');
}

function getTaskStageDetail(task) {
    const files = task?.files || {};
    const stats = task?.stats || {};
    const message = String(task?.message || '').trim();
    if (message) {
        return message;
    }

    const totalFiles = Number(files?.total || 0);
    if (totalFiles > 0) {
        const completedFiles = Number(files?.completed || 0);
        const failedFiles = Number(files?.failed || 0);
        return failedFiles > 0
            ? `文件 ${completedFiles}/${totalFiles}，失败 ${failedFiles}`
            : `文件 ${completedFiles}/${totalFiles}`;
    }

    const totalTiles = Number(stats?.totalTiles || 0);
    if (totalTiles > 0) {
        const processedTiles = Number(stats?.processedTiles || 0);
        const failedTiles = Number(stats?.failedTiles || 0);
        return failedTiles > 0
            ? `瓦片 ${processedTiles}/${totalTiles}，失败 ${failedTiles}`
            : `瓦片 ${processedTiles}/${totalTiles}`;
    }

    return task?.result?.outputPath || task?.result?.mergedOutputPath || '暂无回传信息';
}

function getProgressClass(status) {
    const normalized = String(status || '').toLowerCase();
    if (normalized === 'completed') return 'task-progress-value-success';
    if (normalized === 'running') return 'task-progress-value-running';
    if (normalized === 'failed') return 'task-progress-value-danger';
    if (normalized === 'stopped') return 'task-progress-value-muted';
    return 'task-progress-value-default';
}

function getDetailStatusClass(status) {
    const normalized = String(status || '').toLowerCase();
    if (normalized === 'completed') return 'task-status-chip-success';
    if (normalized === 'running') return 'task-status-chip-running';
    if (normalized === 'failed') return 'task-status-chip-danger';
    if (normalized === 'stopped') return 'task-status-chip-muted';
    return 'task-status-chip-default';
}

function getTaskSummaryStats(task) {
    const result = task?.result || {};
    return [
        { label: '执行进度', value: `${formatProgress(task?.progress)}%` },
        { label: '当前阶段', value: task?.currentStage || '等待回传' },
        { label: '任务类型', value: inferTaskType(task) },
        { label: '产物 ID', value: result?.artifactId || '-' },
        { label: '输出目录', value: result?.outputPath || '-' },
        { label: '结束时间', value: formatDateTime(task?.endTime) },
        Number.isFinite(Number(result?.completedFiles)) ? { label: '成功文件', value: Number(result.completedFiles) } : null,
        Number.isFinite(Number(result?.failedFiles)) && Number(result.failedFiles) > 0 ? { label: '失败文件', value: Number(result.failedFiles) } : null
    ].filter(item => item && item.value !== '' && item.value !== null && item.value !== undefined && item.value !== '-');
}

const visibleTasks = computed(() => {
    const offset = (currentPage.value - 1) * pageSize.value;
    return tasks.value.map((task, index) => ({ ...task, orderNo: offset + index + 1 }));
});

async function load() {
    try {
        const taskResponse = await api.getAllTasks({
            page: currentPage.value,
            pageSize: pageSize.value,
            status: String(statusFilter.value || '').trim() || undefined,
            dateFrom: dateRange.value?.[0] || undefined,
            dateTo: dateRange.value?.[1] || undefined
        });
        const data = taskResponse?.data || {};
        tasks.value = Object.values(data.tasks || {}).sort(compareTaskOrder);
        totalTasks.value = Number(data.total || 0);
        currentPage.value = Number(data.page || currentPage.value);
        pageSize.value = Number(data.pageSize || pageSize.value);
    } catch (error) {
        pushToast(`任务列表加载失败: ${error.message}`, 'error', 4500);
    }
}

function applyFilters() {
    currentPage.value = 1;
    load();
}

function handlePageChange(page) {
    currentPage.value = page;
    load();
}

function handlePageSizeChange(size) {
    pageSize.value = size;
    currentPage.value = 1;
    load();
}

async function openDetail(task) {
    detailVisible.value = true;
    detailLoading.value = true;
    selectedTask.value = null;
    taskEvents.value = [];
    detailTab.value = 'summary';

    try {
        const [taskDetail, eventsResponse] = await Promise.all([
            api.getTaskStatus(task.taskId),
            api.getTaskEvents(task.taskId).catch(() => null)
        ]);
        selectedTask.value = taskDetail?.data || null;
        taskEvents.value = eventsResponse?.data?.events || [];
    } catch (error) {
        pushToast(`任务详情加载失败: ${error.message}`, 'error', 4500);
        detailVisible.value = false;
    } finally {
        detailLoading.value = false;
    }
}

async function stopTask(taskId) {
    try {
        await api.stopTask(taskId);
        pushToast('停止指令已发送', 'success');
        await load();
    } catch (error) {
        pushToast(`停止任务失败: ${error.message}`, 'error', 4500);
    }
}

async function removeTask(taskId) {
    try {
        await ElMessageBox.confirm('确认删除这个任务吗？删除后不可恢复。', '删除任务', {
            type: 'warning',
            confirmButtonText: '删除',
            cancelButtonText: '取消',
            confirmButtonClass: 'el-button--danger'
        });
        await api.deleteTask(taskId);
        pushToast('任务已删除', 'success');
        await load();
    } catch (error) {
        if (error === 'cancel' || error === 'close' || error?.message === 'cancel') return;
        pushToast(`删除任务失败: ${error.message}`, 'error', 4500);
    }
}

function openPublishFromTask(task) {
    const targetTask = task || selectedTask.value;
    const taskId = String(targetTask?.taskId || '').trim();
    if (!taskId) {
        pushToast('未找到任务标识', 'warning');
        return;
    }
    const result = targetTask?.result || {};
    const publishTypeHint = String(result?.publishHints?.publishType || '').trim();
    const normalizedPublishType = publishTypeHint === 'geo' ? 'vector' : publishTypeHint;
    setNavigationIntent({
        section: 'publish',
        sourceMode: 'task',
        taskId,
        alias: String(result?.outputPath || result?.mergedOutputPath || taskId).split('/').filter(Boolean).pop() || taskId,
        publishType: normalizedPublishType || undefined,
        publishMethod: result?.publishHints?.publishMethod || undefined
    });
    emit('navigate', {
        section: 'publish',
        sourceMode: 'task',
        taskId,
        alias: String(result?.outputPath || result?.mergedOutputPath || taskId).split('/').filter(Boolean).pop() || taskId,
        publishType: normalizedPublishType || undefined,
        publishMethod: result?.publishHints?.publishMethod || undefined
    });
}

onMounted(async () => {
    await load();
    loadTimer = window.setInterval(() => {
        load();
    }, 15000);
});

onBeforeUnmount(() => {
    if (loadTimer) {
        window.clearInterval(loadTimer);
        loadTimer = null;
    }
});
</script>

<template>
    <section class="app-view standard-page">
        <div class="page-banner">
            <div class="page-banner__meta">
                <div class="page-banner__title">任务列表</div>
                <div class="page-banner__desc">统一查看任务排队、执行阶段、结果路径与异常信息，便于生产调度和问题回溯。</div>
            </div>
            <div class="page-banner__actions">
                <el-button type="primary" @click="load">刷新</el-button>
            </div>
        </div>

        <div class="app-scroll">
            <div class="layui-panel">
                <div class="layui-toolbar" @keydown.capture.enter.prevent="applyFilters">
                    <el-form class="layui-filter-form" @submit.prevent="applyFilters">
                        <div class="layui-filter-item">
                            <span class="layui-filter-label">状态：</span>
                            <el-select v-model="statusFilter" clearable placeholder="全部状态" class="layui-filter-control layui-filter-status">
                                <el-option label="排队中" value="queued" />
                                <el-option label="运行中" value="running" />
                                <el-option label="已完成" value="completed" />
                                <el-option label="失败" value="failed" />
                                <el-option label="已停止" value="stopped" />
                            </el-select>
                        </div>
                        <div class="layui-filter-item">
                            <span class="layui-filter-label">时间：</span>
                            <el-date-picker
                                v-model="dateRange"
                                type="daterange"
                                range-separator="—"
                                start-placeholder="开始日期"
                                end-placeholder="结束日期"
                                value-format="YYYY-MM-DD"
                                class="layui-filter-control layui-filter-date"
                            />
                        </div>
                        <el-button type="primary" native-type="submit">搜索</el-button>
                    </el-form>
                </div>

                <div class="layui-table-wrap">
                <table class="layui-table">
                    <colgroup>
                        <col style="width: 60px" />
                        <col style="min-width: 280px" />
                        <col style="width: 90px" />
                        <col style="width: 88px" />
                        <col style="min-width: 260px" />
                        <col style="width: 168px" />
                        <col style="width: 168px" />
                        <col style="width: 236px" />
                    </colgroup>
                    <thead>
                        <tr>
                            <th>序号</th>
                            <th>任务信息</th>
                            <th>状态</th>
                            <th>进度</th>
                            <th>过程说明</th>
                            <th>开始时间</th>
                            <th>结束时间</th>
                            <th>操作</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="row in visibleTasks" :key="row.taskId">
                            <td class="cell-center">{{ row.orderNo }}</td>
                            <td>
                                <div class="task-info-cell">
                                    <div class="task-info-id">{{ row.taskId }}</div>
                                    <div class="task-info-meta">{{ getTaskMeta(row) }}</div>
                                </div>
                            </td>
                            <td class="cell-center">
                                <span :class="['layui-badge', `layui-badge-${getStatusTagType(row.status)}`]">
                                    {{ getStatusLabel(row.status) }}
                                </span>
                            </td>
                            <td class="cell-center">
                                <div :class="['task-progress-value', getProgressClass(row.status)]">
                                    {{ formatProgress(row.progress) }}%
                                </div>
                            </td>
                            <td>
                                <div class="task-stage-cell">
                                    <div class="task-stage-title">{{ row.currentStage || '等待回传' }}</div>
                                    <div class="task-stage-detail">{{ getTaskStageDetail(row) }}</div>
                                </div>
                            </td>
                            <td>{{ formatDateTime(row.startTime) }}</td>
                            <td>{{ formatDateTime(row.endTime) }}</td>
                            <td class="cell-center">
                                <div class="layui-table-actions">
                                    <a class="layui-link" @click="openDetail(row)">详情</a>
                                    <a v-if="row.status === 'completed'" class="layui-link" @click="openPublishFromTask(row)">去发布</a>
                                    <a v-if="row.status === 'running'" class="layui-link layui-link-warn" @click="stopTask(row.taskId)">停止</a>
                                    <a v-else class="layui-link layui-link-danger" @click="removeTask(row.taskId)">删除</a>
                                </div>
                            </td>
                        </tr>
                        <tr v-if="!visibleTasks.length">
                            <td colspan="8" class="cell-empty">暂无任务数据</td>
                        </tr>
                    </tbody>
                </table>
                </div>

                <div class="layui-table-footer">
                    <span class="layui-table-count">共 {{ totalTasks }} 条</span>
                    <el-pagination
                        :current-page="currentPage"
                        :page-size="pageSize"
                        :page-sizes="[10, 20, 50, 100]"
                        :total="totalTasks"
                        small
                        background
                        layout="sizes, prev, pager, next, jumper"
                        @current-change="handlePageChange"
                        @size-change="handlePageSizeChange"
                    />
                </div>
            </div>
        </div>

        <ResizableDrawer v-model="detailVisible" title="任务详情" :width="980" :min-width="620" :max-width="1360" destroy-on-close>
            <div v-if="detailLoading" class="dialog-loading-text">正在加载任务详情...</div>
            <template v-else-if="selectedTask">
                <div class="task-detail-shell">
                    <div class="task-detail-hero">
                        <div class="task-detail-hero-main">
                            <div class="task-detail-id">{{ selectedTask.taskId || '-' }}</div>
                            <div class="task-detail-meta">
                                <span :class="['task-status-chip', getDetailStatusClass(selectedTask.status)]">{{ getStatusLabel(selectedTask.status) }}</span>
                                <span>{{ inferTaskType(selectedTask) }}</span>
                                <span>阶段：{{ selectedTask.currentStage || '等待回传' }}</span>
                                <span>开始：{{ formatDateTime(selectedTask.startTime) }}</span>
                            </div>
                        </div>
                    </div>

                    <div class="task-detail-card task-detail-card--tabs">
                        <div class="task-detail-tabs">
                            <button
                                type="button"
                                :class="['task-detail-tab', { 'is-active': detailTab === 'summary' }]"
                                @click="detailTab = 'summary'"
                            >
                                核心信息
                            </button>
                            <button
                                type="button"
                                :class="['task-detail-tab', { 'is-active': detailTab === 'process' }]"
                                @click="detailTab = 'process'"
                            >
                                过程信息
                            </button>
                        </div>

                        <div v-if="detailTab === 'summary'" class="task-detail-tab-panel">
                            <div class="task-detail-summary-stack">
                                <div v-for="item in getTaskSummaryStats(selectedTask)" :key="item.label" class="task-detail-summary-item">
                                    <span>{{ item.label }}</span>
                                    <strong>{{ item.value || '-' }}</strong>
                                </div>
                            </div>
                            <div class="task-detail-message-panel">
                                <span>过程信息</span>
                                <strong>{{ selectedTask.message || '暂无过程信息' }}</strong>
                            </div>
                            <div class="task-detail-summary-actions">
                                <el-button v-if="selectedTask.status === 'completed'" type="primary" @click="openPublishFromTask(selectedTask)">将任务结果去发布</el-button>
                            </div>
                        </div>

                        <div v-else class="task-detail-tab-panel">
                            <div v-if="taskEvents.length" class="task-detail-process-shell">
                                <el-timeline class="task-detail-native-timeline">
                                    <el-timeline-item
                                        v-for="event in taskEvents.slice(0, 12)"
                                        :key="event.id || `${event.eventType}-${event.eventAt}`"
                                        :timestamp="formatDateTime(event.eventAt)"
                                        placement="top"
                                    >
                                        <div class="task-detail-timeline-card">
                                            <strong>{{ formatEventType(event.eventType) }}</strong>
                                            <div>{{ event.details?.message || event.details?.stage || event.details?.status || '过程已记录' }}</div>
                                        </div>
                                    </el-timeline-item>
                                </el-timeline>
                            </div>
                            <div v-else class="task-detail-empty-state">暂无过程信息</div>
                        </div>
                    </div>
                </div>
            </template>
        </ResizableDrawer>
    </section>
</template>

<style scoped>
.page-banner {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    padding: 20px 22px;
    border: 1px solid var(--tf-border);
    border-radius: 16px;
    background: var(--tf-surface);
}

.task-detail-summary-actions {
    margin-top: 16px;
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
}

.page-banner__title {
    color: var(--tf-text-primary);
    font-size: 18px;
    font-weight: 700;
}

.page-banner__desc {
    margin-top: 6px;
    color: var(--tf-text-secondary);
    font-size: 13px;
    line-height: 1.7;
}

.page-banner__actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
}

.app-scroll {
    display: flex;
    flex-direction: column;
}

.layui-panel {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
    background: var(--tf-surface);
    border: 1px solid var(--tf-border);
    border-radius: 16px;
    box-shadow: 0 10px 28px rgba(15, 23, 42, 0.04);
    overflow: hidden;
}

.layui-toolbar {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 12px;
    padding: 18px 20px;
    border-bottom: 1px solid var(--tf-border);
    background: var(--tf-surface-soft);
    flex-shrink: 0;
}

.layui-filter-form {
    display: flex;
    align-items: center;
    gap: 14px;
    flex-wrap: wrap;
    flex: 1;
    min-width: 0;
}

.layui-filter-item {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
}

.layui-filter-label {
    color: var(--tf-text-secondary);
    font-size: 13px;
    white-space: nowrap;
}

.layui-filter-control {
    max-width: 100%;
}

.layui-filter-status {
    width: 180px;
}

.layui-filter-date {
    width: 360px;
}

.layui-table-wrap {
    flex: 1;
    min-height: 0;
    overflow: auto;
}

.layui-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
    table-layout: fixed;
}

.layui-table thead tr {
    background: var(--tf-surface-soft);
}

.layui-table th {
    position: sticky;
    top: 0;
    z-index: 1;
    padding: 14px 14px;
    font-weight: 600;
    color: var(--tf-text-primary);
    font-size: 13px;
    text-align: left;
    border-bottom: 1px solid var(--tf-border);
    border-right: 1px solid var(--tf-border);
    background: var(--tf-surface-soft);
    white-space: nowrap;
    user-select: none;
}

.layui-table th:last-child {
    border-right: none;
}

.layui-table td {
    padding: 14px 14px;
    color: var(--tf-text-secondary);
    font-size: 13px;
    border-bottom: 1px solid var(--tf-border);
    border-right: 1px solid var(--tf-border);
    line-height: 1.7;
    word-break: break-all;
    transition: background 0.2s ease;
    vertical-align: middle;
}

.layui-table td:last-child {
    border-right: none;
}

.layui-table tbody tr:nth-child(odd) {
    background: var(--tf-surface);
}

.layui-table tbody tr:nth-child(even) {
    background: var(--tf-surface);
}

.layui-table tbody tr {
    transition: background 0.2s ease;
}

.layui-table tbody tr:hover td {
    background: var(--tf-surface-muted);
}

.cell-center {
    text-align: center;
}

.task-info-cell {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
}

.task-info-id {
    font-family: "Consolas", "Monaco", "Courier New", monospace;
    font-size: 13px;
    color: var(--tf-text-primary);
    line-height: 1.5;
    word-break: break-all;
}

.task-info-meta {
    color: var(--tf-text-muted);
    font-size: 12px;
    line-height: 1.5;
}

.task-stage-cell {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
}

.task-stage-title {
    color: var(--tf-text-primary);
    font-size: 13px;
    font-weight: 600;
    line-height: 1.5;
}

.task-stage-detail {
    color: var(--tf-text-muted);
    font-size: 12px;
    line-height: 1.6;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    overflow: hidden;
}

.cell-empty {
    text-align: center;
    color: var(--tf-text-muted);
    padding: 60px 14px !important;
    font-size: 13px;
}

.layui-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 56px;
    padding: 4px 10px;
    font-size: 12px;
    line-height: 1.4;
    border-radius: 999px;
    color: #fff;
    white-space: nowrap;
    font-weight: 600;
}

.layui-badge-success {
    background: #67c23a;
}

.layui-badge-warning {
    background: #e6a23c;
}

.layui-badge-danger {
    background: #f56c6c;
}

.layui-badge-info {
    background: #909399;
}

.task-progress-value {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 56px;
    padding: 6px 10px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 700;
    line-height: 1;
    border: 1px solid transparent;
}

.task-progress-value-success {
    color: #95de64;
    background: rgba(103, 194, 58, 0.14);
    border-color: rgba(103, 194, 58, 0.28);
}

.task-progress-value-running {
    color: #73c0ff;
    background: rgba(64, 158, 255, 0.14);
    border-color: rgba(64, 158, 255, 0.3);
}

.task-progress-value-danger {
    color: #ff9b9b;
    background: rgba(245, 108, 108, 0.14);
    border-color: rgba(245, 108, 108, 0.28);
}

.task-progress-value-muted {
    color: var(--tf-text-secondary);
    background: rgba(144, 147, 153, 0.14);
    border-color: rgba(144, 147, 153, 0.26);
}

.task-progress-value-default {
    color: var(--tf-text-primary);
    background: var(--tf-surface-muted);
    border-color: var(--tf-border);
}

.layui-table-actions {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16px;
    min-width: 208px;
    white-space: nowrap;
}

.layui-link {
    color: #409eff;
    cursor: pointer;
    font-size: 13px;
    text-decoration: none;
    transition: color 0.2s ease, opacity 0.2s ease;
}

.layui-link:hover {
    color: #66b1ff;
    text-decoration: none;
    opacity: 0.85;
}

.layui-link-warn {
    color: #e6a23c;
}

.layui-link-warn:hover {
    color: #f0c060;
}

.layui-link-danger {
    color: #f56c6c;
}

.layui-link-danger:hover {
    color: #f89898;
}

.layui-table-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 18px;
    border-top: 1px solid var(--tf-border);
    background: var(--tf-surface-soft);
    flex-shrink: 0;
}

.layui-table-count {
    color: var(--tf-text-muted);
    font-size: 13px;
    flex-shrink: 0;
}

.layui-table-footer :deep(.el-pagination .el-pager) {
    display: inline-flex;
    align-items: center;
    gap: 10px;
}

.layui-toolbar :deep(.el-input__wrapper),
.layui-toolbar :deep(.el-range-editor.el-input__wrapper) {
    min-height: 42px;
    border-radius: 12px;
    box-shadow: 0 0 0 1px var(--tf-border-strong) inset;
}

.layui-toolbar :deep(.el-input__wrapper.is-focus),
.layui-toolbar :deep(.el-range-editor.el-input__wrapper.is-focus) {
    box-shadow: 0 0 0 1px var(--tf-accent) inset;
}

.dialog-loading-text {
    color: var(--tf-text-muted);
}

.standard-detail-stack {
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.task-detail-shell {
    display: flex;
    flex-direction: column;
    gap: 18px;
}

.task-detail-hero {
    display: flex;
    align-items: flex-start;
    gap: 16px;
}

.task-detail-hero-main {
    min-width: 0;
    flex: 1;
}

.task-detail-id {
    font-size: 18px;
    font-weight: 700;
    color: var(--tf-text-primary);
    line-height: 1.4;
    word-break: break-word;
}

.task-detail-meta {
    margin-top: 8px;
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    color: var(--tf-text-secondary);
    font-size: 13px;
}

.task-status-chip {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 60px;
    padding: 6px 12px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
    line-height: 1;
    border: 1px solid transparent;
    letter-spacing: 0;
}

.task-status-chip-success {
    color: #95de64 !important;
    background: rgba(103, 194, 58, 0.16);
    border-color: rgba(103, 194, 58, 0.3);
}

.task-status-chip-running {
    color: #73c0ff !important;
    background: rgba(64, 158, 255, 0.16);
    border-color: rgba(64, 158, 255, 0.32);
}

.task-status-chip-danger {
    color: #ffb3b3 !important;
    background: rgba(245, 108, 108, 0.18);
    border-color: rgba(245, 108, 108, 0.34);
}

.task-status-chip-muted {
    color: var(--tf-text-secondary) !important;
    background: rgba(144, 147, 153, 0.16);
    border-color: rgba(144, 147, 153, 0.28);
}

.task-status-chip-default {
    color: var(--tf-text-primary) !important;
    background: var(--tf-surface-muted);
    border-color: var(--tf-border);
}

.task-detail-card {
    border: 1px solid var(--tf-border);
    border-radius: 16px;
    background: var(--tf-surface-soft);
}

.task-detail-card-title {
    display: block;
    margin-bottom: 12px;
    color: var(--tf-text-secondary);
    font-size: 13px;
    font-weight: 600;
}

.task-detail-card {
    padding: 18px;
}

.task-detail-card--tabs {
    padding: 0;
    overflow: hidden;
}

.task-detail-tabs {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 18px 0;
    border-bottom: 1px solid var(--tf-border);
}

.task-detail-tab {
    appearance: none;
    border: 1px solid transparent;
    background: transparent;
    color: var(--tf-text-secondary);
    font-size: 13px;
    font-weight: 700;
    line-height: 1;
    padding: 10px 14px;
    border-radius: 12px 12px 0 0;
    cursor: pointer;
    transition: color 0.18s ease, background 0.18s ease, border-color 0.18s ease;
}

.task-detail-tab:hover {
    color: var(--tf-text-primary);
    background: var(--tf-surface);
}

.task-detail-tab.is-active {
    color: var(--tf-text-primary);
    background: var(--tf-surface);
    border-color: var(--tf-border);
    border-bottom-color: var(--tf-surface);
}

.task-detail-tab-panel {
    padding: 18px;
}

.task-detail-summary-stack {
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.task-detail-message-panel {
    margin-top: 12px;
    padding: 12px 14px;
    border-radius: 12px;
    background: var(--tf-surface);
    border: 1px solid var(--tf-border);
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.task-detail-summary-item {
    padding: 12px 14px;
    border-radius: 12px;
    background: var(--tf-surface);
    border: 1px solid var(--tf-border);
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.task-detail-summary-item span {
    color: var(--tf-text-muted);
    font-size: 12px;
}

.task-detail-message-panel span {
    color: var(--tf-text-muted);
    font-size: 12px;
}

.task-detail-summary-item strong,
.task-detail-message-panel strong,
.task-detail-timeline-card strong {
    color: var(--tf-text-primary);
    font-size: 14px;
    line-height: 1.5;
    word-break: break-word;
}

.task-detail-native-timeline {
    margin-top: 4px;
}

.task-detail-process-shell {
    min-height: 120px;
}

.task-detail-timeline-card {
    padding: 12px 14px;
    border-radius: 12px;
    background: var(--tf-surface);
    border: 1px solid var(--tf-border);
    display: flex;
    flex-direction: column;
    gap: 6px;
    color: var(--tf-text-secondary);
    line-height: 1.6;
}

.task-detail-native-timeline :deep(.el-timeline-item__node) {
    background: var(--tf-accent);
    box-shadow: 0 0 0 4px var(--tf-accent-soft);
}

.task-detail-native-timeline :deep(.el-timeline-item__tail) {
    border-left-color: var(--tf-border);
}

.task-detail-native-timeline :deep(.el-timeline-item__timestamp) {
    color: var(--tf-text-muted);
}

.task-detail-empty-state {
    padding: 36px 20px;
    border-radius: 12px;
    border: 1px dashed var(--tf-border);
    background: var(--tf-surface);
    color: var(--tf-text-muted);
    text-align: center;
    font-size: 13px;
}

@media (max-width: 960px) {
    .page-banner {
        flex-direction: column;
        align-items: stretch;
    }

    .layui-search-input {
        width: 100%;
    }
}
</style>
