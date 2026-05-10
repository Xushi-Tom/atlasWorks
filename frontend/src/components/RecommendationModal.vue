<script setup>
import { computed } from 'vue';
import ResizableDrawer from './ResizableDrawer.vue';

const props = defineProps({
    modelValue: { type: Boolean, required: true },
    type: { type: String, required: true },
    sourceFile: { type: String, default: '' },
    recommendationData: { type: Object, default: null }
});

const emit = defineEmits(['update:modelValue', 'apply']);

const title = computed(() => props.type === 'terrain' ? '地形切片' : '地图切片');

const items = computed(() => {
    const recommendations = props.recommendationData?.recommendations || {};
    const definitions = [
        ['minZoom', '最小缩放级别'],
        ['maxZoom', '最大缩放级别'],
        ['processes', '进程数'],
        ['maxMemory', '最大内存'],
        ['tileFormat', '瓦片格式'],
        ['quality', '质量'],
        ['resampling', '重采样方法'],
        ['compression', '压缩'],
        ['decompress', '解压'],
        ['autoZoom', '智能分级'],
        ['zoomStrategy', '分级策略'],
        ['optimizeFile', '文件优化'],
        ['createOverview', '创建概览'],
        ['useOptimizedMode', '优化模式']
    ];

    return definitions
        .filter(([key]) => recommendations[key] !== undefined)
        .map(([key, label]) => ({
            key,
            label,
            value: typeof recommendations[key] === 'boolean'
                ? (recommendations[key] ? '是' : '否')
                : recommendations[key]
        }));
});

function close() {
    emit('update:modelValue', false);
}

function applyRecommendation() {
    emit('apply', props.recommendationData?.recommendations || {});
    close();
}
</script>

<template>
    <ResizableDrawer
        :model-value="modelValue"
        :title="`智能推荐配置 - ${title}`"
        :width="560"
        :min-width="420"
        :max-width="820"
        destroy-on-close
        @update:model-value="value => emit('update:modelValue', value)"
    >
        <div class="info-list">
            <div class="info-row">
                <span class="info-label">文件</span>
                <span class="info-value">{{ sourceFile || '-' }}</span>
            </div>
            <div class="info-row">
                <span class="info-label">文件大小</span>
                <span class="info-value">
                    {{ recommendationData?.fileSize ? `${recommendationData.fileSize.toFixed(2)} GB` : '-' }}
                </span>
            </div>
            <div class="info-row">
                <span class="info-label">系统信息</span>
                <span class="info-value">
                    {{
                        recommendationData?.systemInfo
                            ? `CPU ${recommendationData.systemInfo.cpuCount || '-'} 核 / 内存 ${
                                typeof recommendationData.systemInfo.memoryTotalGb === 'number'
                                    ? recommendationData.systemInfo.memoryTotalGb.toFixed(1)
                                    : '-'
                            } GB`
                            : '-'
                    }}
                </span>
            </div>
        </div>

        <div class="recommendation-list recommendation-list-vue">
            <div v-for="item in items" :key="item.key" class="recommendation-item">
                <strong>{{ item.label }}</strong>
                <span>{{ item.value }}</span>
            </div>
        </div>

        <template #footer>
            <button class="btn btn-secondary" type="button" @click="close">关闭</button>
            <button class="btn btn-primary" type="button" @click="applyRecommendation">应用推荐</button>
        </template>
    </ResizableDrawer>
</template>
