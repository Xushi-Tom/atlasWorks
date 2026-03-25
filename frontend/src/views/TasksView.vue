<script setup>
import { computed, onMounted, ref } from 'vue';

import { api } from '../services/api';
import { formatDateTime } from '../utils/formatters';
import { pushToast } from '../composables/useToast';

const tasks = ref([]);
const keyword = ref('');
const dateRange = ref([]);
const detailVisible = ref(false);
const detailLoading = ref(false);
const selectedTask = ref(null);
const taskEvents = ref([]);

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

const filteredTasks = computed(() => {
    const needle = String(keyword.value || '').trim().toLowerCase();
    const hasDateRange = Array.isArray(dateRange.value) && dateRange.value.length === 2;
    const fromDate = hasDateRange ? normalizeTaskDate(`${dateRange.value[0]}T00:00:00`) : null;
    const toDate = hasDateRange ? normalizeTaskDate(`${dateRange.value[1]}T23:59:59`) : null;

    return [...tasks.value]
        .filter(task => {
            const taskDate = normalizeTaskDate(task.startTime);
            if (fromDate && (!taskDate || taskDate < fromDate)) return false;
            if (toDate && (!taskDate || taskDate > toDate)) return false;
            return true;
        })
        .filter(task => {
            if (!needle) return true;
            const searchPool = [
                task.taskId,
                getStatusLabel(task.status),
                task.currentStage,
                task.message,
                inferTaskType(task)
            ];
            return searchPool.some(item => String(item || '').toLowerCase().includes(needle));
        })
        .sort((a, b) => String(b.startTime || '').localeCompare(String(a.startTime || '')))
        .map((task, index) => ({ ...task, orderNo: index + 1 }));
});

async function load() {
    try {
        const taskResponse = await api.getAllTasks();
        tasks.value = Object.values(taskResponse?.tasks || {});
    } catch (error) {
        pushToast(`任务列表加载失败: ${error.message}`, 'error', 4500);
    }
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
        selectedTask.value = taskDetail;
        taskEvents.value = eventsResponse?.events || [];
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
        await api.deleteTask(taskId);
        pushToast('任务已删除', 'success');
        await load();
    } catch (error) {
        pushToast(`删除任务失败: ${error.message}`, 'error', 4500);
    }
}

onMounted(load);
</script>

<template>
    <section class="app-view">
        <div class="section-header section-header-product">
            <div>
                <h2>任务列表</h2>
                <p class="section-subtitle">统一查看任务排队、执行阶段、结果路径与异常信息，便于生产调度和问题回溯。</p>
            </div>
            <div class="tool-actions">
                <el-button type="primary" @click="load">刷新</el-button>
            </div>
        </div>

        <div class="app-scroll">
            <div class="content-stack">
                <div class="card task-list-shell">
                    <div class="card-header task-filter-panel task-filter-panel-simple">
                        <div class="task-filter-regular">
                            <el-input v-model="keyword" clearable placeholder="任务 ID / 状态 / 阶段 / 结果路径" />
                            <el-date-picker
                                v-model="dateRange"
                                type="daterange"
                                range-separator="至"
                                start-placeholder="开始日期"
                                end-placeholder="结束日期"
                                value-format="YYYY-MM-DD"
                            />
                        </div>
                    </div>

                    <div class="card-body task-list-body">
                        <el-table class="task-data-table" :data="filteredTasks" stripe border height="100%">
                            <el-table-column prop="orderNo" label="序号" width="80" />
                            <el-table-column prop="taskId" label="任务 ID" min-width="220" />
                            <el-table-column label="状态" width="110">
                                <template #default="{ row }">
                                    <el-tag :type="getStatusTagType(row.status)">{{ getStatusLabel(row.status) }}</el-tag>
                                </template>
                            </el-table-column>
                            <el-table-column label="进度" min-width="180">
                                <template #default="{ row }">
                                    <el-progress :percentage="formatProgress(row.progress)" :stroke-width="12" />
                                </template>
                            </el-table-column>
                            <el-table-column label="开始时间" min-width="170">
                                <template #default="{ row }">
                                    {{ formatDateTime(row.startTime) }}
                                </template>
                            </el-table-column>
                            <el-table-column label="结束时间" min-width="170">
                                <template #default="{ row }">
                                    {{ formatDateTime(row.endTime) }}
                                </template>
                            </el-table-column>
                            <el-table-column label="操作" width="220" fixed="right">
                                <template #default="{ row }">
                                    <div class="task-table-actions">
                                        <el-button size="small" @click="openDetail(row)">详情</el-button>
                                        <el-button v-if="row.status === 'running'" size="small" type="warning" @click="stopTask(row.taskId)">停止</el-button>
                                        <el-button v-else size="small" type="danger" @click="removeTask(row.taskId)">删除</el-button>
                                    </div>
                                </template>
                            </el-table-column>
                        </el-table>
                    </div>
                </div>
            </div>
        </div>

        <el-dialog v-model="detailVisible" class="task-detail-dialog" title="任务详情" width="980px" destroy-on-close>
            <div v-if="detailLoading" class="message info">正在加载任务详情...</div>
            <template v-else-if="selectedTask">
                <div class="task-detail-overview">
                    <div class="task-detail-overview-main">
                        <span class="task-detail-overview-label">任务 ID</span>
                        <strong class="task-detail-overview-id">{{ selectedTask.taskId || '-' }}</strong>
                    </div>
                    <div class="task-detail-overview-meta">
                        <el-tag :type="getStatusTagType(selectedTask.status)">{{ getStatusLabel(selectedTask.status) }}</el-tag>
                        <span>{{ inferTaskType(selectedTask) }}</span>
                        <span>阶段：{{ selectedTask.currentStage || '等待回传' }}</span>
                        <span>开始：{{ formatDateTime(selectedTask.startTime) }}</span>
                    </div>
                    <div class="task-detail-overview-progress">
                        <span>执行进度</span>
                        <el-progress :percentage="formatProgress(selectedTask.progress)" :stroke-width="14" />
                    </div>
                </div>

                <div class="task-detail-grid">
                    <div class="task-detail-field">
                        <span>当前阶段</span>
                        <strong>{{ selectedTask.currentStage || '等待回传' }}</strong>
                    </div>
                    <div class="task-detail-field">
                        <span>结束时间</span>
                        <strong>{{ formatDateTime(selectedTask.endTime) }}</strong>
                    </div>
                    <div class="task-detail-field">
                        <span>产物 ID</span>
                        <strong>{{ selectedTask.result?.artifactId || '-' }}</strong>
                    </div>
                    <div class="task-detail-field task-detail-field-wide">
                        <span>输出目录</span>
                        <strong>{{ selectedTask.result?.outputPath || '-' }}</strong>
                    </div>
                    <div class="task-detail-field task-detail-field-wide">
                        <span>合并输出</span>
                        <strong>{{ selectedTask.result?.mergedOutputPath || '-' }}</strong>
                    </div>
                    <div class="task-detail-field">
                        <span>成功文件</span>
                        <strong>{{ selectedTask.result?.completedFiles ?? 0 }}</strong>
                    </div>
                    <div class="task-detail-field">
                        <span>失败文件</span>
                        <strong>{{ selectedTask.result?.failedFiles ?? 0 }}</strong>
                    </div>
                </div>

                <div class="task-detail-message-box">
                    {{ selectedTask.message || '暂无过程说明' }}
                </div>

                <div v-if="taskEvents.length" class="task-event-list">
                    <div class="task-event-title">最近过程信息</div>
                    <el-timeline class="task-detail-timeline">
                        <el-timeline-item
                            v-for="event in taskEvents.slice(0, 12)"
                            :key="event.id || `${event.eventType}-${event.eventAt}`"
                            :timestamp="formatDateTime(event.eventAt)"
                        >
                            <strong>{{ formatEventType(event.eventType) }}</strong>
                            <div>{{ event.details?.message || event.details?.stage || event.details?.status || '过程已记录' }}</div>
                        </el-timeline-item>
                    </el-timeline>
                </div>
            </template>
        </el-dialog>
    </section>
</template>

<style scoped>
.task-filter-regular {
    width: 100%;
    display: grid;
    gap: 12px;
    grid-template-columns: minmax(220px, 1fr) minmax(280px, 420px);
}

.task-list-body {
    min-height: 520px;
}

.task-table-actions {
    display: flex;
    align-items: center;
    gap: 8px;
}

.task-table-actions :deep(.el-button) {
    min-width: 56px;
    padding-inline: 12px;
}

.task-detail-overview {
    padding: 14px 16px;
    border-radius: 14px;
    border: 1px solid rgba(74, 195, 255, 0.22);
    background: linear-gradient(145deg, rgba(14, 33, 54, 0.62), rgba(8, 19, 34, 0.72));
    display: grid;
    gap: 12px;
}

.task-detail-overview-main {
    display: flex;
    flex-direction: column;
    gap: 5px;
}

.task-detail-overview-label {
    font-size: 12px;
    color: var(--tf-text-dim);
    letter-spacing: 0.04em;
}

.task-detail-overview-id {
    color: var(--tf-text);
    font-size: 22px;
    line-height: 1.35;
    word-break: break-word;
}

.task-detail-overview-meta {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
    color: var(--tf-text-soft);
}

.task-detail-overview-meta span {
    padding: 4px 10px;
    border-radius: 999px;
    border: 1px solid rgba(74, 195, 255, 0.2);
    background: rgba(5, 16, 30, 0.64);
    font-size: 12px;
}

.task-detail-overview-progress {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.task-detail-overview-progress > span {
    font-size: 12px;
    color: var(--tf-text-dim);
}

.task-detail-grid {
    margin-top: 16px;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 10px;
}

.task-detail-field {
    min-width: 0;
    padding: 12px 14px;
    border-radius: 12px;
    border: 1px solid rgba(74, 195, 255, 0.18);
    background: rgba(7, 20, 36, 0.62);
    display: flex;
    flex-direction: column;
    gap: 5px;
}

.task-detail-field span {
    color: var(--tf-text-dim);
    font-size: 12px;
}

.task-detail-field strong {
    color: var(--tf-text);
    line-height: 1.5;
    word-break: break-word;
}

.task-detail-field-wide {
    grid-column: span 2;
}

.task-detail-message-box {
    margin-top: 16px;
    padding: 12px 14px;
    border-radius: 10px;
    border: 1px solid var(--tf-border);
    background: linear-gradient(145deg, rgba(103, 240, 255, 0.06), rgba(31, 164, 255, 0.03));
    color: var(--tf-text-soft);
}

.task-event-list {
    margin-top: 20px;
}

.task-event-title {
    font-weight: 600;
    margin-bottom: 10px;
    color: var(--tf-text);
}

.task-filter-panel :deep(.el-input__wrapper),
.task-filter-panel :deep(.el-range-editor.el-input__wrapper) {
    background: rgba(3, 12, 24, 0.72);
    box-shadow: 0 0 0 1px rgba(74, 195, 255, 0.22) inset;
}

.task-filter-panel :deep(.el-input__inner),
.task-filter-panel :deep(.el-range-input),
.task-filter-panel :deep(.el-range-separator) {
    color: var(--tf-text);
}

.task-filter-panel :deep(.el-input__inner::placeholder) {
    color: var(--tf-text-dim);
}

.task-list-shell :deep(.el-table) {
    --el-table-header-bg-color: rgba(13, 34, 60, 0.95);
    --el-table-tr-bg-color: rgba(8, 22, 38, 0.84);
    --el-table-striped-bg-color: rgba(15, 38, 63, 0.66);
    --el-table-row-hover-bg-color: rgba(31, 164, 255, 0.14);
    --el-table-border-color: rgba(74, 195, 255, 0.24);
    --el-table-text-color: var(--tf-text);
    --el-table-header-text-color: #bfe8ff;
    --el-table-bg-color: rgba(6, 14, 26, 0.84);
    color: var(--tf-text);
    border-radius: 10px;
    overflow: hidden;
}

.task-list-shell :deep(.el-table__header-wrapper th.el-table__cell) {
    font-weight: 600;
    letter-spacing: 0.02em;
}

.task-list-shell :deep(.el-table__body tr td.el-table__cell) {
    border-bottom-color: rgba(74, 195, 255, 0.18);
}

.task-list-shell :deep(.el-table__body tr.el-table__row > td.el-table__cell) {
    background: rgba(6, 18, 32, 0.86);
}

.task-list-shell :deep(.el-table--striped .el-table__body tr.el-table__row--striped > td.el-table__cell) {
    background: rgba(13, 31, 52, 0.82);
}

.task-list-shell :deep(.el-table__body tr.el-table__row:hover > td.el-table__cell) {
    background: rgba(31, 164, 255, 0.16) !important;
}

.task-list-shell :deep(.el-progress-bar__outer) {
    background: rgba(255, 255, 255, 0.08);
}

.task-list-shell :deep(.el-progress-bar__inner) {
    background: linear-gradient(90deg, var(--tf-accent), var(--tf-accent-strong));
}

:deep(.task-detail-dialog.el-dialog) {
    background: linear-gradient(160deg, rgba(4, 14, 26, 0.96), rgba(9, 24, 42, 0.97));
    border: 1px solid rgba(74, 195, 255, 0.3);
    box-shadow: 0 20px 44px rgba(0, 0, 0, 0.5);
}

:deep(.task-detail-dialog .el-dialog__header) {
    border-bottom: 1px solid rgba(74, 195, 255, 0.2);
    margin-right: 0;
    padding: 16px 20px;
}

:deep(.task-detail-dialog .el-dialog__title),
:deep(.task-detail-dialog .el-dialog__close) {
    color: var(--tf-text);
}

:deep(.task-detail-dialog .el-dialog__body) {
    color: var(--tf-text-soft);
    padding-top: 14px;
}

:deep(.task-detail-dialog .el-progress__text) {
    color: var(--tf-text-soft);
}

:deep(.task-detail-dialog .el-timeline-item__tail) {
    border-left-color: rgba(74, 195, 255, 0.36);
}

:deep(.task-detail-dialog .el-timeline-item__node--normal) {
    background: var(--tf-accent);
}

:deep(.task-detail-dialog .el-timeline-item__timestamp) {
    color: var(--tf-text-dim);
}

:deep(.task-detail-dialog .el-timeline-item__content) {
    color: var(--tf-text-soft);
}

@media (max-width: 960px) {
    .task-filter-regular {
        grid-template-columns: 1fr;
    }

    .task-table-actions {
        flex-wrap: wrap;
    }

    .task-detail-grid {
        grid-template-columns: 1fr;
    }

    .task-detail-field-wide {
        grid-column: auto;
    }
}
</style>
