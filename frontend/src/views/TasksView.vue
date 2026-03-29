<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import { api } from '../services/api';
import { formatDateTime } from '../utils/formatters';
import { pushToast } from '../composables/useToast';

const tasks = ref([]);
const keyword = ref('');
const dateRange = ref([]);
const currentPage = ref(1);
const pageSize = ref(10);
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

const visibleTasks = computed(() => {
    const offset = (currentPage.value - 1) * pageSize.value;
    return tasks.value.map((task, index) => ({ ...task, orderNo: offset + index + 1 }));
});

async function load() {
    try {
        const taskResponse = await api.getAllTasks({
            page: currentPage.value,
            pageSize: pageSize.value,
            keyword: String(keyword.value || '').trim() || undefined,
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

function handlePageChange(page) {
    currentPage.value = page;
    load();
}

function handlePageSizeChange(size) {
    pageSize.value = size;
    currentPage.value = 1;
    load();
}

function scheduleLoad() {
    if (loadTimer) {
        window.clearTimeout(loadTimer);
    }
    loadTimer = window.setTimeout(() => {
        loadTimer = null;
        load();
    }, 250);
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
        await api.deleteTask(taskId);
        pushToast('任务已删除', 'success');
        await load();
    } catch (error) {
        pushToast(`删除任务失败: ${error.message}`, 'error', 4500);
    }
}

onMounted(load);

watch([keyword, dateRange], () => {
    currentPage.value = 1;
    scheduleLoad();
}, { deep: true });

onBeforeUnmount(() => {
    if (loadTimer) {
        window.clearTimeout(loadTimer);
        loadTimer = null;
    }
});
</script>

<template>
    <section class="app-view">
        <div class="section-header section-header-product">
            <div>
                <h2>任务列表</h2>
                <p class="section-subtitle">统一查看任务排队、执行阶段、结果路径与异常信息，便于生产调度和问题回溯。</p>
            </div>
            <div class="tool-actions task-header-actions">
                <el-button type="primary" @click="load">刷新</el-button>
            </div>
        </div>

        <div class="app-scroll">
            <div class="content-stack">
                <div class="card task-list-shell data-panel">
                    <div class="card-header task-filter-panel task-filter-panel-simple data-toolbar">
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

                    <div class="card-body task-list-body data-table-shell">
                        <el-table class="task-data-table" :data="visibleTasks" stripe border height="100%">
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
                        <div class="task-list-pagination">
                            <el-pagination
                                :current-page="currentPage"
                                :page-size="pageSize"
                                :page-sizes="[10, 20, 50, 100]"
                                :total="totalTasks"
                                background
                                layout="total, sizes, prev, pager, next, jumper"
                                @current-change="handlePageChange"
                                @size-change="handlePageSizeChange"
                            />
                        </div>
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

.task-list-pagination {
    display: flex;
    justify-content: flex-end;
    padding: 16px 18px 18px;
    border-top: 1px solid rgba(145, 160, 180, 0.12);
}

.task-table-actions {
    display: flex;
    align-items: center;
    gap: 8px;
}

.task-list-shell {
    border: 1px solid rgba(145, 160, 180, 0.14);
    background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.02), transparent),
        linear-gradient(160deg, rgba(8, 16, 28, 0.92), rgba(10, 19, 32, 0.96));
    box-shadow: 0 18px 38px rgba(0, 0, 0, 0.16);
}

.task-list-shell.data-panel {
    border-radius: 30px;
    border-color: rgba(129, 150, 181, 0.16);
    background:
        radial-gradient(circle at top right, rgba(92, 132, 190, 0.1), transparent 26%),
        linear-gradient(180deg, rgba(255, 255, 255, 0.03), transparent 22%),
        linear-gradient(160deg, rgba(7, 14, 24, 0.98), rgba(8, 15, 26, 0.95));
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.04),
        0 26px 54px rgba(0, 0, 0, 0.22);
}

.task-filter-panel {
    border-bottom: 1px solid rgba(145, 160, 180, 0.12);
}

.task-list-shell :deep(.el-input__wrapper),
.task-list-shell :deep(.el-range-editor.el-input__wrapper) {
    background: rgba(6, 14, 24, 0.9) !important;
    border-radius: 14px !important;
    box-shadow:
        inset 0 0 0 1px rgba(82, 112, 147, 0.3) !important,
        0 10px 24px rgba(0, 0, 0, 0.08) !important;
}

.task-list-shell :deep(.el-input__wrapper.is-focus),
.task-list-shell :deep(.el-range-editor.el-input__wrapper.is-active) {
    box-shadow:
        inset 0 0 0 1px rgba(103, 240, 255, 0.26) !important,
        0 0 0 4px rgba(31, 164, 255, 0.08) !important;
}

.task-list-shell :deep(.el-input__inner),
.task-list-shell :deep(.el-range-input),
.task-list-shell :deep(.el-range-separator),
.task-list-shell :deep(.el-input__icon) {
    color: var(--tf-text) !important;
}

.task-list-shell :deep(.el-input__inner::placeholder),
.task-list-shell :deep(.el-range-input::placeholder) {
    color: var(--tf-text-dim) !important;
}

.task-list-shell :deep(.el-table) {
    color: var(--tf-text) !important;
    border: 1px solid rgba(108, 134, 168, 0.14) !important;
    border-radius: 26px !important;
    overflow: hidden !important;
    background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.02), transparent),
        linear-gradient(150deg, rgba(10, 17, 29, 0.96), rgba(9, 15, 25, 0.92)) !important;
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.03),
        0 16px 30px rgba(0, 0, 0, 0.14) !important;
}

.task-list-shell :deep(.el-table::before),
.task-list-shell :deep(.el-table__inner-wrapper::before) {
    display: none !important;
}

.task-list-shell :deep(.el-table__header-wrapper) {
    background: linear-gradient(180deg, rgba(31, 43, 63, 0.96), rgba(25, 35, 52, 0.92)) !important;
}

.task-list-shell :deep(.el-table__header-wrapper th.el-table__cell) {
    background: transparent !important;
    border-bottom-color: rgba(108, 134, 168, 0.16) !important;
    color: #dbe7f4 !important;
    font-weight: 700 !important;
    letter-spacing: 0.02em !important;
    padding-top: 18px !important;
    padding-bottom: 18px !important;
}

.task-list-shell :deep(.el-table__body td.el-table__cell) {
    border-bottom-color: rgba(108, 134, 168, 0.1) !important;
    padding-top: 18px !important;
    padding-bottom: 18px !important;
}

.task-list-shell :deep(.el-table__body tr.el-table__row > td.el-table__cell),
.task-list-shell :deep(.el-table__fixed-body-wrapper tr.el-table__row > td.el-table__cell) {
    background: rgba(11, 20, 33, 0.82) !important;
}

.task-list-shell :deep(.el-table--striped .el-table__body tr.el-table__row--striped > td.el-table__cell) {
    background: rgba(15, 25, 40, 0.86) !important;
}

.task-list-shell :deep(.el-table__body tr.el-table__row:hover > td.el-table__cell),
.task-list-shell :deep(.el-table__fixed-body-wrapper tr.el-table__row:hover > td.el-table__cell) {
    background: rgba(20, 33, 50, 0.94) !important;
}

.task-list-shell :deep(.el-table__fixed),
.task-list-shell :deep(.el-table__fixed-right),
.task-list-shell :deep(.el-table__fixed-right-patch) {
    background: rgba(11, 19, 31, 0.96) !important;
}

.task-list-shell :deep(.el-table__fixed-right::before),
.task-list-shell :deep(.el-table__fixed::before) {
    background: linear-gradient(180deg, rgba(108, 134, 168, 0.16), rgba(108, 134, 168, 0.04)) !important;
}

.task-list-shell :deep(.el-table .cell) {
    line-height: 1.6;
}

.task-table-actions :deep(.el-button),
.task-header-actions :deep(.el-button) {
    min-width: 62px;
    border-radius: 10px;
    padding-inline: 14px;
    font-weight: 700;
}

.task-header-actions :deep(.el-button--primary),
.task-table-actions :deep(.el-button--primary) {
    border-color: rgba(196, 205, 216, 0.16);
    background: linear-gradient(135deg, rgba(142, 169, 201, 0.96), rgba(88, 109, 137, 0.92));
    color: #08111b;
    box-shadow: 0 10px 24px rgba(44, 56, 74, 0.26);
}

.task-table-actions :deep(.el-button--warning) {
    border-color: rgba(246, 207, 140, 0.16);
    background: linear-gradient(135deg, rgba(198, 161, 102, 0.94), rgba(139, 113, 67, 0.9));
    color: #101010;
}

.task-table-actions :deep(.el-button--danger) {
    border-color: rgba(233, 171, 183, 0.16);
    background: linear-gradient(135deg, rgba(201, 103, 120, 0.94), rgba(138, 59, 76, 0.9));
}

.task-table-actions :deep(.el-button:not(.el-button--primary):not(.el-button--warning):not(.el-button--danger)),
.task-header-actions :deep(.el-button:not(.el-button--primary):not(.el-button--warning):not(.el-button--danger)) {
    border-color: rgba(156, 170, 188, 0.16);
    background: linear-gradient(135deg, rgba(34, 44, 58, 0.96), rgba(22, 29, 39, 0.94));
    color: #dce6f1;
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

.task-list-shell :deep(.el-progress-bar__outer) {
    background: rgba(255, 255, 255, 0.06);
}

.task-list-shell :deep(.el-progress-bar__inner) {
    background: linear-gradient(90deg, rgba(114, 213, 224, 0.92), rgba(82, 150, 217, 0.86));
}

.task-list-shell :deep(.el-tag) {
    border-radius: 999px;
    font-weight: 700;
    padding-inline: 10px;
}

.task-list-pagination :deep(.el-pagination) {
    gap: 8px;
}

.task-list-pagination :deep(.btn-prev),
.task-list-pagination :deep(.btn-next),
.task-list-pagination :deep(.el-pager li) {
    min-width: 38px;
    height: 38px;
    border: 1px solid rgba(108, 134, 168, 0.14) !important;
    border-radius: 12px;
    background: rgba(16, 27, 42, 0.92) !important;
    color: var(--tf-text) !important;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
}

.task-list-pagination :deep(.el-pager li.is-active) {
    border-color: rgba(103, 240, 255, 0.2) !important;
    background: linear-gradient(135deg, rgba(75, 133, 214, 0.96), rgba(62, 111, 176, 0.92)) !important;
    color: #f5fbff !important;
}

.task-list-pagination :deep(.el-pagination__total),
.task-list-pagination :deep(.el-pagination__jump),
.task-list-pagination :deep(.el-pagination__sizes),
.task-list-pagination :deep(.el-pagination__goto) {
    color: var(--tf-text-soft) !important;
}

.task-list-pagination :deep(.el-select .el-select__wrapper),
.task-list-pagination :deep(.el-input .el-input__wrapper) {
    min-height: 38px;
    border-radius: 12px;
    background: rgba(16, 27, 42, 0.92) !important;
    box-shadow: inset 0 0 0 1px rgba(108, 134, 168, 0.18) !important;
}

.task-list-pagination :deep(.el-select__selected-item),
.task-list-pagination :deep(.el-input__inner),
.task-list-pagination :deep(.el-select__caret),
.task-list-pagination :deep(.el-input__icon) {
    color: var(--tf-text) !important;
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
