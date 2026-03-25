<script setup>
import { computed, onMounted, ref, watch } from 'vue';

import { api } from '../services/api';
import { formatBytes } from '../utils/formatters';
import { pushToast } from '../composables/useToast';

const props = defineProps({
    activeSubsection: { type: String, required: true }
});

const emit = defineEmits(['update:activeSubsection']);

const currentTab = ref(props.activeSubsection);
watch(() => props.activeSubsection, value => currentTab.value = value);
watch(currentTab, value => emit('update:activeSubsection', value));

const health = ref(null);
const systemInfo = ref(null);
const routes = ref([]);

async function loadHealth() {
    try {
        health.value = await api.getHealth();
        systemInfo.value = await api.getSystemInfo();
    } catch (error) {
        pushToast(`系统信息加载失败: ${error.message}`, 'error', 4500);
    }
}

async function loadRoutes() {
    try {
        const response = await api.getRoutes();
        routes.value = response?.routes || [];
    } catch (error) {
        pushToast(`路由加载失败: ${error.message}`, 'error', 4500);
    }
}

async function updateContainer() {
    try {
        await api.updateContainer({ updateType: 'all' });
        pushToast('容器信息刷新完成', 'success');
        await loadHealth();
    } catch (error) {
        pushToast(`刷新失败: ${error.message}`, 'error', 4500);
    }
}

onMounted(async () => {
    await Promise.all([loadHealth(), loadRoutes()]);
});

const currentLabel = computed(() => {
    if (currentTab.value === 'systemRoutes') return 'API 路由';
    if (currentTab.value === 'systemConfig') return '系统配置';
    return '系统更新';
});
</script>

<template>
    <section class="app-view">
        <div class="section-header section-header-product">
            <div>
                <h2>{{ currentLabel }}</h2>
                <p class="section-subtitle">集中查看平台健康、接口清单与运行配置，支撑服务巡检、问题定位与运维决策。</p>
            </div>
        </div>

        <div class="app-scroll">
            <div class="content-stack content-stack-system">
                <div v-if="currentTab === 'systemUpdates'" class="system-block active">
                            <div class="card">
                                <div class="card-header">
                                    <h3>服务状态</h3>
                                </div>
                                <div class="card-body">
                                    <div class="info-list">
                                        <div class="info-row"><span class="info-label">服务</span><span class="info-value">{{ health?.status || '-' }}</span></div>
                                        <div class="info-row"><span class="info-label">数据库</span><span class="info-value">{{ health?.database?.status || '-' }}</span></div>
                                        <div class="info-row"><span class="info-label">版本</span><span class="info-value">{{ health?.version || '-' }}</span></div>
                                    </div>
                                    <div class="tool-actions">
                                        <button class="btn btn-primary" type="button" @click="updateContainer">刷新容器信息</button>
                                    </div>
                                </div>
                            </div>
                </div>

                <div v-else-if="currentTab === 'systemRoutes'" class="system-block active">
                            <div class="card">
                                <div class="card-header"><h3>接口清单</h3></div>
                                <div class="card-body routes-list">
                                    <div v-for="route in routes" :key="route.path" class="info-row">
                                        <span class="info-label">{{ route.path }}</span>
                                        <span class="info-value">{{ route.methods.join(', ') }} / {{ route.category }}</span>
                                    </div>
                                </div>
                            </div>
                </div>

                <div v-else class="system-block active">
                            <div class="card">
                                <div class="card-header"><h3>系统配置</h3></div>
                                <div class="card-body">
                                    <div class="info-list">
                                        <div class="info-row"><span class="info-label">数据源目录</span><span class="info-value">{{ systemInfo?.config?.dataSourceDir || '-' }}</span></div>
                                        <div class="info-row"><span class="info-label">瓦片目录</span><span class="info-value">{{ systemInfo?.config?.tilesDir || '-' }}</span></div>
                                        <div class="info-row"><span class="info-label">总内存</span><span class="info-value">{{ formatBytes(systemInfo?.system?.memoryTotal) }}</span></div>
                                        <div class="info-row"><span class="info-label">支持格式</span><span class="info-value">{{ (systemInfo?.config?.supportedFormats || []).join(', ') || '-' }}</span></div>
                                    </div>
                                </div>
                            </div>
                </div>
            </div>
        </div>
    </section>
</template>
