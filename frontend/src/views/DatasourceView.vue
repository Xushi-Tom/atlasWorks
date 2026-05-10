<script setup>
import { computed, nextTick, onMounted, ref } from 'vue';
import { Document, Folder } from '@element-plus/icons-vue';

import ResizableDrawer from '../components/ResizableDrawer.vue';
import { api } from '../services/api';
import { formatBytes, formatDateTime } from '../utils/formatters';
import { pushToast } from '../composables/useToast';

const ARCHIVE_EXTENSIONS = ['.zip', '.tar', '.tgz', '.tar.gz', '.tar.bz2', '.tbz2', '.tar.xz', '.txz', '.7z'];

const currentPath = ref('');
const browser = ref({ directories: [], datasources: [] });
const page = ref(1);
const pageSize = ref(100);
const total = ref(0);
const loading = ref(false);
const loadingMore = ref(false);
const appScrollRef = ref(null);
const selectedFile = ref(null);
const detailVisible = ref(false);
const importVisible = ref(false);
const folderVisible = ref(false);
const previewLoadFailed = ref(false);
const newFolderName = ref('');
const importState = ref({
    overwrite: false
});
const importResult = ref('');
const singleInput = ref(null);

const rows = computed(() => {
    const directories = (browser.value?.directories || []).map(item => ({
        ...item,
        entryType: 'directory',
        displayType: '文件夹',
        displaySize: '-'
    }));
    const files = (browser.value?.datasources || []).map(item => ({
        ...item,
        entryType: 'file',
        displayType: String(item.extension || '').replace(/^\./, '').toUpperCase() || '文件',
        displaySize: item.sizeFormatted || formatBytes(item.size)
    }));
    return [...directories, ...files];
});

const breadcrumbSegments = computed(() => {
    const segments = String(currentPath.value || '')
        .split('/')
        .filter(Boolean);

    return segments.map((segment, index) => ({
        label: segment,
        path: segments.slice(0, index + 1).join('/')
    }));
});

function isArchiveName(name = '') {
    const lower = String(name || '').toLowerCase();
    return ARCHIVE_EXTENSIONS.some(ext => lower.endsWith(ext));
}

const loadedCount = computed(() => rows.value.length);
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
    const container = appScrollRef.value;
    if (!container || loading.value || loadingMore.value) return;

    let guard = 0;
    while (hasMore.value && container.scrollHeight <= container.clientHeight + 24 && guard < 3) {
        guard += 1;
        await loadMore();
        await nextTick();
    }
}

async function loadLibrary(path = currentPath.value, targetPage = 1, append = false) {
    if (append && (loading.value || loadingMore.value || !hasMore.value)) {
        return;
    }

    if (append) {
        loadingMore.value = true;
    } else {
        loading.value = true;
    }

    try {
        const response = await api.browseDatasources(path, {
            page: targetPage,
            pageSize: pageSize.value
        });
        const data = response?.data || {};
        const directories = Array.isArray(data?.directories) ? data.directories : [];
        const datasources = Array.isArray(data?.datasources) ? data.datasources : [];
        const totalEntries = Number(data?.totalEntries || 0);
        if (targetPage > 1 && totalEntries > 0 && !directories.length && !datasources.length) {
            await loadLibrary(path, 1, false);
            return;
        }

        const mergedDirectories = append
            ? mergePagedRows(browser.value?.directories || [], directories)
            : directories;
        const mergedDatasources = append
            ? mergePagedRows(browser.value?.datasources || [], datasources)
            : datasources;

        browser.value = {
            ...data,
            directories: mergedDirectories,
            datasources: mergedDatasources
        };
        currentPath.value = data?.currentPath || path || '';
        page.value = Number(data?.page || targetPage || 1);
        pageSize.value = Number(data?.pageSize || pageSize.value);
        total.value = totalEntries;
    } catch (error) {
        if (!append) {
            browser.value = { directories: [], datasources: [] };
        }
        pushToast(`数据源加载失败: ${error.message}`, 'error', 4500);
    } finally {
        loading.value = false;
        loadingMore.value = false;
    }

    await ensureViewportFilled();
}

async function loadMore() {
    if (!hasMore.value || loading.value || loadingMore.value) return;
    await loadLibrary(currentPath.value, page.value + 1, true);
}

function handleBrowserScroll() {
    const container = appScrollRef.value;
    if (!container || loading.value || loadingMore.value) return;
    if (container.scrollTop + container.clientHeight >= container.scrollHeight - 140) {
        loadMore();
    }
}

async function showFileDetails(file) {
    try {
        const response = await api.getDatasourceInfo(file.path);
        selectedFile.value = response?.data || null;
        previewLoadFailed.value = false;
        detailVisible.value = true;
    } catch (error) {
        pushToast(`获取文件详情失败: ${error.message}`, 'error', 4500);
    }
}

function closeDetailModal() {
    detailVisible.value = false;
    previewLoadFailed.value = false;
}

function resolvePreviewUrl(fileInfo) {
    const previewUrl = String(fileInfo?.previewUrl || '').trim();
    if (previewUrl) {
        return previewUrl.startsWith('http') ? previewUrl : `${window.location.origin}${previewUrl}`;
    }
    const extension = String(fileInfo?.extension || '').toLowerCase();
    if (extension === '.png' || extension === '.jpg' || extension === '.jpeg') {
        return api.getDatasourceFileUrl(fileInfo?.path || '');
    }
    return '';
}

function openImportModal() {
    importState.value.overwrite = false;
    importResult.value = '';
    importVisible.value = true;
}

function closeImportModal() {
    importVisible.value = false;
}

function openFolderModal() {
    newFolderName.value = '';
    folderVisible.value = true;
}

function closeFolderModal() {
    folderVisible.value = false;
}

function triggerSingleUpload() {
    singleInput.value?.click();
}

async function handleSingleUpload(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    importResult.value = '上传中...';
    try {
        const response = await api.uploadDataSourceFile(file, currentPath.value, importState.value.overwrite);
        importResult.value = response?.message || '导入完成';
        pushToast(importResult.value, 'success');
        await loadLibrary(currentPath.value, 1, false);
        importVisible.value = false;
    } catch (error) {
        importResult.value = error.message;
        pushToast(`导入失败: ${error.message}`, 'error', 5000);
    } finally {
        event.target.value = '';
    }
}

async function createFolder() {
    const name = String(newFolderName.value || '').trim();
    if (!name) {
        pushToast('请输入文件夹名称', 'warning');
        return;
    }
    try {
        const folderPath = currentPath.value ? `${currentPath.value}/${name}` : name;
        await api.createDatasourceFolder(folderPath);
        pushToast('数据源文件夹创建成功', 'success');
        folderVisible.value = false;
        await loadLibrary(currentPath.value, 1, false);
    } catch (error) {
        pushToast(`创建文件夹失败: ${error.message}`, 'error', 5000);
    }
}

function navigateToRoot() {
    loadLibrary('', 1);
}

function navigateUp() {
    if (!currentPath.value) return;
    const parentPath = currentPath.value.includes('/') ? currentPath.value.split('/').slice(0, -1).join('/') : '';
    loadLibrary(parentPath, 1);
}

async function deleteItem(item, type) {
    const label = type === 'directory' ? '目录' : '文件';
    if (!window.confirm(`确认删除${label}“${item.name}”吗？该操作不可恢复。`)) return;
    try {
        if (type === 'directory') {
            await api.deleteDatasourceFolder(item.path);
        } else {
            await api.deleteDatasourceFile(item.path);
        }
        pushToast(`${label}删除成功`, 'success');
        await loadLibrary(currentPath.value, 1, false);
    } catch (error) {
        pushToast(`删除${label}失败: ${error.message}`, 'error', 5000);
    }
}

async function extractArchive(file) {
    if (!window.confirm(`确认解压“${file.name}”到当前目录吗？`)) return;
    const extractFolderName = window.prompt('解压后文件夹名称（可选，留空使用默认）', '');
    if (extractFolderName === null) return;
    try {
        await api.extractArchive(file.path, 'datasource', false, extractFolderName);
        pushToast('压缩文件解压完成', 'success');
        await loadLibrary(currentPath.value, 1, false);
    } catch (error) {
        pushToast(`解压失败: ${error.message}`, 'error', 5000);
    }
}

onMounted(async () => {
    await loadLibrary('', 1, false);
});
</script>

<template>
    <section class="app-view standard-page">
        <div class="page-banner">
            <div class="page-banner__meta">
                <div class="page-banner__title">数据源管理</div>
                <div class="page-banner__desc">直接围绕当前目录完成浏览、定位、查看与导入，不把高频操作拆散到额外页面。</div>
            </div>
        </div>

        <div ref="appScrollRef" class="app-scroll" @scroll.passive="handleBrowserScroll">
            <div class="content-stack">
                <el-card class="standard-panel" shadow="never">
                    <template #header>
                        <div class="standard-browser-head">
                            <div class="standard-browser-breadcrumb">
                                <el-breadcrumb separator="/">
                                    <el-breadcrumb-item>
                                        <a href="#" @click.prevent="navigateToRoot">根目录</a>
                                    </el-breadcrumb-item>
                                    <el-breadcrumb-item
                                        v-for="segment in breadcrumbSegments"
                                        :key="segment.path"
                                    >
                                        <a href="#" @click.prevent="loadLibrary(segment.path, 1)">{{ segment.label }}</a>
                                    </el-breadcrumb-item>
                                </el-breadcrumb>
                            </div>
                            <div class="tool-actions">
                                <el-button v-if="currentPath" @click="navigateUp">上一级</el-button>
                                <el-button @click="loadLibrary(currentPath, 1, false)">刷新</el-button>
                                <el-button @click="openFolderModal">新建文件夹</el-button>
                                <el-button type="primary" @click="openImportModal">导入到当前目录</el-button>
                            </div>
                        </div>
                    </template>
                    <el-table v-loading="loading" :data="rows" border stripe class="browser-table" empty-text="当前目录为空">
                        <el-table-column label="名称" min-width="360">
                            <template #default="{ row }">
                                <button
                                    v-if="row.entryType === 'directory'"
                                    type="button"
                                    class="browser-name-button"
                                    @click="loadLibrary(row.path, 1)"
                                >
                                    <el-icon class="browser-name-icon is-folder"><Folder /></el-icon>
                                    <span class="browser-name-copy">{{ row.name }}</span>
                                </button>
                                <button
                                    v-else
                                    type="button"
                                    class="browser-name-button"
                                    @click="showFileDetails(row)"
                                >
                                    <el-icon class="browser-name-icon is-file"><Document /></el-icon>
                                    <span class="browser-name-copy">{{ row.name }}</span>
                                </button>
                            </template>
                        </el-table-column>
                        <el-table-column prop="displayType" label="类型" min-width="140" />
                        <el-table-column prop="displaySize" label="大小" min-width="140" />
                        <el-table-column label="操作" width="220" fixed="right">
                            <template #default="{ row }">
                                <div class="browser-table-actions">
                                    <el-button
                                        v-if="row.entryType === 'directory'"
                                        link
                                        @click="loadLibrary(row.path, 1)"
                                    >
                                        打开
                                    </el-button>
                                    <el-button
                                        v-else
                                        link
                                        @click="showFileDetails(row)"
                                    >
                                        详情
                                    </el-button>
                                    <el-button
                                        v-if="row.entryType === 'file' && isArchiveName(row.name)"
                                        link
                                        @click="extractArchive(row)"
                                    >
                                        解压
                                    </el-button>
                                    <el-button
                                        type="danger"
                                        link
                                        @click="deleteItem(row, row.entryType)"
                                    >
                                        删除
                                    </el-button>
                                </div>
                            </template>
                        </el-table-column>
                    </el-table>
                    <div class="browser-load-status">
                        <span>已加载 {{ loadedCount }} / {{ total }}</span>
                        <span v-if="loadingMore">加载更多中...</span>
                        <span v-else-if="hasMore">继续下滑加载更多</span>
                        <span v-else-if="total > 0">已全部加载</span>
                    </div>
                </el-card>
            </div>
        </div>

        <ResizableDrawer v-model="detailVisible" title="文件详情" :width="920" :min-width="560" :max-width="1320" destroy-on-close @closed="closeDetailModal">
            <div v-if="selectedFile" class="standard-detail-stack">
                <div v-if="resolvePreviewUrl(selectedFile)" class="datasource-preview-card">
                    <div class="datasource-preview-head">图片预览</div>
                    <div class="datasource-preview-frame">
                        <img
                            v-if="!previewLoadFailed"
                            :src="resolvePreviewUrl(selectedFile)"
                            :alt="selectedFile.name || 'preview'"
                            class="datasource-preview-image"
                            @error="previewLoadFailed = true"
                        >
                        <div v-else class="placeholder-text">图片预览加载失败</div>
                    </div>
                </div>
                <el-descriptions :column="1" direction="vertical" border>
                    <el-descriptions-item label="文件名">{{ selectedFile.name || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="路径">{{ selectedFile.path || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="格式">{{ selectedFile.format || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="大小">{{ selectedFile.sizeFormatted || formatBytes(selectedFile.size) }}</el-descriptions-item>
                    <el-descriptions-item label="更新时间">{{ formatDateTime(selectedFile.lastModified || selectedFile.modifiedTime) }}</el-descriptions-item>
                    <el-descriptions-item label="波段数">{{ selectedFile.metadata?.bandCount ?? '-' }}</el-descriptions-item>
                    <el-descriptions-item label="栅格尺寸">{{ selectedFile.metadata?.rasterSize?.width ?? '-' }} × {{ selectedFile.metadata?.rasterSize?.height ?? '-' }}</el-descriptions-item>
                    <el-descriptions-item label="投影">{{ selectedFile.metadata?.srs || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="驱动">{{ selectedFile.metadata?.driverLongName || selectedFile.metadata?.driver || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="数据类型">{{ selectedFile.metadata?.dataType || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="NoData">{{ selectedFile.metadata?.nodata ?? '-' }}</el-descriptions-item>
                    <el-descriptions-item label="压缩">{{ selectedFile.metadata?.compression || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="地理范围">
                        {{ selectedFile.geoBounds ? `${selectedFile.geoBounds.west}, ${selectedFile.geoBounds.south}, ${selectedFile.geoBounds.east}, ${selectedFile.geoBounds.north}` : '-' }}
                    </el-descriptions-item>
                </el-descriptions>
            </div>
        </ResizableDrawer>

        <ResizableDrawer v-model="importVisible" title="导入到当前目录" :width="520" :min-width="420" :max-width="760" destroy-on-close @closed="closeImportModal">
            <el-form label-width="100px">
                <el-form-item label="覆盖同名">
                    <el-switch v-model="importState.overwrite" />
                </el-form-item>
                <el-form-item>
                    <el-button type="primary" @click="triggerSingleUpload">选择单文件</el-button>
                </el-form-item>
                <input ref="singleInput" hidden type="file" accept=".tif,.tiff,.zip,.tar,.tgz,.tar.gz,.7z,.txt,.png,.jpg,.jpeg" @change="handleSingleUpload">
                <el-alert
                    :title="importResult || '文件会直接上传到当前目录，压缩包上传后可在列表中单独执行解压。'"
                    type="info"
                    :closable="false"
                    show-icon
                />
            </el-form>
        </ResizableDrawer>

        <ResizableDrawer v-model="folderVisible" title="新建数据源文件夹" :width="520" :min-width="420" :max-width="760" destroy-on-close @closed="closeFolderModal">
            <el-form label-width="100px">
                <el-form-item label="文件夹名称">
                    <el-input v-model="newFolderName" placeholder="例如 raw/project-a" />
                </el-form-item>
            </el-form>
            <template #footer>
                <el-button @click="closeFolderModal">取消</el-button>
                <el-button type="primary" @click="createFolder">创建</el-button>
            </template>
        </ResizableDrawer>
    </section>
</template>

<style scoped>
.page-banner {
    padding: 20px 22px;
    border: 1px solid #e5eaf3;
    border-radius: 16px;
    background: linear-gradient(180deg, #ffffff 0%, #f9fbfe 100%);
}

.page-banner__title {
    color: #1f2d3d;
    font-size: 18px;
    font-weight: 700;
}

.page-banner__desc {
    margin-top: 6px;
    color: #6b7280;
    font-size: 13px;
    line-height: 1.7;
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

.browser-load-status {
    margin-top: 16px;
    display: flex;
    justify-content: flex-end;
    gap: 16px;
    color: #667085;
    font-size: 13px;
}
</style>
