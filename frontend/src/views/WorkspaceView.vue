<script setup>
import { computed, nextTick, onMounted, ref } from 'vue';
import { ElMessageBox } from 'element-plus';
import { Document, Folder } from '@element-plus/icons-vue';

import ResizableDrawer from '../components/ResizableDrawer.vue';
import { api } from '../services/api';
import { formatBytes, formatDateTime } from '../utils/formatters';
import { pushToast } from '../composables/useToast';
import { setNavigationIntent } from '../utils/navigationIntent';

const emit = defineEmits(['navigate']);

const ARCHIVE_EXTENSIONS = ['.zip', '.tar', '.tgz', '.tar.gz', '.tar.bz2', '.tbz2', '.tar.xz', '.txz', '.7z'];

const browser = ref({ directories: [], files: [] });
const currentPath = ref('');
const page = ref(1);
const pageSize = ref(100);
const total = ref(0);
const loading = ref(false);
const loadingMore = ref(false);
const appScrollRef = ref(null);
const selectedFile = ref(null);
const detailVisible = ref(false);
const previewLoadFailed = ref(false);
const uploadVisible = ref(false);
const folderVisible = ref(false);
const newFolderName = ref('');
const uploadState = ref({
    overwrite: false
});
const uploadResult = ref('');
const singleInput = ref(null);

const rows = computed(() => {
    const directories = (browser.value?.directories || []).map(item => ({
        ...item,
        entryType: 'directory',
        displayType: '文件夹',
        displaySize: '-'
    }));
    const files = (browser.value?.files || []).map(item => ({
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

async function loadDirectory(path = currentPath.value, targetPage = 1, append = false) {
    if (append && (loading.value || loadingMore.value || !hasMore.value)) {
        return;
    }

    if (append) {
        loadingMore.value = true;
    } else {
        loading.value = true;
    }

    try {
        const response = await api.browseResults(path, {
            page: targetPage,
            pageSize: pageSize.value
        });
        const data = response?.data || {};
        const directories = Array.isArray(data?.directories) ? data.directories : [];
        const files = Array.isArray(data?.files) ? data.files : [];
        const totalEntries = Number(data?.totalEntries || 0);
        if (targetPage > 1 && totalEntries > 0 && !directories.length && !files.length) {
            await loadDirectory(path, 1, false);
            return;
        }

        const mergedDirectories = append
            ? mergePagedRows(browser.value?.directories || [], directories)
            : directories;
        const mergedFiles = append
            ? mergePagedRows(browser.value?.files || [], files)
            : files;

        browser.value = {
            ...data,
            directories: mergedDirectories,
            files: mergedFiles
        };
        currentPath.value = data?.currentPath || path || '';
        page.value = Number(data?.page || targetPage || 1);
        pageSize.value = Number(data?.pageSize || pageSize.value);
        total.value = totalEntries;
    } catch (error) {
        if (!append) {
            browser.value = { directories: [], files: [] };
        }
        pushToast(`工作空间加载失败: ${error.message}`, 'error', 4500);
    } finally {
        loading.value = false;
        loadingMore.value = false;
    }

    await ensureViewportFilled();
}

async function loadMore() {
    if (!hasMore.value || loading.value || loadingMore.value) return;
    await loadDirectory(currentPath.value, page.value + 1, true);
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
        const response = await api.getWorkspaceFileInfo(file.path);
        selectedFile.value = response?.data || null;
        previewLoadFailed.value = false;
        detailVisible.value = true;
    } catch (error) {
        pushToast(`文件详情加载失败: ${error.message}`, 'error', 4500);
    }
}

function openPublishFromWorkspace(file) {
    const filePath = String(file?.path || selectedFile.value?.path || '').trim();
    const targetPath = String(currentPath.value || (file?.entryType === 'directory' ? filePath : '') || '').trim();
    if (!targetPath) {
        pushToast('未找到可用的工作空间路径', 'warning');
        return;
    }
    const aliasSource = String(targetPath).split('/').filter(Boolean).pop() || String(file?.name || selectedFile.value?.name || '').trim();
    setNavigationIntent({
        section: 'publish',
        sourceMode: 'manual',
        workspacePath: targetPath,
        alias: aliasSource
    });
    emit('navigate', {
        section: 'publish',
        sourceMode: 'manual',
        workspacePath: targetPath,
        alias: aliasSource
    });
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
        return api.getWorkspaceFileUrl(fileInfo?.path || '');
    }
    return '';
}

function openUploadModal() {
    uploadState.value.overwrite = false;
    uploadResult.value = '';
    uploadVisible.value = true;
}

function closeUploadModal() {
    uploadVisible.value = false;
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
    uploadResult.value = '上传中...';
    try {
        const response = await api.uploadDataSourceFile(file, currentPath.value, uploadState.value.overwrite, 'workspace');
        uploadResult.value = response?.message || '上传完成';
        pushToast(uploadResult.value, 'success');
        await loadDirectory(currentPath.value, 1, false);
        uploadVisible.value = false;
    } catch (error) {
        uploadResult.value = error.message;
        pushToast(`上传失败: ${error.message}`, 'error', 5000);
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
        await api.createWorkspaceFolder(folderPath);
        newFolderName.value = '';
        pushToast('文件夹创建成功', 'success');
        folderVisible.value = false;
        await loadDirectory(currentPath.value, 1, false);
    } catch (error) {
        pushToast(`创建文件夹失败: ${error.message}`, 'error', 4500);
    }
}

function navigateToRoot() {
    loadDirectory('', 1);
}

function navigateUp() {
    if (!currentPath.value) return;
    const parentPath = currentPath.value.includes('/') ? currentPath.value.split('/').slice(0, -1).join('/') : '';
    loadDirectory(parentPath, 1);
}

async function deleteItem(item, type) {
    const label = type === 'directory' ? '目录' : '文件';
    try {
        await ElMessageBox.confirm(`确认删除${label}“${item.name}”吗？该操作不可恢复。`, `删除${label}`, {
            type: 'warning',
            confirmButtonText: '删除',
            cancelButtonText: '取消',
            confirmButtonClass: 'el-button--danger'
        });
        if (type === 'directory') {
            await api.deleteWorkspaceFolder(item.path);
        } else {
            await api.deleteWorkspaceFile(item.path);
        }
        pushToast(`${label}删除成功`, 'success');
        await loadDirectory(currentPath.value, 1, false);
    } catch (error) {
        if (error === 'cancel' || error === 'close' || error?.message === 'cancel') return;
        pushToast(`删除${label}失败: ${error.message}`, 'error', 5000);
    }
}

async function extractArchive(file) {
    try {
        const { value: extractFolderName } = await ElMessageBox.prompt(
            `确认解压“${file.name}”到当前目录，可选填写解压后的目标文件夹名称。`,
            '解压压缩文件',
            {
                confirmButtonText: '开始解压',
                cancelButtonText: '取消',
                inputPlaceholder: '留空则使用默认名称',
                inputValue: ''
            }
        );
        await api.extractArchive(file.path, 'workspace', false, extractFolderName);
        pushToast('压缩文件解压完成', 'success');
        await loadDirectory(currentPath.value, 1, false);
    } catch (error) {
        if (error === 'cancel' || error === 'close' || error?.message === 'cancel') return;
        pushToast(`解压失败: ${error.message}`, 'error', 5000);
    }
}

onMounted(async () => {
    await loadDirectory('', 1, false);
});
</script>

<template>
    <section class="app-view standard-page">
        <div class="page-banner">
            <div class="page-banner__meta">
                <div class="page-banner__title">工作空间</div>
                <div class="page-banner__desc">面向交付资产目录进行归档、补充上传与发布前整理，确保外部成果也能纳入统一交付体系。</div>
            </div>
        </div>

        <div ref="appScrollRef" class="app-scroll" @scroll.passive="handleBrowserScroll">
            <div class="content-stack">
                <el-card class="standard-panel browser-panel" shadow="never">
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
                                        <a href="#" @click.prevent="loadDirectory(segment.path, 1)">{{ segment.label }}</a>
                                    </el-breadcrumb-item>
                                </el-breadcrumb>
                            </div>
                            <div class="tool-actions">
                                <el-button v-if="currentPath" @click="navigateUp">上一级</el-button>
                                <el-button @click="loadDirectory(currentPath, 1, false)">刷新</el-button>
                                <el-button @click="openFolderModal">新建文件夹</el-button>
                                <el-button type="primary" @click="openUploadModal">上传到当前目录</el-button>
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
                                    @click="loadDirectory(row.path, 1)"
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
                        <el-table-column prop="displayType" label="类型" min-width="180" />
                        <el-table-column prop="displaySize" label="大小" min-width="140" />
                        <el-table-column label="操作" width="220" fixed="right">
                            <template #default="{ row }">
                                <div class="browser-table-actions">
                                    <el-button
                                        v-if="row.entryType === 'directory'"
                                        link
                                        @click="loadDirectory(row.path, 1)"
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
                                        v-if="row.entryType === 'directory'"
                                        link
                                        @click="openPublishFromWorkspace(row)"
                                    >
                                        去发布
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

        <ResizableDrawer v-model="detailVisible" title="工作空间文件详情" :width="820" :min-width="560" :max-width="1320" destroy-on-close @closed="closeDetailModal">
            <div v-if="selectedFile" class="standard-detail-stack">
                <el-descriptions :column="1" direction="vertical" border>
                    <el-descriptions-item label="文件">{{ selectedFile.name || selectedFile.path || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="大小">{{ formatBytes(selectedFile.size) }}</el-descriptions-item>
                    <el-descriptions-item label="更新时间">{{ formatDateTime(selectedFile.lastModified || selectedFile.modifiedTime) || '-' }}</el-descriptions-item>
                    <el-descriptions-item label="元数据">{{ selectedFile.metadata?.bandCount ? `${selectedFile.metadata.bandCount} 波段` : '普通文件' }}</el-descriptions-item>
                </el-descriptions>
                <div v-if="resolvePreviewUrl(selectedFile)" class="datasource-preview-card workspace-preview-card">
                    <div class="datasource-preview-head">图片预览</div>
                    <div class="datasource-preview-frame workspace-preview-frame">
                        <img
                            v-if="!previewLoadFailed"
                            :src="resolvePreviewUrl(selectedFile)"
                            :alt="selectedFile?.name || 'preview'"
                            class="datasource-preview-image workspace-preview-image"
                            @error="previewLoadFailed = true"
                        >
                        <div v-else class="message warning">图片加载失败</div>
                    </div>
                </div>
                <div class="workspace-detail-actions">
                    <el-button type="primary" @click="openPublishFromWorkspace(selectedFile)">按当前路径发布</el-button>
                </div>
            </div>
        </ResizableDrawer>

        <ResizableDrawer v-model="uploadVisible" title="上传到工作空间当前目录" :width="520" :min-width="420" :max-width="760" destroy-on-close @closed="closeUploadModal">
            <el-form label-width="100px">
                <el-form-item label="覆盖同名">
                    <el-switch v-model="uploadState.overwrite" />
                </el-form-item>
                <el-form-item>
                    <el-button type="primary" @click="triggerSingleUpload">选择单文件</el-button>
                </el-form-item>
                <input ref="singleInput" hidden type="file" accept=".zip,.tar,.tgz,.tar.gz,.7z,.json,.png,.jpg,.jpeg,.terrain,.b3dm,.glb,.gltf,.geojson,.tif,.tiff" @change="handleSingleUpload">
                <el-alert
                    :title="uploadResult || '文件会直接上传到当前目录，压缩包上传后可在列表中单独执行解压。'"
                    type="info"
                    :closable="false"
                    show-icon
                />
            </el-form>
        </ResizableDrawer>

        <ResizableDrawer v-model="folderVisible" title="新建工作空间文件夹" :width="520" :min-width="420" :max-width="760" destroy-on-close @closed="closeFolderModal">
            <el-form label-width="100px">
                <el-form-item label="文件夹名称">
                    <el-input v-model="newFolderName" placeholder="例如 publish/project-a" />
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
    border: 1px solid var(--tf-border);
    border-radius: 16px;
    background: linear-gradient(180deg, var(--tf-surface) 0%, var(--tf-surface-soft) 100%);
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

.workspace-preview-card {
    margin-top: 18px;
}

.workspace-preview-frame {
    min-height: 320px;
}

.workspace-preview-image {
    max-height: 520px;
}

.workspace-detail-actions {
    margin-top: 16px;
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
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
    color: var(--el-color-warning);
}

.browser-name-icon.is-file {
    color: var(--tf-accent);
}

.browser-name-copy {
    min-width: 0;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    color: var(--tf-text-primary);
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
    color: var(--tf-text-muted);
    font-size: 13px;
}

.browser-panel {
    overflow: visible;
}

.browser-panel :deep(.el-card__header) {
    position: sticky;
    top: 0;
    z-index: 20;
    background: var(--tf-surface);
    border-bottom: 1px solid var(--tf-border);
}
</style>
