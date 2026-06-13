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

async function updateContainer() {
    try {
        await api.updateContainer({ updateType: 'all' });
        pushToast('容器信息刷新完成', 'success');
        await loadHealth();
    } catch (error) {
        pushToast(`刷新失败: ${error.message}`, 'error', 4500);
    }
}

onMounted(loadHealth);

const currentLabel = computed(() => {
    if (currentTab.value === 'systemRoutes') return 'API 文档';
    return '系统更新';
});

const docsUrl = computed(() => {
    const loc = window.location;
    // 动态取当前浏览器端口，避免与实际访问端口不一致
    const port = loc.port || (loc.protocol === 'https:' ? '443' : '80');
    return `${loc.protocol}//${loc.hostname}:${port}/api/docs`;
});
</script>

<template>
    <section class="app-view standard-page">
        <div class="page-banner">
            <div class="page-banner__meta">
                <div class="page-banner__title">{{ currentLabel }}</div>
                <div class="page-banner__desc">集中查看平台健康、接口文档与运行配置，支撑服务巡检、问题定位与运维决策。</div>
            </div>
        </div>

        <div class="app-scroll">
            <el-card v-if="currentTab === 'systemUpdates'" class="standard-panel" shadow="never">
                <template #header>
                    <div class="standard-card-head">
                        <span>服务状态</span>
                        <el-button type="primary" @click="updateContainer">刷新容器信息</el-button>
                    </div>
                </template>
                <el-descriptions :column="1" direction="vertical" border>
                    <el-descriptions-item label="服务">{{ health?.status || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="数据库">{{ health?.database?.status || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="版本">{{ health?.version || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="数据源目录">{{ systemInfo?.config?.dataSourceDir || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="瓦片目录">{{ systemInfo?.config?.tilesDir || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="总内存">{{ formatBytes(systemInfo?.system?.memoryTotal) }}</el-descriptions-item>
                </el-descriptions>
            </el-card>

            <div v-else class="docs-embed-container">
                <iframe
                    :src="docsUrl"
                    class="docs-embed-frame"
                    frameborder="0"
                    allow="clipboard-write"
                />
            </div>
        </div>
    </section>
</template>

<style scoped>
.page-banner {
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

.standard-panel {
    border-radius: 12px;
}

.standard-card-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    font-weight: 600;
    color: var(--tf-text-primary);
}

.docs-embed-container {
    flex: 1;
    min-height: 0;
    display: flex;
    border: 1px solid var(--tf-border);
    border-radius: 10px;
    overflow: hidden;
    background: var(--tf-surface);
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}

.docs-embed-frame {
    flex: 1;
    width: 100%;
    min-height: 0;
    border: none;
}

.app-scroll {
    display: flex;
    flex-direction: column;
}

.standard-panel :deep(.el-card__header) {
    background: var(--tf-surface);
    border-bottom: 1px solid var(--tf-border);
}

.standard-panel :deep(.el-descriptions__label) {
    background: var(--tf-surface-soft);
    color: var(--tf-text-secondary);
    width: 160px;
}

.standard-panel :deep(.el-descriptions__content) {
    color: var(--tf-text-primary);
    background: var(--tf-surface);
}
</style>
