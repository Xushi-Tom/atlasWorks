<script setup>
import { computed, onMounted, ref } from 'vue';

import { ElMessage } from 'element-plus';

import { api } from '../services/api';
import { formatBytes } from '../utils/formatters';

const health = ref(null);
const systemInfo = ref(null);
const tasks = ref([]);
const taskTotal = ref(0);
const taskStats = ref({});
const loading = ref(true);

const metrics = computed(() => {
    const stats = taskStats.value || {};
    return [
        {
            label: '总任务数',
            value: taskTotal.value,
            tone: 'primary'
        },
        {
            label: '运行中',
            value: stats.running ?? 0,
            tone: 'processing'
        },
        {
            label: '已完成',
            value: stats.completed ?? 0,
            tone: 'success'
        },
        {
            label: '失败',
            value: stats.failed ?? 0,
            tone: 'danger'
        }
    ];
});

const taskSummary = computed(() => {
    const summary = {
        running: 0,
        completed: 0,
        failed: 0
    };
    tasks.value.forEach(task => {
        const status = String(task?.status || '').toLowerCase();
        if (status === 'running') summary.running += 1;
        if (status === 'completed') summary.completed += 1;
        if (status === 'failed') summary.failed += 1;
    });
    return summary;
});

const memoryUsage = computed(() => {
    const total = Number(systemInfo.value?.system?.memoryTotal || 0);
    const available = Number(systemInfo.value?.system?.memoryAvailable || 0);
    if (!total || available < 0) return 0;
    return Math.max(0, Math.min(100, Math.round(((total - available) / total) * 100)));
});

const diskUsage = computed(() => {
    const value = Number(systemInfo.value?.system?.diskUsage || 0);
    return Number.isFinite(value) ? Math.max(0, Math.min(100, Math.round(value))) : 0;
});

const memoryUsed = computed(() => {
    const total = Number(systemInfo.value?.system?.memoryTotal || 0);
    const available = Number(systemInfo.value?.system?.memoryAvailable || 0);
    return total > 0 ? Math.max(0, total - available) : 0;
});

const diskTotal = computed(() => Number(systemInfo.value?.system?.diskTotal || 0));
const diskFree = computed(() => Number(systemInfo.value?.system?.diskFree || 0));
const diskUsed = computed(() => {
    const total = diskTotal.value;
    const free = diskFree.value;
    return total > 0 ? Math.max(0, total - free) : 0;
});

function translateHealthStatus(value) {
    const normalized = String(value || '').trim().toLowerCase();
    if (!normalized) return '未知';
    if (normalized === 'ok' || normalized === 'healthy') return '正常';
    if (normalized === 'warning' || normalized === 'degraded') return '告警';
    if (normalized === 'error' || normalized === 'failed' || normalized === 'unhealthy') return '异常';
    return value;
}

function healthTagType(value) {
    const normalized = String(value || '').trim().toLowerCase();
    if (normalized === 'ok' || normalized === 'healthy') return 'success';
    if (normalized === 'warning' || normalized === 'degraded') return 'warning';
    if (normalized === 'error' || normalized === 'failed' || normalized === 'unhealthy') return 'danger';
    return 'info';
}

async function load() {
    loading.value = true;
    try {
        const [healthResponse, systemResponse, tasksResponse] = await Promise.all([
            api.getHealth(),
            api.getSystemInfo(),
            api.getAllTasks({ page: 1, pageSize: 500 })
        ]);
        health.value = healthResponse?.data || null;
        systemInfo.value = systemResponse?.data || null;
        tasks.value = Object.values(tasksResponse?.data?.tasks || {});
        taskStats.value = tasksResponse?.data?.stats || taskSummary.value;
        taskTotal.value = Number(tasksResponse?.data?.total ?? taskStats.value?.total ?? tasks.value.length ?? 0);
    } catch (error) {
        ElMessage.error(`仪表盘加载失败: ${error.message}`);
    } finally {
        loading.value = false;
    }
}

onMounted(load);
</script>

<template>
    <section class="app-view dashboard-view">
        <div class="app-scroll">
            <div class="dashboard-shell">
                <section class="dashboard-hero">
                    <div class="dashboard-hero__main">
                        <div class="dashboard-hero__title">AtlasWorks 控制台</div>
                        <div class="dashboard-hero__subtitle">
                            汇总任务、资源、服务健康与目录挂载，直接看当前系统运行状态。
                        </div>
                    </div>
                    <div class="dashboard-hero__side">
                        <el-button type="primary" @click="load">刷新数据</el-button>
                    </div>
                </section>

                <section class="dashboard-metrics">
                    <article
                        v-for="metric in metrics"
                        :key="metric.label"
                        class="metric-tile"
                        :class="`metric-tile--${metric.tone}`"
                    >
                        <div class="metric-tile__label">{{ metric.label }}</div>
                        <div class="metric-tile__value">{{ metric.value }}</div>
                    </article>
                </section>

                <section class="dashboard-grid">
                    <el-card shadow="never" class="dashboard-card">
                        <template #header>
                            <div class="dashboard-card__head">
                                <span>服务健康</span>
                                <el-tag class="dashboard-status-tag" :type="healthTagType(health?.status)" effect="light">
                                    {{ translateHealthStatus(health?.status) }}
                                </el-tag>
                            </div>
                        </template>

                        <div v-if="loading" class="dashboard-loading">
                            <el-skeleton :rows="5" animated />
                        </div>
                        <div v-else class="kv-stack">
                            <div class="kv-row">
                                <span>数据库</span>
                                <strong>{{ translateHealthStatus(health?.database?.status) }}</strong>
                            </div>
                            <div class="kv-row">
                                <span>运行中任务</span>
                                <strong>{{ health?.tasks?.running ?? 0 }}</strong>
                            </div>
                            <div class="kv-row">
                                <span>排队任务</span>
                                <strong>{{ health?.tasks?.queued ?? 0 }}</strong>
                            </div>
                            <div class="kv-row">
                                <span>最后更新时间</span>
                                <strong>{{ health?.timestamp || '-' }}</strong>
                            </div>
                        </div>
                    </el-card>

                    <el-card shadow="never" class="dashboard-card">
                        <template #header>
                            <div class="dashboard-card__head">
                                <span>资源概览</span>
                                <span class="dashboard-card__minor">{{ systemInfo?.system?.cpuCount ?? '-' }} 核 CPU</span>
                            </div>
                        </template>

                        <div v-if="loading" class="dashboard-loading">
                            <el-skeleton :rows="5" animated />
                        </div>
                        <div v-else class="resource-stack">
                            <div class="resource-row">
                                <div class="resource-row__head">
                                    <span>内存占用</span>
                                    <strong>{{ memoryUsage }}%</strong>
                                </div>
                                <el-progress :percentage="memoryUsage" :stroke-width="10" :show-text="false" />
                                <div class="resource-row__desc">
                                    {{ formatBytes(memoryUsed) }}
                                    /
                                    {{ formatBytes(systemInfo?.system?.memoryTotal) }}
                                </div>
                            </div>
                            <div class="resource-foot">
                                <span>可用内存</span>
                                <strong>{{ formatBytes(systemInfo?.system?.memoryAvailable) }}</strong>
                            </div>
                            <div class="resource-row">
                                <div class="resource-row__head">
                                    <span>磁盘占用</span>
                                    <strong>{{ diskUsage }}%</strong>
                                </div>
                                <el-progress :percentage="diskUsage" :stroke-width="10" status="warning" :show-text="false" />
                                <div class="resource-row__desc">
                                    {{ formatBytes(diskUsed) }}
                                    /
                                    {{ formatBytes(diskTotal) }}
                                </div>
                            </div>
                            <div class="resource-foot">
                                <span>剩余磁盘</span>
                                <strong>{{ formatBytes(diskFree) }}</strong>
                            </div>
                        </div>
                    </el-card>
                </section>

                <section class="dashboard-strip-card">
                    <el-card shadow="never" class="dashboard-card">
                        <template #header>
                            <div class="dashboard-card__head">
                                <span>目录与版本</span>
                            </div>
                        </template>
                        <div v-if="loading" class="dashboard-loading">
                            <el-skeleton :rows="3" animated />
                        </div>
                        <div v-else class="info-strip">
                            <div class="info-strip__item">
                                <span>版本</span>
                                <strong>{{ systemInfo?.version || health?.version || '-' }}</strong>
                            </div>
                            <div class="info-strip__item">
                                <span>数据源目录</span>
                                <strong>{{ systemInfo?.config?.dataSourceDir || '-' }}</strong>
                            </div>
                            <div class="info-strip__item">
                                <span>瓦片目录</span>
                                <strong>{{ systemInfo?.config?.tilesDir || '-' }}</strong>
                            </div>
                            <div class="info-strip__item">
                                <span>最大线程</span>
                                <strong>{{ systemInfo?.config?.maxThreads || '-' }}</strong>
                            </div>
                            <div class="info-strip__item">
                                <span>支持格式</span>
                                <strong>{{ (systemInfo?.config?.supportedFormats || []).join(', ') || '-' }}</strong>
                            </div>
                        </div>
                    </el-card>
                </section>
            </div>
        </div>
    </section>
</template>

<style scoped>
.dashboard-shell {
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.dashboard-hero {
    position: sticky;
    top: 0;
    z-index: 25;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 24px;
    padding: 24px 28px;
    border: 1px solid var(--tf-border);
    border-radius: 18px;
    background: var(--tf-surface);
    box-shadow: 0 12px 28px rgba(15, 23, 42, 0.05);
}

.dashboard-hero__title {
    color: var(--tf-text-primary);
    font-size: 24px;
    font-weight: 700;
    line-height: 1.2;
}

.dashboard-hero__subtitle {
    margin-top: 8px;
    max-width: 720px;
    color: var(--tf-text-secondary);
    font-size: 14px;
    line-height: 1.7;
}

.dashboard-metrics {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 16px;
}

.metric-tile {
    padding: 18px 20px;
    border: 1px solid var(--tf-border);
    border-radius: 16px;
    background: var(--tf-surface);
    box-shadow: 0 10px 24px rgba(15, 23, 42, 0.04);
}

.metric-tile__label {
    color: var(--tf-text-muted);
    font-size: 13px;
}

.metric-tile__value {
    margin-top: 10px;
    color: var(--tf-text-primary);
    font-size: 32px;
    font-weight: 700;
    line-height: 1;
}

.metric-tile--primary .metric-tile__value {
    color: #2563eb;
}

.metric-tile--processing .metric-tile__value {
    color: #0f766e;
}

.metric-tile--success .metric-tile__value {
    color: #16a34a;
}

.metric-tile--danger .metric-tile__value {
    color: #dc2626;
}

.dashboard-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16px;
}

.dashboard-strip-card {
    display: block;
}

.dashboard-card {
    border-radius: 16px;
}

.dashboard-card__head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    font-weight: 600;
    color: var(--tf-text-primary);
}

.dashboard-card__minor {
    color: var(--tf-text-muted);
    font-size: 12px;
    font-weight: 500;
}

.dashboard-card :deep(.dashboard-status-tag.el-tag) {
    padding: 0 10px;
    border-radius: 999px;
    border: 1px solid transparent;
    font-weight: 600;
}

.dashboard-card :deep(.dashboard-status-tag.el-tag--success.el-tag--light) {
    background: rgba(34, 197, 94, 0.14);
    border-color: rgba(34, 197, 94, 0.28);
    color: #4ade80;
}

.dashboard-card :deep(.dashboard-status-tag.el-tag--warning.el-tag--light) {
    background: rgba(245, 158, 11, 0.16);
    border-color: rgba(245, 158, 11, 0.3);
    color: #fbbf24;
}

.dashboard-card :deep(.dashboard-status-tag.el-tag--danger.el-tag--light) {
    background: rgba(239, 68, 68, 0.16);
    border-color: rgba(239, 68, 68, 0.28);
    color: #f87171;
}

.dashboard-card :deep(.dashboard-status-tag.el-tag--info.el-tag--light) {
    background: rgba(148, 163, 184, 0.14);
    border-color: rgba(148, 163, 184, 0.22);
    color: #cbd5e1;
}

.dashboard-loading {
    padding: 4px 0;
}

.kv-stack {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.kv-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 12px 14px;
    border-radius: 12px;
    background: var(--tf-surface-soft);
    color: var(--tf-text-secondary);
    font-size: 13px;
}

.kv-row strong {
    color: var(--tf-text-primary);
    font-size: 13px;
    text-align: right;
    word-break: break-all;
}

.resource-stack {
    display: flex;
    flex-direction: column;
    gap: 18px;
}

.resource-row {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.resource-row__head,
.resource-foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    color: var(--tf-text-secondary);
    font-size: 13px;
}

.resource-row__head strong,
.resource-foot strong {
    color: var(--tf-text-primary);
}

.resource-row__desc {
    color: var(--tf-text-muted);
    font-size: 12px;
}

.info-strip {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 12px;
}

.info-strip__item {
    min-width: 0;
    padding: 14px 16px;
    border-radius: 14px;
    background: var(--tf-surface-soft);
    border: 1px solid var(--tf-border);
}

.info-strip__item span {
    display: block;
    color: var(--tf-text-muted);
    font-size: 12px;
}

.info-strip__item strong {
    display: block;
    margin-top: 8px;
    color: var(--tf-text-primary);
    font-size: 13px;
    line-height: 1.6;
    word-break: break-all;
}

.dashboard-card :deep(.el-skeleton__item) {
    background: var(--tf-surface-soft);
}

.dashboard-card :deep(.el-progress-bar__outer) {
    background: var(--tf-surface-muted);
}

.dashboard-card :deep(.el-progress__text) {
    color: var(--tf-text-primary);
}

@media (max-width: 1100px) {
    .dashboard-metrics {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .info-strip {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}

@media (max-width: 900px) {
    .dashboard-hero,
    .dashboard-grid {
        grid-template-columns: 1fr;
        flex-direction: column;
        align-items: stretch;
    }
}

@media (max-width: 720px) {
    .dashboard-metrics {
        grid-template-columns: 1fr;
    }

    .info-strip {
        grid-template-columns: 1fr;
    }
}
</style>
