<script setup>
import { computed, nextTick, ref, watch } from 'vue';

const props = defineProps({
    tabs: { type: Array, required: true },
    activeKey: { type: String, required: true }
});

const emit = defineEmits(['tab-change', 'tab-remove', 'close-all']);

const scrollRef = ref(null);

const hasClosable = computed(() => props.tabs.some(t => t.closable));

function selectTab(key) {
    if (key !== props.activeKey) emit('tab-change', key);
}

function closeTab(e, key) {
    e.stopPropagation();
    emit('tab-remove', key);
}

function closeAll() {
    emit('close-all');
}

watch(() => props.activeKey, async () => {
    await nextTick();
    const el = scrollRef.value?.querySelector?.(`[data-tab-key="${props.activeKey}"]`);
    el?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
});
</script>

<template>
    <div class="tab-bar">
        <div ref="scrollRef" class="tab-bar__scroll">
            <div class="tab-bar__list">
                <button
                    v-for="tab in tabs"
                    :key="tab.key"
                    :data-tab-key="tab.key"
                    :class="['tab-bar__item', { 'tab-bar__item--active': tab.key === activeKey }]"
                    type="button"
                    @click="selectTab(tab.key)"
                >
                    <span class="tab-bar__label">{{ tab.label }}</span>
                    <span
                        v-if="tab.closable"
                        class="tab-bar__close"
                        role="button"
                        :aria-label="`关闭 ${tab.label}`"
                        @click="closeTab($event, tab.key)"
                    >×</span>
                </button>
            </div>
        </div>
        <button
            v-if="hasClosable"
            class="tab-bar__close-all"
            type="button"
            title="关闭所有可关闭标签"
            @click="closeAll"
        >关闭全部</button>
    </div>
</template>

<style scoped>
.tab-bar {
    display: flex;
    align-items: stretch;
    gap: 8px;
    min-height: 36px;
    flex-shrink: 0;
}

.tab-bar__scroll {
    flex: 1;
    min-width: 0;
    overflow-x: auto;
    overflow-y: hidden;
    scrollbar-width: none;
}
.tab-bar__scroll::-webkit-scrollbar { display: none; }

.tab-bar__list {
    display: flex;
    align-items: stretch;
    gap: 4px;
    min-width: max-content;
    height: 36px;
}

.tab-bar__item {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 36px;
    padding: 0 14px;
    border: 1px solid #e4e7ed;
    border-radius: 8px 8px 0 0;
    background: #f5f7fa;
    color: #606266;
    font-size: 13px;
    cursor: pointer;
    white-space: nowrap;
    transition: background 0.15s, color 0.15s, border-color 0.15s;
    position: relative;
    bottom: -1px;
}

.tab-bar__item:hover {
    background: #ecf5ff;
    color: #409eff;
    border-color: #c6e2ff;
}

.tab-bar__item--active {
    background: #ffffff;
    color: #303133;
    border-color: #e4e7ed;
    border-bottom-color: #ffffff;
    font-weight: 600;
    z-index: 1;
}

.tab-bar__label {
    max-width: 140px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.tab-bar__close {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    font-size: 14px;
    line-height: 1;
    color: #c0c4cc;
    flex-shrink: 0;
    transition: background 0.15s, color 0.15s;
}
.tab-bar__close:hover {
    background: #f56c6c;
    color: #fff;
}

.tab-bar__close-all {
    flex-shrink: 0;
    align-self: center;
    height: 28px;
    padding: 0 12px;
    border: 1px solid #dcdfe6;
    border-radius: 6px;
    background: #fff;
    color: #909399;
    font-size: 12px;
    cursor: pointer;
    white-space: nowrap;
    transition: all 0.2s ease;
}
.tab-bar__close-all:hover {
    border-color: #f56c6c;
    color: #f56c6c;
    background: #fef0f0;
}
</style>
