<script setup>
import { computed, onMounted, ref, watch } from 'vue';

import { api } from '../services/api';
import { formatBytes } from '../utils/formatters';
import { pushToast } from '../composables/useToast';

const props = defineProps({
    activeSubsection: { type: String, default: 'systemUpdates' },
    standaloneMode: { type: Boolean, default: false }
});

const emit = defineEmits(['update:activeSubsection']);

const currentTab = ref(props.activeSubsection);
watch(() => props.activeSubsection, value => currentTab.value = value || 'systemUpdates');
watch(currentTab, value => {
    if (!props.standaloneMode) {
        emit('update:activeSubsection', value);
    }
});

const health = ref(null);
const systemInfo = ref(null);
const routes = ref([]);
const routeCurrentPage = ref(1);
const routePageSize = ref(10);
const routeTotal = ref(0);

async function loadHealth() {
    try {
        const [healthResponse, systemResponse] = await Promise.all([
            api.getHealth(),
            api.getSystemInfo()
        ]);
        health.value = healthResponse?.data || null;
        systemInfo.value = systemResponse?.data || null;
    } catch (error) {
        pushToast(`系统信息加载失败: ${error.message}`, 'error', 4500);
    }
}

async function loadRoutes() {
    try {
        const response = await api.getRoutes({
            page: routeCurrentPage.value,
            pageSize: routePageSize.value
        });
        const data = response?.data || {};
        routes.value = data.routes || [];
        routeTotal.value = Number(data.total || 0);
        routeCurrentPage.value = Number(data.page || routeCurrentPage.value);
        routePageSize.value = Number(data.pageSize || routePageSize.value);
    } catch (error) {
        pushToast(`路由加载失败: ${error.message}`, 'error', 4500);
    }
}

function handleRoutePageChange(page) {
    routeCurrentPage.value = page;
    loadRoutes();
}

function handleRoutePageSizeChange(size) {
    routePageSize.value = size;
    routeCurrentPage.value = 1;
    loadRoutes();
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
        <div v-if="!standaloneMode" class="view-subnav">
            <div class="subnav-tabs">
                <button class="subnav-tab" :class="{ active: currentTab === 'systemUpdates' }" type="button" @click="currentTab = 'systemUpdates'">系统更新</button>
                <button class="subnav-tab" :class="{ active: currentTab === 'systemRoutes' }" type="button" @click="currentTab = 'systemRoutes'">API 路由</button>
                <button class="subnav-tab" :class="{ active: currentTab === 'systemConfig' }" type="button" @click="currentTab = 'systemConfig'">系统配置</button>
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
                                <div class="card-body routes-list route-record-list">
                                    <div v-for="route in routes" :key="route.path" class="route-record-item">
                                        <div class="route-record-head">
                                            <code class="route-record-path">{{ route.path }}</code>
                                            <span class="route-record-category">{{ route.category }}</span>
                                        </div>
                                        <div class="route-record-methods">
                                            <span v-for="method in route.methods" :key="`${route.path}-${method}`" class="route-method-chip">{{ method }}</span>
                                        </div>
                                        <p class="route-record-description">{{ route.description || route.logic || '接口说明待补充' }}</p>
                                    </div>
                                    <div class="system-list-pagination soft-pagination">
                                        <el-pagination
                                            :current-page="routeCurrentPage"
                                            :page-size="routePageSize"
                                            :page-sizes="[10, 20, 50, 100]"
                                            :total="routeTotal"
                                            background
                                            layout="total, sizes, prev, pager, next, jumper"
                                            @current-change="handleRoutePageChange"
                                            @size-change="handleRoutePageSizeChange"
                                        />
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

<style scoped>
.system-list-pagination {
    display: flex;
    justify-content: flex-end;
    padding-top: 16px;
}

.route-record-list {
    display: flex;
    flex-direction: column;
    gap: 14px;
}

.route-record-item {
    padding: 18px 20px;
    border: 1px solid rgba(120, 150, 186, 0.14);
    border-radius: 18px;
    background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.02), transparent),
        linear-gradient(145deg, rgba(10, 19, 33, 0.92), rgba(8, 15, 27, 0.88));
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.03),
        0 10px 24px rgba(0, 0, 0, 0.14);
}

.route-record-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    margin-bottom: 12px;
}

.route-record-path {
    font-size: 14px;
    color: var(--tf-text);
    word-break: break-all;
}

.route-record-category {
    flex: 0 0 auto;
    padding: 6px 10px;
    border-radius: 999px;
    border: 1px solid rgba(103, 240, 255, 0.16);
    background: rgba(9, 25, 40, 0.7);
    color: var(--tf-text-soft);
    font-size: 12px;
}

.route-record-methods {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 12px;
}

.route-method-chip {
    min-width: 52px;
    padding: 5px 10px;
    border-radius: 999px;
    border: 1px solid rgba(120, 150, 186, 0.14);
    background: rgba(18, 34, 52, 0.76);
    color: #dbe9f6;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-align: center;
}

.route-record-description {
    margin: 0;
    color: var(--tf-text-soft);
    line-height: 1.7;
}

@media (max-width: 900px) {
    .route-record-head {
        flex-direction: column;
        align-items: flex-start;
    }
}
</style>
