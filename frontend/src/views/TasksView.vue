<script setup>
import { computed, onMounted, ref } from 'vue';
import { ElMessageBox } from 'element-plus';

import ResizableDrawer from '../components/ResizableDrawer.vue';
import { api } from '../services/api';
import { formatDateTime } from '../utils/formatters';
import { pushToast } from '../composables/useToast';

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
        tasks.value = Object.values(data.tasks || {});
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

onMounted(load);
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
                        <col style="min-width: 200px" />
                        <col style="width: 90px" />
                        <col style="min-width: 160px" />
                        <col style="width: 165px" />
                        <col style="width: 165px" />
                        <col style="width: 140px" />
                    </colgroup>
                    <thead>
                        <tr>
                            <th>序号</th>
                            <th>任务 ID</th>
                            <th>状态</th>
                            <th>进度</th>
                            <th>开始时间</th>
                            <th>结束时间</th>
                            <th>操作</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="row in visibleTasks" :key="row.taskId">
                            <td class="cell-center">{{ row.orderNo }}</td>
                            <td class="cell-id">{{ row.taskId }}</td>
                            <td class="cell-center">
                                <span :class="['layui-badge', `layui-badge-${getStatusTagType(row.status)}`]">
                                    {{ getStatusLabel(row.status) }}
                                </span>
                            </td>
                            <td>
                                <div class="layui-progress">
                                    <div
                                        class="layui-progress-bar"
                                        :class="{ 'layui-progress-bar-active': row.status === 'running' }"
                                        :style="{ width: formatProgress(row.progress) + '%' }"
                                    />
                                    <span class="layui-progress-text">{{ formatProgress(row.progress) }}%</span>
                                </div>
                            </td>
                            <td>{{ formatDateTime(row.startTime) }}</td>
                            <td>{{ formatDateTime(row.endTime) }}</td>
                            <td class="cell-center">
                                <div class="layui-table-actions">
                                    <a class="layui-link" @click="openDetail(row)">详情</a>
                                    <a v-if="row.status === 'running'" class="layui-link layui-link-warn" @click="stopTask(row.taskId)">停止</a>
                                    <a v-else class="layui-link layui-link-danger" @click="removeTask(row.taskId)">删除</a>
                                </div>
                            </td>
                        </tr>
                        <tr v-if="!visibleTasks.length">
                            <td colspan="7" class="cell-empty">暂无任务数据</td>
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
                                <el-tag :type="getStatusTagType(selectedTask.status)">{{ getStatusLabel(selectedTask.status) }}</el-tag>
                                <span>{{ inferTaskType(selectedTask) }}</span>
                                <span>阶段：{{ selectedTask.currentStage || '等待回传' }}</span>
                                <span>开始：{{ formatDateTime(selectedTask.startTime) }}</span>
                            </div>
                        </div>
                    </div>

                    <div class="task-detail-card task-detail-card--summary">
                        <div class="task-detail-card-title">核心信息</div>
                        <div class="task-detail-progress-panel">
                            <div class="task-detail-progress-row">
                                <el-progress :percentage="formatProgress(selectedTask.progress)" :stroke-width="14" :show-text="false" />
                                <strong>{{ formatProgress(selectedTask.progress) }}%</strong>
                            </div>
                        </div>
                        <div class="task-detail-summary-stack">
                            <div v-for="item in getTaskSummaryStats(selectedTask)" :key="item.label" class="task-detail-summary-item">
                                <span>{{ item.label }}</span>
                                <strong>{{ item.value || '-' }}</strong>
                            </div>
                        </div>
                        <div class="task-detail-message-panel">
                            <span>过程说明</span>
                            <strong>{{ selectedTask.message || '暂无过程说明' }}</strong>
                        </div>
                    </div>

                    <div v-if="taskEvents.length" class="task-detail-card">
                        <div class="task-detail-card-title">最近过程信息</div>
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

.cell-id {
    font-family: "Consolas", "Monaco", "Courier New", monospace;
    font-size: 13px;
    color: var(--tf-text-primary);
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

.layui-progress {
    position: relative;
    height: 18px;
    background: var(--tf-surface-muted);
    border-radius: 999px;
    overflow: hidden;
}

.layui-progress-bar {
    height: 100%;
    background: linear-gradient(90deg, #67c23a, #85ce61);
    border-radius: 999px;
    transition: width 0.6s cubic-bezier(0.4, 0, 0.2, 1);
}

.layui-progress-bar-active {
    background: linear-gradient(90deg, #409eff, #66b1ff);
    background-size: 200% 100%;
    animation: layui-progress-shimmer 2s ease infinite;
}

@keyframes layui-progress-shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
}

.layui-progress-text {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    font-weight: 600;
    color: #fff;
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
}

.layui-table-actions {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16px;
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

.task-detail-progress-panel {
    margin-bottom: 14px;
    padding: 14px 16px;
    border-radius: 12px;
    background: var(--tf-surface);
    border: 1px solid var(--tf-border);
}

.task-detail-progress-row {
    display: flex;
    align-items: center;
    gap: 14px;
}

.task-detail-progress-row :deep(.el-progress) {
    flex: 1;
}

.task-detail-progress-row strong {
    color: var(--tf-text-primary);
    font-size: 18px;
    line-height: 1;
}

.task-detail-card {
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
