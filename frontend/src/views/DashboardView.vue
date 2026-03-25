<script setup>
import { computed, onMounted, ref } from 'vue';

import { api } from '../services/api';
import { formatBytes } from '../utils/formatters';
import { pushToast } from '../composables/useToast';

const health = ref(null);
const systemInfo = ref(null);
const tasks = ref([]);
const loading = ref(true);

const metrics = computed(() => {
    const taskStats = systemInfo.value?.tasks || {};
    return [
        { label: '总任务数', value: taskStats.total ?? tasks.value.length ?? 0 },
        { label: '运行中', value: taskStats.running ?? 0 },
        { label: '已完成', value: taskStats.completed ?? 0 },
        { label: '失败', value: taskStats.failed ?? 0 }
    ];
});

async function load() {
    loading.value = true;
    try {
        const [healthResponse, systemResponse, tasksResponse] = await Promise.all([
            api.getHealth(),
            api.getSystemInfo(),
            api.getAllTasks()
        ]);
        health.value = healthResponse;
        systemInfo.value = systemResponse;
        tasks.value = Object.values(tasksResponse?.tasks || {});
    } catch (error) {
        pushToast(`仪表盘加载失败: ${error.message}`, 'error', 4500);
    } finally {
        loading.value = false;
    }
}

onMounted(load);
</script>

<template>
    <section class="app-view">
        <div class="section-header">
            <div>
                <h2>系统仪表盘</h2>
                <!-- 从任务、资源与目录视角快速掌握 AtlasWorks 当前运行状态。 -->
                <p class="section-subtitle">从任务、资源与目录视角快速掌握 terra forge 当前运行状态。</p>
            </div>
            <div class="tool-actions">
                <button class="btn btn-secondary" type="button" @click="load">刷新</button>
            </div>
        </div>

        <div class="app-scroll">
            <div class="dashboard-container">
                <div class="overview-cards">
                    <div v-for="metric in metrics" :key="metric.label" class="overview-card">
                        <span class="card-value">{{ metric.value }}</span>
                        <span class="card-label">{{ metric.label }}</span>
                    </div>
                </div>

                <div class="system-panels">
                    <div class="system-panel">
                        <h3>服务健康</h3>
                        <div v-if="loading" class="loading">加载中...</div>
                        <div v-else class="info-list">
                            <div class="info-row">
                                <span class="info-label">服务状态</span>
                                <span class="info-value">{{ health?.status || '-' }}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">数据库</span>
                                <span class="info-value">{{ health?.database?.status || '-' }}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">运行中任务</span>
                                <span class="info-value">{{ health?.tasks?.running ?? 0 }}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">排队任务</span>
                                <span class="info-value">{{ health?.tasks?.queued ?? 0 }}</span>
                            </div>
                        </div>
                    </div>

                    <div class="system-panel">
                        <h3>资源概览</h3>
                        <div v-if="loading" class="loading">加载中...</div>
                        <div v-else class="info-list">
                            <div class="info-row">
                                <span class="info-label">CPU</span>
                                <span class="info-value">{{ systemInfo?.system?.cpuCount ?? '-' }} 核</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">总内存</span>
                                <span class="info-value">{{ formatBytes(systemInfo?.system?.memoryTotal) }}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">可用内存</span>
                                <span class="info-value">{{ formatBytes(systemInfo?.system?.memoryAvailable) }}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">磁盘占用</span>
                                <span class="info-value">{{ systemInfo?.system?.diskUsage ?? '-' }}%</span>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="product-grid product-grid-2">
                    <div class="card">
                        <div class="card-header">
                            <h3>目录与版本</h3>
                        </div>
                        <div class="card-body">
                            <div class="info-list">
                                <div class="info-row">
                                    <span class="info-label">版本</span>
                                    <span class="info-value">{{ systemInfo?.version || health?.version || '-' }}</span>
                                </div>
                                <div class="info-row">
                                    <span class="info-label">数据源目录</span>
                                    <span class="info-value">{{ systemInfo?.config?.dataSourceDir || '-' }}</span>
                                </div>
                                <div class="info-row">
                                    <span class="info-label">瓦片目录</span>
                                    <span class="info-value">{{ systemInfo?.config?.tilesDir || '-' }}</span>
                                </div>
                                <div class="info-row">
                                    <span class="info-label">最大线程</span>
                                    <span class="info-value">{{ systemInfo?.config?.maxThreads || '-' }}</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="card">
                        <div class="card-header">
                            <h3>目录挂载</h3>
                        </div>
                        <div class="card-body">
                            <div class="info-list">
                                <div class="info-row">
                                    <span class="info-label">宿主机数据源</span>
                                    <span class="info-value">{{ systemInfo?.config?.dataSourceHostDir || '未配置' }}</span>
                                </div>
                                <div class="info-row">
                                    <span class="info-label">宿主机瓦片</span>
                                    <span class="info-value">{{ systemInfo?.config?.tilesHostDir || '未配置' }}</span>
                                </div>
                                <div class="info-row">
                                    <span class="info-label">支持格式</span>
                                    <span class="info-value">{{ (systemInfo?.config?.supportedFormats || []).join(', ') || '-' }}</span>
                                </div>
                                <div class="info-row">
                                    <span class="info-label">更新时间</span>
                                    <span class="info-value">{{ health?.timestamp || '-' }}</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </section>
</template>
