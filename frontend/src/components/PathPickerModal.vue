<script setup>
import { computed, ref, watch } from 'vue';

import { api } from '../services/api';
import { pushToast } from '../composables/useToast';
import { normalizeListInput } from '../utils/formatters';

const props = defineProps({
    modelValue: { type: Boolean, required: true },
    title: { type: String, required: true },
    source: { type: String, default: 'datasource' },
    selectionMode: { type: String, default: 'file' },
    multiple: { type: Boolean, default: false },
    currentValue: { type: String, default: '' },
    allowedExtensions: { type: Array, default: () => [] },
    overlayClass: { type: String, default: '' }
});

const emit = defineEmits(['update:modelValue', 'apply']);

const currentPath = ref('');
const loading = ref(false);
const browser = ref({ directories: [], datasources: [] });
const selectedPaths = ref([]);

const canSelectCurrentFolder = computed(() => props.selectionMode === 'folder' && Boolean(currentPath.value));

const filteredFiles = computed(() => {
    const extensions = props.allowedExtensions.map(item => String(item).toLowerCase());
    return (browser.value?.datasources || []).filter(file => {
        if (props.selectionMode !== 'file') {
            return false;
        }
        if (!extensions.length) {
            return true;
        }
        const lowerName = String(file.name || file.path || '').toLowerCase();
        return extensions.some(ext => lowerName.endsWith(ext));
    });
});

const breadcrumbs = computed(() => {
    const parts = String(currentPath.value || '').split('/').filter(Boolean);
    const nodes = [{ label: '根目录', path: '' }];
    let acc = '';
    parts.forEach(part => {
        acc = acc ? `${acc}/${part}` : part;
        nodes.push({ label: part, path: acc });
    });
    return nodes;
});

function syncSelection() {
    selectedPaths.value = normalizeListInput(props.currentValue);
}

async function load(path = '') {
    loading.value = true;
    try {
        const response = props.source === 'workspace'
            ? await api.browseResults(path)
            : await api.browseDatasources(path);
        const data = response?.data || {};
        browser.value = data || { directories: [], datasources: [] };
        currentPath.value = data?.currentPath || path || '';
    } catch (error) {
        browser.value = { directories: [], datasources: [] };
        pushToast(`路径加载失败: ${error.message}`, 'error', 4500);
    } finally {
        loading.value = false;
    }
}

function close() {
    emit('update:modelValue', false);
}

function clearSelection() {
    selectedPaths.value = [];
}

function toggleSelection(path) {
    if (!path) return;
    if (props.multiple) {
        selectedPaths.value = selectedPaths.value.includes(path)
            ? selectedPaths.value.filter(item => item !== path)
            : [...selectedPaths.value, path];
        return;
    }
    selectedPaths.value = [path];
}

function applySelection() {
    emit('apply', [...selectedPaths.value]);
    close();
}

function isSelected(path) {
    return selectedPaths.value.includes(path);
}

watch(() => props.modelValue, visible => {
    if (!visible) {
        return;
    }
    syncSelection();
    currentPath.value = '';
    load('');
}, { immediate: true });

watch(() => props.currentValue, () => {
    if (props.modelValue) {
        syncSelection();
    }
});
</script>

<template>
    <Teleport to="body">
        <div v-if="modelValue" class="modal modal-overlay modal-overlay-active" :class="overlayClass" @click.self="close">
            <div class="modal-content picker-modal-content">
                <div class="modal-header">
                    <h3>{{ title }}</h3>
                    <button class="message-close" type="button" @click="close">×</button>
                </div>

                <div class="modal-body picker-modal-body">
                    <div class="picker-selection-panel">
                        <div class="picker-selection-header">
                            <strong>当前选择</strong>
                            <button class="btn btn-secondary" type="button" @click="clearSelection">清空</button>
                        </div>
                        <div v-if="selectedPaths.length" class="picker-chip-list">
                            <button
                                v-for="path in selectedPaths"
                                :key="path"
                                class="picker-chip"
                                type="button"
                                @click="toggleSelection(path)"
                            >
                                <span>{{ path }}</span>
                                <span aria-hidden="true">×</span>
                            </button>
                        </div>
                        <div v-else class="placeholder-text">还没有选择任何路径</div>
                    </div>

                    <div class="file-browser picker-browser-shell">
                        <div class="breadcrumb">
                            <span
                                v-for="(item, index) in breadcrumbs"
                                :key="item.path || 'root'"
                                class="breadcrumb-item"
                                :class="{ active: index === breadcrumbs.length - 1 }"
                                @click="load(item.path)"
                            >
                                {{ item.label }}
                            </span>
                        </div>

                        <div class="file-list picker-file-list">
                            <div v-if="loading" class="loading">加载中...</div>

                            <template v-else>
                                <div v-if="canSelectCurrentFolder" class="file-item picker-file-item picker-file-item-current">
                                    <div class="file-info">
                                        <div class="file-name">选择当前目录</div>
                                        <div class="file-details">{{ currentPath }}</div>
                                    </div>
                                    <div class="file-actions">
                                        <button
                                            class="btn btn-primary"
                                            type="button"
                                            @click="toggleSelection(currentPath)"
                                        >
                                            {{ isSelected(currentPath) ? '已选择' : '选择' }}
                                        </button>
                                    </div>
                                </div>

                                <div
                                    v-for="dir in browser.directories || []"
                                    :key="dir.path || dir.name"
                                    class="file-item picker-file-item"
                                >
                                    <div class="file-info" @click="load(dir.path || dir.name)">
                                        <div class="file-name">{{ dir.name }}</div>
                                        <div class="file-details">目录</div>
                                    </div>
                                    <div class="file-actions">
                                        <button class="btn btn-secondary" type="button" @click="load(dir.path || dir.name)">进入</button>
                                        <button
                                            v-if="selectionMode === 'folder'"
                                            class="btn btn-primary"
                                            type="button"
                                            @click="toggleSelection(dir.path || dir.name)"
                                        >
                                            {{ isSelected(dir.path || dir.name) ? '已选择' : '选择' }}
                                        </button>
                                    </div>
                                </div>

                                <div
                                    v-for="file in filteredFiles"
                                    :key="file.path || file.name"
                                    class="file-item picker-file-item"
                                >
                                    <div class="file-info">
                                        <div class="file-name">{{ file.name }}</div>
                                        <div class="file-details">{{ file.sizeFormatted || '文件' }}</div>
                                    </div>
                                    <div class="file-actions">
                                        <button
                                            class="btn btn-primary"
                                            type="button"
                                            @click="toggleSelection(file.path || file.name)"
                                        >
                                            {{ isSelected(file.path || file.name) ? '已选择' : '选择' }}
                                        </button>
                                    </div>
                                </div>

                                <div
                                    v-if="!(browser.directories || []).length && !filteredFiles.length && !canSelectCurrentFolder"
                                    class="message info"
                                >
                                    当前目录为空
                                </div>
                            </template>
                        </div>
                    </div>
                </div>

                <div class="modal-footer">
                    <button class="btn btn-secondary" type="button" @click="close">取消</button>
                    <button class="btn btn-primary" type="button" @click="applySelection">应用选择</button>
                </div>
            </div>
        </div>
    </Teleport>
</template>
