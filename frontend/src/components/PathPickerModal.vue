<script setup>
import { computed, nextTick, ref, watch } from 'vue';
import { Document, Folder } from '@element-plus/icons-vue';

import ResizableDrawer from './ResizableDrawer.vue';
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
const loadingMore = ref(false);
const browser = ref({ directories: [], datasources: [] });
const page = ref(1);
const pageSize = ref(100);
const total = ref(0);
const selectedPaths = ref([]);
const activePath = ref('');
const browserBodyRef = ref(null);

const canSelectCurrentFolder = computed(() => props.selectionMode === 'folder' && Boolean(currentPath.value));

const browserFiles = computed(() => (
    props.source === 'workspace'
        ? (browser.value?.files || [])
        : (browser.value?.datasources || [])
));

const filteredFiles = computed(() => {
    const extensions = props.allowedExtensions.map(item => String(item).toLowerCase());
    return browserFiles.value.filter(file => {
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

const parentPath = computed(() => {
    const parts = String(currentPath.value || '').split('/').filter(Boolean);
    if (!parts.length) {
        return '';
    }
    parts.pop();
    return parts.join('/');
});

const tableRows = computed(() => {
    const rows = [];
    (browser.value?.directories || []).forEach(dir => {
        rows.push({
            kind: 'directory',
            name: dir.name,
            path: dir.path || dir.name,
            typeLabel: '文件夹',
            sizeLabel: '-',
            modifiedLabel: formatModified(dir),
            selectable: props.selectionMode === 'folder'
        });
    });

    filteredFiles.value.forEach(file => {
        rows.push({
            kind: 'file',
            name: file.name,
            path: file.path || file.name,
            typeLabel: buildFileTypeLabel(file),
            sizeLabel: file.sizeFormatted || '-',
            modifiedLabel: formatModified(file),
            selectable: true
        });
    });

    return rows;
});

function syncSelection() {
    selectedPaths.value = normalizeListInput(props.currentValue);
}

const loadedCount = computed(() => tableRows.value.length);
const hasMore = computed(() => loadedCount.value < total.value);

function mergePagedRows(existingRows = [], incomingRows = []) {
    const seen = new Set(existingRows.map(item => item.path));
    const merged = [...existingRows];
    for (const item of incomingRows) {
        if (seen.has(item.path)) continue;
        seen.add(item.path);
        merged.push(item);
    }
    return merged;
}

async function ensureViewportFilled() {
    await nextTick();
    const container = browserBodyRef.value;
    if (!container || loading.value || loadingMore.value) return;

    let guard = 0;
    while (hasMore.value && container.scrollHeight <= container.clientHeight + 24 && guard < 3) {
        guard += 1;
        await loadMore();
        await nextTick();
    }
}

async function load(path = '', targetPage = 1, append = false) {
    if (append && (loading.value || loadingMore.value || !hasMore.value)) {
        return;
    }

    if (append) {
        loadingMore.value = true;
    } else {
        loading.value = true;
    }

    try {
        const response = props.source === 'workspace'
            ? await api.browseResults(path, { page: targetPage, pageSize: pageSize.value })
            : await api.browseDatasources(path, { page: targetPage, pageSize: pageSize.value });
        const data = response?.data || {};
        const directories = Array.isArray(data?.directories) ? data.directories : [];
        const datasources = Array.isArray(data?.datasources) ? data.datasources : [];
        const files = Array.isArray(data?.files) ? data.files : [];
        const totalEntries = Number(data?.totalEntries || 0);
        const currentFiles = props.source === 'workspace' ? files : datasources;

        if (targetPage > 1 && totalEntries > 0 && !directories.length && !currentFiles.length) {
            await load(path, 1, false);
            return;
        }

        browser.value = {
            ...data,
            directories: append ? mergePagedRows(browser.value?.directories || [], directories) : directories,
            datasources: props.source === 'datasource'
                ? (append ? mergePagedRows(browser.value?.datasources || [], datasources) : datasources)
                : [],
            files: props.source === 'workspace'
                ? (append ? mergePagedRows(browser.value?.files || [], files) : files)
                : []
        };
        currentPath.value = data?.currentPath || path || '';
        page.value = Number(data?.page || targetPage || 1);
        pageSize.value = Number(data?.pageSize || pageSize.value);
        total.value = totalEntries;
        activePath.value = '';
    } catch (error) {
        browser.value = { directories: [], datasources: [] };
        pushToast(`路径加载失败: ${error.message}`, 'error', 4500);
    } finally {
        loading.value = false;
        loadingMore.value = false;
    }

    await ensureViewportFilled();
}

function close() {
    emit('update:modelValue', false);
}

function clearSelection() {
    selectedPaths.value = [];
}

function formatModified(item) {
    if (!item) {
        return '-';
    }
    return item.modifiedTime || item.modifiedAt || item.lastModified || '-';
}

function buildFileTypeLabel(file) {
    const extension = String(file?.extension || '').trim().replace(/^\./, '').toUpperCase();
    if (extension) {
        return `${extension} 文件`;
    }
    return '文件';
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

function isActive(path) {
    return activePath.value === path;
}

function activateRow(item) {
    activePath.value = item.path || '';
    if (!item.selectable || !item.path) {
        return;
    }
    toggleSelection(item.path);
}

function openRow(item) {
    if (!item?.path) {
        return;
    }
    if (item.kind === 'directory') {
        load(item.path, 1);
    } else if (item.kind === 'file' && !props.multiple) {
        selectedPaths.value = [item.path];
    }
}

function goRoot() {
    load('', 1);
}

async function loadMore() {
    if (!hasMore.value || loading.value || loadingMore.value) return;
    await load(currentPath.value, page.value + 1, true);
}

function handleBrowserScroll() {
    const container = browserBodyRef.value;
    if (!container || loading.value || loadingMore.value) return;
    if (container.scrollTop + container.clientHeight >= container.scrollHeight - 140) {
        loadMore();
    }
}

function selectCurrentFolder() {
    if (!canSelectCurrentFolder.value) return;
    selectedPaths.value = [currentPath.value];
}

watch(() => props.modelValue, visible => {
    if (!visible) {
        return;
    }
    syncSelection();
    currentPath.value = '';
    load('', 1);
}, { immediate: true });

watch(() => props.currentValue, () => {
    if (props.modelValue) {
        syncSelection();
    }
});
</script>

<template>
    <ResizableDrawer
        :model-value="modelValue"
        :title="title"
        :subtitle="source === 'workspace' ? '结果目录' : '数据源目录'"
        :width="1040"
        :min-width="760"
        :max-width="1480"
        destroy-on-close
        @update:model-value="value => emit('update:modelValue', value)"
    >
        <div class="picker-head">
            <div class="picker-breadcrumb">
                <el-breadcrumb separator="/">
                    <el-breadcrumb-item>
                        <a href="#" @click.prevent="goRoot">根目录</a>
                    </el-breadcrumb-item>
                    <el-breadcrumb-item
                        v-for="item in breadcrumbs.slice(1)"
                        :key="item.path"
                    >
                        <a href="#" @click.prevent="load(item.path, 1)">{{ item.label }}</a>
                    </el-breadcrumb-item>
                </el-breadcrumb>
            </div>
            <div class="picker-toolbar-actions">
                <button class="picker-toolbar-button" type="button" :disabled="!currentPath" @click="load(parentPath, 1)">上一级</button>
                <button class="picker-toolbar-button" type="button" @click="load(currentPath, 1)">刷新</button>
                <button
                    v-if="canSelectCurrentFolder"
                    class="picker-toolbar-button picker-toolbar-button-primary"
                    type="button"
                    @click="selectCurrentFolder"
                >
                    选择当前目录
                </button>
            </div>
        </div>

        <div class="picker-location-strip">
            <div class="picker-location-bar">{{ currentPath || '/' }}</div>
            <div class="picker-location-meta">已加载 {{ loadedCount }} / {{ total }}</div>
        </div>

        <div v-if="selectedPaths.length" class="picker-selection-strip">
            <div class="picker-selection-strip-head">
                <strong>已选 {{ selectedPaths.length }} 项</strong>
                <button class="picker-link-button" type="button" @click="clearSelection">清空</button>
            </div>
            <div class="picker-selection-list">
                <div
                    v-for="path in selectedPaths"
                    :key="path"
                    class="picker-selection-item"
                >
                    <span>{{ path }}</span>
                    <button type="button" @click="toggleSelection(path)">移除</button>
                </div>
            </div>
        </div>

        <div class="picker-browser-frame">
            <div ref="browserBodyRef" class="picker-browser-body" @scroll.passive="handleBrowserScroll">
                <el-table
                    v-loading="loading"
                    :data="tableRows"
                    border
                    stripe
                    class="browser-table picker-browser-table"
                    empty-text="当前目录为空"
                >
                    <el-table-column label="名称" min-width="360">
                        <template #default="{ row }">
                            <button
                                type="button"
                                class="browser-name-button"
                                @click="row.kind === 'directory' ? load(row.path, 1) : activateRow(row)"
                                @dblclick.prevent="openRow(row)"
                            >
                                <el-icon class="browser-name-icon" :class="row.kind === 'directory' ? 'is-folder' : 'is-file'">
                                    <Folder v-if="row.kind === 'directory'" />
                                    <Document v-else />
                                </el-icon>
                                <span class="browser-name-copy">{{ row.name }}</span>
                            </button>
                        </template>
                    </el-table-column>
                    <el-table-column prop="typeLabel" label="类型" min-width="140" />
                    <el-table-column prop="sizeLabel" label="大小" min-width="140" />
                    <el-table-column label="操作" width="220" fixed="right">
                        <template #default="{ row }">
                            <div class="browser-table-actions">
                                <el-button
                                    v-if="row.kind === 'directory'"
                                    link
                                    @click="load(row.path, 1)"
                                >
                                    打开
                                </el-button>
                                <el-button
                                    v-if="row.selectable"
                                    link
                                    @click="toggleSelection(row.path)"
                                >
                                    {{ isSelected(row.path) ? '已选择' : '选择' }}
                                </el-button>
                            </div>
                        </template>
                    </el-table-column>
                </el-table>
                <div class="picker-load-status">
                    <span v-if="loadingMore">加载更多中...</span>
                    <span v-else-if="hasMore">继续下滑加载更多</span>
                    <span v-else-if="total > 0">已全部加载</span>
                </div>
            </div>
        </div>

        <template #footer>
            <div class="picker-window-footer">
                <div class="picker-footer-meta">
                    <span>已选 {{ selectedPaths.length }} 项</span>
                </div>
                <div class="picker-footer-actions">
                    <button class="btn btn-secondary" type="button" @click="close">取消</button>
                    <button class="btn btn-primary" type="button" @click="applySelection">确定</button>
                </div>
            </div>
        </template>
    </ResizableDrawer>
</template>

<style scoped>
.picker-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 12px;
}

.picker-breadcrumb {
    min-width: 0;
}

.picker-location-strip {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 12px;
    align-items: center;
    margin-bottom: 12px;
}

.picker-toolbar-actions {
    display: inline-flex;
    gap: 8px;
    flex-wrap: wrap;
}

.picker-toolbar-button {
    min-height: 32px;
    padding: 0 14px;
    border: 1px solid #c6cdd8;
    border-radius: 8px;
    background: linear-gradient(180deg, #ffffff 0%, #edf1f5 100%);
    color: #1f2937;
    cursor: pointer;
}

.picker-toolbar-button:hover:not(:disabled) {
    background: linear-gradient(180deg, #ffffff 0%, #e7edf5 100%);
    border-color: #9fb8dc;
}

.picker-toolbar-button:disabled {
    opacity: 0.45;
    cursor: not-allowed;
}

.picker-toolbar-button-primary {
    border-color: #8ab0e6;
    background: linear-gradient(180deg, #f7fbff 0%, #dbeafe 100%);
    color: #174ea6;
}

.picker-toolbar-button-primary:hover:not(:disabled) {
    background: linear-gradient(180deg, #ffffff 0%, #cfe3ff 100%);
}

.picker-location-bar {
    min-height: 34px;
    padding: 0 12px;
    display: flex;
    align-items: center;
    border: 1px solid #cfd6df;
    border-radius: 8px;
    background: #ffffff;
    color: #344054;
    font-size: 13px;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
}

.picker-location-meta {
    color: #667085;
    font-size: 12px;
}

.picker-selection-strip {
    padding: 12px 14px;
    border: 1px solid #d8dee7;
    border-radius: 10px;
    background: #ffffff;
    margin-bottom: 12px;
}

.picker-selection-strip-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 10px;
}

.picker-selection-strip-head strong {
    color: #111827;
    font-size: 13px;
}

.picker-link-button {
    padding: 0;
    border: 0;
    background: transparent;
    color: #2563eb;
    cursor: pointer;
}

.picker-selection-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
    max-height: 110px;
    overflow-y: auto;
}

.picker-selection-item {
    min-height: 34px;
    padding: 0 10px;
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 10px;
    align-items: center;
    border: 1px solid #d9e1ec;
    border-radius: 8px;
    background: #f8fafc;
}

.picker-selection-item span {
    min-width: 0;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    color: #344054;
    font-size: 12px;
}

.picker-selection-item button {
    border: 0;
    background: transparent;
    color: #667085;
    cursor: pointer;
}

.picker-browser-frame {
    border: 1px solid #d6dde7;
    border-radius: 10px;
    background: #ffffff;
    overflow: hidden;
}

.picker-browser-body {
    max-height: 520px;
    overflow-y: auto;
}

.picker-window-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 14px 18px 18px;
    border-top: 1px solid #d6dde6;
    background: linear-gradient(180deg, #f8fafc 0%, #eef2f6 100%);
}

.picker-footer-meta {
    display: flex;
    align-items: center;
    gap: 14px;
    color: #667085;
    font-size: 12px;
}

.picker-footer-actions {
    display: flex;
    align-items: center;
    gap: 10px;
}

.picker-window-footer :deep(.btn) {
    min-height: 34px;
    padding: 0 16px;
    border-radius: 8px;
    box-shadow: none;
    transform: none;
}

.picker-window-footer :deep(.btn-secondary) {
    border: 1px solid #c6cdd8;
    background: linear-gradient(180deg, #ffffff 0%, #edf1f5 100%);
    color: #344054;
}

.picker-window-footer :deep(.btn-secondary:hover) {
    border-color: #aeb9c7;
    background: linear-gradient(180deg, #ffffff 0%, #e6ecf3 100%);
}

.picker-window-footer :deep(.btn-primary) {
    border: 1px solid #8ab0e6;
    background: linear-gradient(180deg, #f7fbff 0%, #dbeafe 100%);
    color: #174ea6;
}

.picker-window-footer :deep(.btn-primary:hover) {
    border-color: #6d98db;
    background: linear-gradient(180deg, #ffffff 0%, #cfe3ff 100%);
}

.picker-window-header :deep(.message-close) {
    border: 1px solid #d5dbe4;
    border-radius: 8px;
    background: #ffffff;
    color: #475467;
    box-shadow: none;
}

.picker-window-header :deep(.message-close:hover) {
    border-color: #b9c6d6;
    background: #f3f6fa;
    color: #111827;
}

.picker-browser-table {
    border: 0;
}

.browser-name-button {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 12px;
    border: 0;
    background: transparent;
    padding: 0;
    min-height: 32px;
    text-align: left;
    cursor: pointer;
}

.browser-name-icon {
    font-size: 18px;
    flex: 0 0 auto;
}

.browser-name-icon.is-folder {
    color: #e6a23c;
}

.browser-name-icon.is-file {
    color: #5b8ff9;
}

.browser-name-copy {
    min-width: 0;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    color: #101828;
    font-weight: 600;
}

.browser-table-actions {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
}

.picker-load-status {
    padding: 12px 16px;
    display: flex;
    justify-content: flex-end;
    color: #667085;
    font-size: 12px;
    border-top: 1px solid #edf1f5;
    background: #ffffff;
}

@media (max-width: 900px) {
    .picker-head,
    .picker-location-strip {
        grid-template-columns: 1fr;
        display: grid;
    }
}

@media (max-width: 640px) {
    .picker-window-footer {
        flex-direction: column;
        align-items: stretch;
    }

    .picker-footer-actions {
        justify-content: flex-end;
    }
}
</style>
