<script setup>
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import {
    Check,
    Clock,
    CopyDocument,
    Delete,
    EditPen,
    MoreFilled,
    Plus,
    Refresh,
    Search,
    View
} from '@element-plus/icons-vue';

import PathPickerModal from '../components/PathPickerModal.vue';
import ResizableDrawer from '../components/ResizableDrawer.vue';
import { api } from '../services/api';
import { formatDateTime, normalizeListInput } from '../utils/formatters';
import { pushToast } from '../composables/useToast';
import { addNavigationIntentListener, consumeNavigationIntent } from '../utils/navigationIntent';

const PublicationPreviewModal = defineAsyncComponent(() => import('../components/PublicationPreviewModal.vue'));

const picker = reactive({
    visible: false,
    title: '',
    source: 'workspace',
    selectionMode: 'folder',
    multiple: false,
    field: 'workspacePath',
    allowedExtensions: []
});

const form = reactive({
    sourceMode: 'task',
    taskId: '',
    workspacePath: '',
    alias: '',
    publishType: 'imagery',
    publishMethod: 'wmts',
    seedEnabled: true,
    seedMinZoom: 0,
    seedMaxZoom: 16,
    vectorMinZoom: 0,
    vectorMaxZoom: 14,
    vectorLayerName: '',
    enabled: true,
    visibility: 'public',
    note: ''
});

const createVisible = ref(false);
const detailVisible = ref(false);
const detailPublication = ref(null);
const detailLoading = ref(false);
const previewVisible = ref(false);
const keyword = ref('');
const statusFilter = ref('');
const publishTypeFilter = ref('');
const publications = ref([]);
const tasks = ref([]);
const tasksLoaded = ref(false);
const tasksLoading = ref(false);
const publicationsLoading = ref(false);
const editingPublicationId = ref('');
const currentPage = ref(1);
const pageSize = ref(10);
const totalPublications = ref(0);
const publicationDetails = ref({});
const selectedPublicationIds = ref([]);
const detailSeedStatus = ref(null);
const detailSeedLoading = ref(false);
const detailCacheInfo = ref(null);
const detailCacheLoading = ref(false);
const detailTab = ref('core');
const applyingIntent = ref(false);
let publicationRefreshTimer = null;
let detailSeedRefreshTimer = null;
let removeNavigationIntentListener = null;

const DATASOURCE_PUBLISH_TYPE = 'imagery';
const DATASOURCE_PUBLISH_METHOD = 'geoserver-wmts';
const DATASOURCE_PUBLISH_TYPE_LABEL = '地图';
const DATASOURCE_PUBLISH_METHOD_LABEL = '数据源影像发布';
const MBTILES_PUBLISH_METHOD = 'mbtiles-mvt';

const publishMethodCatalog = {
    imagery: [
        { value: 'wmts', label: 'WMTS 服务' },
        { value: 'tms', label: 'TMS 服务' },
        { value: 'xyz', label: 'XYZ 服务' }
    ],
    'electronic-map': [
        { value: 'wmts', label: 'WMTS 服务' },
        { value: 'tms', label: 'TMS 服务' },
        { value: 'xyz', label: 'XYZ 服务' }
    ],
    terrain: [
        { value: 'cesium-terrain', label: 'Cesium Terrain' },
        { value: 'quantized-mesh', label: 'Quantized Mesh' }
    ],
    '3dtiles': [
        { value: '3d-tiles', label: '3D Tiles 服务' }
    ],
    vector: [
        { value: 'mvt-xyz', label: 'MVT XYZ' },
        { value: 'mvt-tms', label: 'MVT TMS' },
        { value: 'geojson-tile', label: 'GeoJSON 瓦片' }
    ]
};

const publishTypeLabelMap = {
    imagery: '地图',
    'electronic-map': '地图',
    terrain: '地形',
    '3dtiles': '3DTiles',
    vector: '二维矢量'
};

const visibilityLabelMap = {
    private: '私有',
    internal: '内部',
    public: '公开'
};

const publicationStatusLabelMap = {
    enabled: '已启动',
    disabled: '未启动',
    published: '已启动',
    draft: '构建中',
    failed: '失败'
};

const publicationStatusTagMap = {
    enabled: 'success',
    disabled: 'info',
    published: 'success',
    draft: 'warning',
    failed: 'danger'
};
const TILES_BASE_PATH = '/app/tiles';
const DATASOURCE_BASE_PATH = '/app/dataSource';
const GEOSERVER_METHODS = ['geoserver-wms', 'geoserver-wmts'];
const VECTOR_MVT_METHODS = ['mvt', 'mvt-xyz', 'mvt-tms', 'vector-tile', 'vector-tiles', MBTILES_PUBLISH_METHOD, 'mvt-dynamic', 'dynamic-mvt'];
const VECTOR_GEOJSON_METHODS = ['geojson-tile', 'geojson-tiles'];
const DATASOURCE_IMAGERY_EXTENSIONS = ['.tif', '.tiff'];
const DATASOURCE_VECTOR_EXTENSIONS = ['.mbtiles', '.geojson', '.json', '.shp', '.gpkg'];

const isDatasourceMode = computed(() => form.sourceMode === 'datasource');
const publishMethodOptions = computed(() => {
    if (isDatasourceMode.value) {
        return form.publishType === 'vector'
            ? [{ value: MBTILES_PUBLISH_METHOD, label: '动态 MVT / MBTiles' }]
            : [{ value: DATASOURCE_PUBLISH_METHOD, label: DATASOURCE_PUBLISH_METHOD_LABEL }];
    }
    return publishMethodCatalog[form.publishType] || [];
});
const isGeoserverPublish = computed(() => GEOSERVER_METHODS.includes(String(form.publishMethod || '').toLowerCase()));
const isMbtilesPublish = computed(() => String(form.publishMethod || '').toLowerCase() === MBTILES_PUBLISH_METHOD);
const isDatasourcePublish = computed(() => isGeoserverPublish.value);
const dataSourceAllowedExtensions = computed(() => {
    if (!isDatasourceMode.value) return [];
    return [...DATASOURCE_IMAGERY_EXTENSIONS, ...DATASOURCE_VECTOR_EXTENSIONS];
});
const dataSourcePlaceholder = computed(() => {
    if (isMbtilesPublish.value) return '选择 .geojson/.shp/.gpkg 生成 MBTiles，或选择已有 .mbtiles';
    return '选择 .tif/.tiff 影像，或 .geojson/.shp/.gpkg/.mbtiles 矢量文件';
});

const publishableTasks = computed(() => {
    return [...tasks.value]
        .filter(task => task?.status === 'completed' && (task?.result?.mergedOutputPath || task?.result?.outputPath || task?.result?.artifactId))
        .sort((a, b) => String(b.startTime || '').localeCompare(String(a.startTime || '')));
});

const selectedTask = computed(() => publishableTasks.value.find(task => task.taskId === form.taskId) || null);
const modalTitle = computed(() => editingPublicationId.value ? '编辑发布' : '创建发布');
const selectedPublicationSet = computed(() => new Set(selectedPublicationIds.value));
const allPublicationIds = computed(() => publications.value.map(item => String(item?.publicationId || '').trim()).filter(Boolean));
const allSelected = computed(() => Boolean(allPublicationIds.value.length) && allPublicationIds.value.every(id => selectedPublicationSet.value.has(id)));
const selectedPublicationCount = computed(() => selectedPublicationIds.value.length);

function normalizeDisplayUrl(url) {
    const value = String(url || '').trim();
    if (!value) return '';
    return value
        .replace(/^((?:https?):\/\/)([^/?#]+)/i, (_, protocol, hostPart) => {
            const portMatch = String(hostPart || '').match(/:(\d+)$/);
            return `${protocol}localhost${portMatch ? `:${portMatch[1]}` : ''}`;
        })
        .replace(/%7B/ig, '{')
        .replace(/%7D/ig, '}');
}

function resolveInteractiveUrl(url) {
    const value = String(url || '').trim();
    if (!value) return '';
    return value
        .replace(/^((?:https?):\/\/)([^/?#]+)/i, (_, protocol, hostPart) => {
            const portMatch = String(hostPart || '').match(/:(\d+)$/);
            const nextHost = window.location.hostname || 'localhost';
            return `${protocol}${nextHost}${portMatch ? `:${portMatch[1]}` : ''}`;
        })
        .replace(/%7B/ig, '{')
        .replace(/%7D/ig, '}');
}

/**
 * 根据 URL 中的端口判断地址来源后端，用于在 UI 中给用户展示服务标签。
 * - nginx：静态瓦片服务（ATLASWORKS_NGINX_HOST_PORT，默认 18080）
 * - publisher：发布 API 服务（ATLASWORKS_PUBLISHER_HOST_PORT，默认 18001）
 * - api：主 API 服务（ATLASWORKS_HOST_PORT，默认 18000）
 * - geoserver：GeoServer 服务（默认 18083）
 */
function getUrlBackend(url) {
    const value = String(url || '').trim();
    if (!value) return '';
    const portMatch = value.match(/^https?:\/\/[^/:]+:(\d+)/i);
    if (!portMatch) return '';
    const port = Number(portMatch[1]);
    // GeoServer 对外端口（默认 18083）
    if (port === 18083 || port === 8080) return 'geoserver';
    // Nginx 静态瓦片端口（默认 18080）
    if (port === 18080) return 'nginx';
    // 发布服务端口（默认 18001）
    if (port === 18001) return 'publisher';
    // 主 API 端口（默认 18000）
    if (port === 18000) return 'api';
    return '';
}

const BACKEND_LABEL = {
    nginx: 'Nginx 静态',
    publisher: '发布服务',
    api: 'API 服务',
    geoserver: 'GeoServer'
};

function getEndpointBackendLabel(url) {
    return BACKEND_LABEL[getUrlBackend(url)] || '';
}

function toPreviewPublication(item) {
    if (!item) return null;
    const vectorPublication = item.vectorPublication ? {
        ...item.vectorPublication,
        tileJsonUrl: resolveInteractiveUrl(item.vectorPublication.tileJsonUrl),
        xyzTemplate: resolveInteractiveUrl(item.vectorPublication.xyzTemplate),
        sampleTileUrl: resolveInteractiveUrl(item.vectorPublication.sampleTileUrl),
        tilesetUrl: resolveInteractiveUrl(item.vectorPublication.tilesetUrl)
    } : item.vectorPublication;
    return {
        ...item,
        vectorPublication,
        browserUrl: resolveInteractiveUrl(item.browserUrl),
        launchUrl: resolveInteractiveUrl(item.launchUrl),
        accessUrl: resolveInteractiveUrl(item.accessUrl),
        sampleUrl: resolveInteractiveUrl(item.sampleUrl),
        wmsUrl: resolveInteractiveUrl(item.wmsUrl),
        wmtsCapabilitiesUrl: resolveInteractiveUrl(item.wmtsCapabilitiesUrl),
        wmtsTileUrl: resolveInteractiveUrl(item.wmtsTileUrl)
    };
}

function getMergedPublication(item) {
    if (!item) return null;
    const publicationId = String(item?.publicationId || item?.id || '').trim();
    const detail = publicationId ? publicationDetails.value[publicationId] : null;
    return detail ? { ...item, ...detail } : item;
}

function normalizeSeedTaskState(statusText = '') {
    const text = String(statusText || '').trim();
    if (!text) return 'idle';
    const lowered = text.toLowerCase();
    if (text === '当前没有运行中的预热任务' || lowered.includes('no running') || lowered.includes('idle')) return 'idle';
    if (lowered.includes('running') || lowered.includes('pending') || lowered.includes('seeding') || lowered.includes('truncate')) return 'running';
    if (lowered.includes('error') || lowered.includes('failed')) return 'failed';
    return 'submitted';
}

function getSeedStatusTone(state = '') {
    const normalized = String(state || '').trim().toLowerCase();
    if (normalized === 'failed') return 'is-danger';
    if (normalized === 'running') return 'is-warning';
    if (normalized === 'submitted' || normalized === 'completed') return 'is-success';
    return 'is-muted';
}

function getSeedStatusLabel(status = null) {
    if (!status) return '暂无状态';
    if (status.running) return '预热进行中';
    if (status.state === 'completed') return '预热已完成';
    if (status.statusText === '当前没有运行中的预热任务') return '当前空闲';
    if (status.state === 'submitted') return '预热已提交';
    if (status.state === 'failed') return '状态读取失败';
    return '当前空闲';
}

function getSeedStatusDescription(status = null) {
    if (!status) return '当前没有预热任务。';
    const text = String(status.statusText || status.status || '').trim();
    if (text) return text;
    if (status.running) return 'GeoServer 正在执行预热任务。';
    return '当前没有运行中的预热任务。';
}

function isPublicationEnabled(item) {
    return Boolean(item?.metadata?.enabled ?? (item?.status === 'enabled' || item?.status === 'published'));
}

function getPublicationSourceSummary(item) {
    const sourceMode = item?.metadata?.sourceMode || (item?.metadata?.taskId ? 'task' : 'manual');
    if (sourceMode === 'task' && item?.metadata?.taskId) return `任务 ${item.metadata.taskId}`;
    if (sourceMode === 'datasource') {
        const count = getPublicationDataSourcePaths(item).length;
        return count ? `数据源 ${count} 项` : '数据源发布';
    }
    const entryCount = Number(item?.sourceEntryCount ?? item?.metadata?.sourceEntryCount ?? 0);
    return entryCount ? `${entryCount} 项` : (normalizeWorkspacePath(item?.publishPath || '') || '-');
}

function getPrimaryPublicationUrl(item) {
    if (!item) return '';
    const method = String(item?.metadata?.publishMethod || item?.publishMethod || '').toLowerCase();
    if (method.includes('geoserver')) {
        return normalizeDisplayUrl(item?.sampleUrl || item?.accessUrl || '');
    }
    return normalizeDisplayUrl(item?.accessUrl || item?.browserUrl || item?.launchUrl || '');
}

function getPrimaryPublicationHref(item) {
    if (!item) return '';
    const method = String(item?.metadata?.publishMethod || item?.publishMethod || '').toLowerCase();
    if (method.includes('geoserver')) {
        return resolveInteractiveUrl(item?.sampleUrl || item?.accessUrl || '');
    }
    return resolveInteractiveUrl(item?.accessUrl || item?.browserUrl || item?.launchUrl || '');
}

function getPrimaryPublicationUrlLabel(item) {
    if (!item) return '访问地址';
    const method = String(item?.metadata?.publishMethod || item?.publishMethod || '').toLowerCase();
    if (method.includes('geoserver')) {
        return '示例瓦片';
    }
    return '访问地址';
}

function getSecondaryPublicationUrl(item) {
    return '';
}

function getSecondaryPublicationHref(item) {
    return '';
}

function normalizeWorkspacePath(pathValue) {
    let path = String(pathValue || '').trim().replace(/\\/g, '/');
    if (!path) return '';

    const lowerPath = path.toLowerCase();
    const lowerBase = TILES_BASE_PATH.toLowerCase();
    if (lowerPath === lowerBase) return '';
    if (lowerPath.startsWith(`${lowerBase}/`)) {
        path = path.slice(TILES_BASE_PATH.length + 1);
    }
    return path.replace(/^\/+|\/+$/g, '');
}

function normalizeDataSourcePath(pathValue) {
    let path = String(pathValue || '').trim().replace(/\\/g, '/');
    if (!path) return '';

    const lowerPath = path.toLowerCase();
    const lowerBase = DATASOURCE_BASE_PATH.toLowerCase();
    if (lowerPath === lowerBase) return '';
    if (lowerPath.startsWith(`${lowerBase}/`)) {
        path = path.slice(DATASOURCE_BASE_PATH.length + 1);
    }
    return path.replace(/^\/+|\/+$/g, '');
}

function getNormalizedSourcePath() {
    return form.sourceMode === 'datasource'
        ? getNormalizedDataSourcePaths()[0] || ''
        : normalizeWorkspacePath(form.workspacePath);
}

function getNormalizedDataSourcePaths() {
    return normalizeListInput(form.workspacePath)
        .map(item => normalizeDataSourcePath(item))
        .filter(Boolean);
}

function isVectorDataSourcePath(pathValue) {
    const normalized = String(pathValue || '').trim().toLowerCase();
    return DATASOURCE_VECTOR_EXTENSIONS.some(extension => normalized.endsWith(extension));
}

function syncDatasourcePublishModeFromPath(pathValue = form.workspacePath) {
    if (!isDatasourceMode.value) return;
    if (isVectorDataSourcePath(pathValue)) {
        form.publishType = 'vector';
        form.publishMethod = MBTILES_PUBLISH_METHOD;
        return;
    }
    form.publishType = DATASOURCE_PUBLISH_TYPE;
    form.publishMethod = DATASOURCE_PUBLISH_METHOD;
}

function getPublicationDataSourcePaths(item) {
    const rawSourcePaths = Array.isArray(item?.metadata?.sourcePaths) && item.metadata.sourcePaths.length
        ? item.metadata.sourcePaths
        : normalizeListInput(item?.metadata?.sourcePath || item?.metadata?.workspacePath || item?.publishPath || '');
    return rawSourcePaths
        .map(item => normalizeDataSourcePath(item))
        .filter(Boolean);
}

function getPublicationSourceTarget(item) {
    const sourceMode = item?.metadata?.sourceMode || (item?.metadata?.taskId ? 'task' : 'manual');
    if (sourceMode === 'datasource') {
        const paths = getPublicationDataSourcePaths(item);
        return paths.length ? paths.join(', ') : '-';
    }
    return normalizeWorkspacePath(item?.metadata?.workspacePath || item?.publishPath || '') || '-';
}

function getPublicationSeedConfig(item) {
    const customMetadata = item?.metadata?.customMetadata || item?.customMetadata || {};
    return {
        enabled: Boolean(customMetadata?.seedEnabled),
        minZoom: Number(customMetadata?.minZoom ?? 0),
        maxZoom: Number(customMetadata?.maxZoom ?? 16)
    };
}

function getPublicationSeedSummary(item) {
    const metadata = item?.metadata || {};
    const customMetadata = metadata?.customMetadata || item?.customMetadata || {};
    if (!GEOSERVER_METHODS.includes(String(metadata?.publishMethod || item?.publishMethod || '').toLowerCase())) {
        return '非 GeoServer 服务';
    }
    const configured = getPublicationSeedConfig(item);
    const seedError = String(metadata?.seedError || customMetadata?.seedError || '').trim();
    const cachedSeedStatus = metadata?.seedStatus || customMetadata?.seedStatus || null;
    if (seedError) return '预热失败';
    if (detailPublication.value && getPublicationId(item) === getPublicationId(detailPublication.value) && detailSeedStatus.value?.running) {
        return '预热进行中';
    }
    if (cachedSeedStatus?.running) return '预热进行中';
    if (cachedSeedStatus?.state === 'completed') return '预热已完成';
    if (cachedSeedStatus?.statusText && cachedSeedStatus?.state === 'submitted') return '预热已提交';
    if (cachedSeedStatus?.state === 'idle') return '当前空闲';
    if (configured.enabled) return `预热层级 ${configured.minZoom}-${configured.maxZoom}`;
    return '未启用预热';
}

function getPublicationSeedClass(item) {
    const summary = getPublicationSeedSummary(item);
    if (summary.includes('失败')) return 'is-danger';
    if (summary.includes('进行中')) return 'is-warning';
    if (summary.includes('提交') || summary.startsWith('预热层级')) return 'is-success';
    return 'is-muted';
}

function getGeoserverWorkspace(item) {
    return String(item?.metadata?.geoserverWorkspace || item?.metadata?.customMetadata?.geoserverWorkspace || '').trim();
}

function getGeoserverLayerNames(item) {
    const metadata = item?.metadata || {};
    const customMetadata = metadata?.customMetadata || {};
    const raw = metadata?.geoserverLayerNames || customMetadata?.geoserverLayerNames || [];
    if (Array.isArray(raw) && raw.length) return raw.filter(Boolean);
    const single = metadata?.geoserverLayerName || customMetadata?.geoserverLayerName || '';
    return single ? [single] : [];
}

function getGeoserverStoreNames(item) {
    const metadata = item?.metadata || {};
    const customMetadata = metadata?.customMetadata || {};
    const raw = metadata?.geoserverStoreNames || customMetadata?.geoserverStoreNames || [];
    if (Array.isArray(raw) && raw.length) return raw.filter(Boolean);
    const single = metadata?.geoserverStoreName || customMetadata?.geoserverStoreName || '';
    return single ? [single] : [];
}

function getPublicationCachePath(item) {
    return normalizeWorkspacePath(item?.publishPath || item?.metadata?.workspacePath || '');
}

function getTaskResultPath(task) {
    const rawPath = task?.result?.mergedOutputPath || task?.result?.outputPath || '';
    const normalizedPath = normalizeWorkspacePath(rawPath);
    return normalizedPath || '-';
}

function getPublishTypeLabel(value) {
    return publishTypeLabelMap[value] || value || '-';
}

function getVisibilityLabel(value) {
    return visibilityLabelMap[value] || value || '-';
}

function getPublicationStatusLabel(value) {
    return publicationStatusLabelMap[value] || value || '-';
}

function getPublicationStatusTag(value) {
    return publicationStatusTagMap[value] || 'info';
}

function getPublicationStatusBadgeClass(item) {
    const status = String(item?.status || '').toLowerCase();
    if (status === 'failed') return 'is-danger';
    if (status === 'draft') return 'is-warning';
    return isPublicationEnabled(item) ? 'is-success' : 'is-muted';
}

function getPublicationVisibilityBadgeClass(item) {
    return String(item?.metadata?.visibility || '').toLowerCase() === 'private' ? 'is-private' : 'is-shared';
}

function getPublicationVisibilityBadgeLabel(item) {
    return String(item?.metadata?.visibility || '').toLowerCase() === 'private' ? '私有' : '公共';
}

function getPublishMethodLabel(publishType, publishMethod) {
    const normalized = String(publishMethod || '').trim().toLowerCase();
    if (GEOSERVER_METHODS.includes(normalized)) {
        return '数据源影像发布';
    }
    if (normalized === 'nginx-static') {
        if (publishType === 'terrain') return 'Quantized Mesh';
        if (publishType === '3dtiles') return '3D Tiles 服务';
        if (publishType === 'vector') return 'XYZ 服务';
        return 'XYZ 服务';
    }
    const option = (publishMethodCatalog[publishType] || []).find(item => item.value === publishMethod);
    return option?.label || publishMethod || '-';
}

function getPublicationCategoryLine(item) {
    return [
        getPublishTypeLabel(item?.publishType),
        getPublishMethodLabel(item?.publishType, item?.metadata?.publishMethod || item?.publishMethod)
    ].filter(Boolean).join(' / ');
}

function getPublicationUpdatedTime(item) {
    return formatDateTime(item?.updatedAt || item?.publishedAt || item?.createdAt);
}

function getPublicationPublishedTime(item) {
    return formatDateTime(item?.publishedAt || item?.createdAt);
}

function getPublicationTileSchemeLabel(item) {
    const method = String(item?.metadata?.publishMethod || item?.publishMethod || '').trim().toLowerCase();
    if (method === 'wmts' || method === 'xyz') return 'XYZ';
    if (method === 'tms') return 'TMS';
    return getSourceTileScheme(item);
}

function getPublicationCopyUrl(item) {
    const merged = getMergedPublication(item);
    return getPrimaryPublicationUrl(merged) || getSecondaryPublicationUrl(merged) || '';
}

function getPublicationId(item) {
    return String(item?.publicationId || item?.id || '').trim();
}

function isGeoserverPublication(item) {
    return GEOSERVER_METHODS.includes(String(item?.metadata?.publishMethod || item?.publishMethod || '').toLowerCase());
}

function isPublicationSelected(item) {
    return selectedPublicationSet.value.has(getPublicationId(item));
}

function togglePublicationSelection(item, checked) {
    const publicationId = getPublicationId(item);
    if (!publicationId) return;
    if (checked) {
        selectedPublicationIds.value = Array.from(new Set([...selectedPublicationIds.value, publicationId]));
        return;
    }
    selectedPublicationIds.value = selectedPublicationIds.value.filter(id => id !== publicationId);
}

function toggleSelectAll(checked) {
    selectedPublicationIds.value = checked ? [...allPublicationIds.value] : [];
}

function clearPublicationSelection() {
    selectedPublicationIds.value = [];
}

function getDefaultPublishMethodForType(publishType) {
    const options = publishMethodCatalog[publishType] || [];
    return options[0]?.value || 'wmts';
}

function ensurePublishMethodForCurrentMode() {
    if (isDatasourceMode.value) {
        syncDatasourcePublishModeFromPath();
        return;
    }
    const options = publishMethodCatalog[form.publishType] || [];
    if (!options.some(item => item.value === form.publishMethod)) {
        form.publishMethod = options[0]?.value || '';
    }
}

async function copyText(text) {
    const value = String(text || '').trim();
    if (!value) return false;

    if (navigator.clipboard?.writeText && window.isSecureContext) {
        await navigator.clipboard.writeText(value);
        return true;
    }

    const textArea = document.createElement('textarea');
    textArea.value = value;
    textArea.setAttribute('readonly', 'readonly');
    textArea.style.position = 'absolute';
    textArea.style.left = '-9999px';
    document.body.appendChild(textArea);
    textArea.select();
    const copied = document.execCommand('copy');
    document.body.removeChild(textArea);
    return copied;
}

async function copyPublicationUrl(url) {
    try {
        const copied = await copyText(url);
        if (!copied) {
            throw new Error('复制失败');
        }
        pushToast('发布地址已复制', 'success');
    } catch (error) {
        pushToast(`复制失败: ${error.message}`, 'error', 4000);
    }
}

function handlePublicationMenu(command, item) {
    if (command === 'edit') {
        editPublication(item);
        return;
    }

    if (command === 'toggle') {
        togglePublicationStatus(item, !isPublicationEnabled(item));
        return;
    }

    if (command === 'delete') {
        removePublication(item);
    }
}

function openPublicationDetail(item) {
    detailPublication.value = item || null;
    detailVisible.value = true;
    detailTab.value = 'core';
    loadPublicationDetail(item?.publicationId);
}

function closePublicationDetail() {
    if (detailSeedRefreshTimer) {
        window.clearInterval(detailSeedRefreshTimer);
        detailSeedRefreshTimer = null;
    }
    detailVisible.value = false;
    detailPublication.value = null;
    detailLoading.value = false;
    detailSeedStatus.value = null;
    detailCacheInfo.value = null;
    detailSeedLoading.value = false;
    detailCacheLoading.value = false;
    detailTab.value = 'core';
}

function openPublicationPreview(item) {
    const merged = getMergedPublication(item || detailPublication.value);
    detailPublication.value = toPreviewPublication(merged || item || detailPublication.value);
    previewVisible.value = true;
    if (item?.publicationId && !(merged?.accessUrl || merged?.launchUrl || merged?.browserUrl)) {
        loadPublicationDetail(item.publicationId);
    }
}

async function loadPublicationDetail(publicationId) {
    const normalizedId = String(publicationId || '').trim();
    if (!normalizedId) return;
    if (detailSeedRefreshTimer) {
        window.clearInterval(detailSeedRefreshTimer);
        detailSeedRefreshTimer = null;
    }
    detailLoading.value = true;
    try {
        const response = await api.getPublication(normalizedId);
        const publication = response?.data?.publication || detailPublication.value;
        if (publication) {
            publicationDetails.value = {
                ...publicationDetails.value,
                [normalizedId]: publication
            };
        }
        detailPublication.value = toPreviewPublication(publication);
        const detailTasks = [loadPublicationCacheDetail(publication)];
        if (isGeoserverPublication(publication)) {
            detailTasks.push(loadPublicationSeedStatus(publication));
        }
        await Promise.all(detailTasks);
        if (isGeoserverPublication(publication)) {
            detailSeedRefreshTimer = window.setInterval(() => {
                if (!detailVisible.value || !detailPublication.value || detailSeedLoading.value || !isGeoserverPublication(detailPublication.value)) return;
                loadPublicationSeedStatus(detailPublication.value);
            }, 5000);
        }
    } catch (error) {
        pushToast(`发布详情加载失败: ${error.message}`, 'error', 4500);
    } finally {
        detailLoading.value = false;
    }
}

async function loadPublicationSeedStatus(publication = detailPublication.value) {
    const publicationId = getPublicationId(publication);
    if (!publicationId || !GEOSERVER_METHODS.includes(String(publication?.metadata?.publishMethod || publication?.publishMethod || '').toLowerCase())) {
        detailSeedStatus.value = null;
        return;
    }
    detailSeedLoading.value = true;
    try {
        const response = await api.getPublicationSeedStatus(publicationId);
        const payload = response?.data || response || {};
        detailSeedStatus.value = {
            ...payload,
            state: payload?.state || normalizeSeedTaskState(payload?.statusText || payload?.status),
            statusText: payload?.statusText || payload?.status || '暂无状态',
        };
        mergePublicationSeedStatus(publicationId, detailSeedStatus.value);
    } catch (error) {
        detailSeedStatus.value = {
            running: false,
            state: 'failed',
            status: error.message,
            statusText: `状态读取失败：${error.message}`
        };
        mergePublicationSeedStatus(publicationId, detailSeedStatus.value);
    } finally {
        detailSeedLoading.value = false;
    }
}

function mergePublicationSeedStatus(publicationId, seedStatus) {
    const normalizedId = String(publicationId || '').trim();
    if (!normalizedId || !seedStatus) return;
    const normalizedStatus = {
        ...seedStatus,
        running: Boolean(seedStatus?.running),
        state: seedStatus?.state || normalizeSeedTaskState(seedStatus?.statusText || seedStatus?.status),
        statusText: seedStatus?.statusText || seedStatus?.status || '暂无状态',
        taskCount: Number(seedStatus?.taskCount || 0)
    };
    publicationDetails.value = {
        ...publicationDetails.value,
        [normalizedId]: {
            ...(publicationDetails.value[normalizedId] || publications.value.find(item => getPublicationId(item) === normalizedId) || {}),
            metadata: {
                ...((publicationDetails.value[normalizedId] || publications.value.find(item => getPublicationId(item) === normalizedId) || {}).metadata || {}),
                seedStatus: normalizedStatus
            }
        }
    };
    publications.value = publications.value.map(item => {
        if (getPublicationId(item) !== normalizedId) return item;
        return {
            ...item,
            metadata: {
                ...(item.metadata || {}),
                seedStatus: normalizedStatus
            }
        };
    });
}

async function refreshPublicationSeedStatuses(items = publications.value) {
    const targets = (Array.isArray(items) ? items : []).filter(item => {
        const publicationId = getPublicationId(item);
        return publicationId && isGeoserverPublication(item);
    });
    if (!targets.length) return;
    await Promise.all(targets.map(async item => {
        try {
            const response = await api.getPublicationSeedStatus(getPublicationId(item));
            const payload = response?.data || response || {};
            mergePublicationSeedStatus(getPublicationId(item), payload);
        } catch {
            return null;
        }
        return null;
    }));
}

async function loadPublicationCacheDetail(publication = detailPublication.value) {
    const cachePath = getPublicationCachePath(publication);
    if (!cachePath) {
        detailCacheInfo.value = null;
        return;
    }
    detailCacheLoading.value = true;
    try {
        const response = await api.getTileCacheDetail(cachePath);
        detailCacheInfo.value = response?.data || response || null;
    } catch {
        detailCacheInfo.value = null;
    } finally {
        detailCacheLoading.value = false;
    }
}

function getVectorPublicationKind(publishMethod) {
    const normalizedMethod = String(publishMethod || '').trim().toLowerCase();
    if (VECTOR_MVT_METHODS.includes(normalizedMethod)) return 'mvt';
    if (VECTOR_GEOJSON_METHODS.includes(normalizedMethod)) return 'geojson';
    return '';
}

function getVectorSourceLayerHint(item) {
    const vectorLayers = item?.vectorPublication?.vectorLayers || item?.metadata?.vectorLayers || item?.customMetadata?.vectorLayers || [];
    if (Array.isArray(vectorLayers) && vectorLayers.length && vectorLayers[0]?.id) {
        return String(vectorLayers[0].id).trim();
    }
    return 'source-layer-name';
}

function getSourceTileScheme(item) {
    const raw = String(
        item?.metadata?.sourceTileScheme
        || item?.customMetadata?.sourceTileScheme
        || item?.sourceTileScheme
        || ''
    ).trim().toLowerCase();
    if (raw === 'google' || raw === 'xyz') return 'XYZ';
    return 'TMS';
}

function formatBounds(bounds) {
    if (!Array.isArray(bounds) || bounds.length !== 4) return '-';
    return bounds.map(value => Number(value).toFixed(6)).join(', ');
}

function dedupeGuideEndpoints(items = []) {
    const seen = new Set();
    return items.filter(item => {
        const url = String(item?.url || '').trim();
        if (!url) return false;
        if (seen.has(url)) return false;
        seen.add(url);
        return true;
    });
}

function getPublicationGuide(item) {
    if (!item) {
        return {
            endpoints: [],
            notes: [],
            concepts: []
        };
    }

    const publishMethod = String(item?.publishMethod || item?.metadata?.publishMethod || '').toLowerCase();
    const vectorKind = getVectorPublicationKind(publishMethod);
    const endpoints = [];
    const notes = [];
    const concepts = [];
    const metadataRows = [];

    if (item.browserUrl) {
        endpoints.push({
            key: 'browser',
            label: '浏览器预览',
            url: normalizeDisplayUrl(item.browserUrl),
            href: resolveInteractiveUrl(item.browserUrl),
            backend: getEndpointBackendLabel(item.browserUrl),
            description: '直接在浏览器打开，用于查看已发布内容或入口文件。'
        });
    }

    if (vectorKind) {
        const vectorPublication = item?.vectorPublication || {};
        metadataRows.push({
            key: 'vector-kind',
            label: '矢量格式',
            value: vectorKind === 'mvt' ? 'MVT / PBF' : 'GeoJSON Tile'
        });
        metadataRows.push({
            key: 'vector-zoom',
            label: '层级范围',
            value: vectorPublication.minzoom !== undefined && vectorPublication.maxzoom !== undefined
                ? `${vectorPublication.minzoom} - ${vectorPublication.maxzoom}`
                : '-'
        });
        metadataRows.push({
            key: 'vector-bounds',
            label: '数据范围',
            value: formatBounds(vectorPublication.bounds)
        });
        metadataRows.push({
            key: 'vector-layer',
            label: 'source-layer',
            value: getVectorSourceLayerHint(item)
        });
        metadataRows.push({
            key: 'vector-scheme',
            label: '行号规则',
            value: getSourceTileScheme(item)
        });

        if (item.launchUrl) {
            endpoints.push({
                key: 'tilejson',
                label: 'TileJSON',
                url: normalizeDisplayUrl(item.launchUrl),
                href: resolveInteractiveUrl(item.launchUrl),
                backend: getEndpointBackendLabel(item.launchUrl),
                description: vectorKind === 'mvt'
                    ? '矢量发布入口。MapLibre 优先使用这个地址。'
                    : '矢量瓦片描述文件，可用于查看层级、范围和模板地址。'
            });
        }
        if (item.accessUrl) {
            endpoints.push({
                key: 'xyz',
                label: 'XYZ 模板',
                url: normalizeDisplayUrl(item.accessUrl),
                href: resolveInteractiveUrl(item.accessUrl),
                backend: getEndpointBackendLabel(item.accessUrl),
                description: vectorKind === 'mvt'
                    ? '按 {z}/{x}/{y} 请求 PBF 瓦片。OpenLayers 常直接使用这个地址。'
                    : '按 {z}/{x}/{y} 请求 GeoJSON 瓦片，适合调试或小数据量使用。'
            });
        }
        if (item.sampleUrl && item.sampleUrl !== item.launchUrl && item.sampleUrl !== item.accessUrl && item.sampleUrl !== item.browserUrl) {
            endpoints.push({
                key: 'sample',
                label: '示例瓦片',
                url: normalizeDisplayUrl(item.sampleUrl),
                href: resolveInteractiveUrl(item.sampleUrl),
                backend: getEndpointBackendLabel(item.sampleUrl),
                description: '用于直接验证某一级某一块瓦片是否可访问。'
            });
        }

        if (vectorKind === 'mvt') {
            notes.push('二维矢量正式发布优先使用 MVT。');
            notes.push('程序接入时可直接使用 TileJSON，或按 XYZ 模板请求 PBF 瓦片。');
            notes.push('预览按钮可直接检查当前发布是否能正常出图。');
            concepts.push({
                title: 'MVT 是什么',
                text: 'MVT 是二进制矢量瓦片格式，体积更小、客户端支持更广，适合正式发布。'
            });
        } else {
            notes.push('GeoJSON 瓦片更适合调试、小数据量或兼容用途。');
            notes.push('正式发布如需更高性能，建议改发 MVT。');
            notes.push('预览按钮可直接检查 GeoJSON 瓦片是否按层级正常返回。');
            concepts.push({
                title: 'GeoJSON 瓦片适用场景',
                text: 'GeoJSON 瓦片可读性高，但体积和客户端生态都不如 MVT，更适合调试和小规模数据。'
            });
        }
    } else if (publishMethod === 'wmts' || publishMethod.includes('geoserver')) {
        if (item.launchUrl) {
            endpoints.push({
                key: 'capabilities',
                label: 'Capabilities',
                url: normalizeDisplayUrl(item.launchUrl),
                href: resolveInteractiveUrl(item.launchUrl),
                backend: getEndpointBackendLabel(item.launchUrl),
                description: '地图服务元数据入口，GIS 客户端一般先读取这个地址。'
            });
        }
        if (item.sampleUrl) {
            endpoints.push({
                key: 'tiles',
                label: '示例瓦片',
                url: normalizeDisplayUrl(item.sampleUrl),
                href: resolveInteractiveUrl(item.sampleUrl),
                backend: getEndpointBackendLabel(item.sampleUrl),
                description: '用于直接验证服务是否能稳定返回瓦片。'
            });
        }
        if (item.accessUrl && item.accessUrl !== item.launchUrl) {
            endpoints.push({
                key: 'service',
                label: '服务地址',
                url: normalizeDisplayUrl(item.accessUrl),
                href: resolveInteractiveUrl(item.accessUrl),
                backend: getEndpointBackendLabel(item.accessUrl),
                description: '服务访问入口。'
            });
        }

        notes.push('GIS 客户端优先加载 Capabilities。');
        notes.push('浏览器直接验证时，可先打开“示例瓦片”。');
        metadataRows.push({
            key: 'wmts-scheme',
            label: '行号规则',
            value: 'XYZ / EPSG:3857'
        });
        const workspace = getGeoserverWorkspace(item);
        const layers = getGeoserverLayerNames(item);
        const stores = getGeoserverStoreNames(item);
        if (workspace) metadataRows.push({ key: 'gs-workspace', label: 'Workspace', value: workspace });
        if (stores.length) metadataRows.push({ key: 'gs-store', label: 'Store', value: stores.join(', ') });
        if (layers.length) metadataRows.push({ key: 'gs-layer', label: 'Layer', value: layers.join(', ') });
        const seedConfig = getPublicationSeedConfig(item);
        metadataRows.push({
            key: 'gs-seed',
            label: '预热配置',
            value: seedConfig.enabled ? `层级 ${seedConfig.minZoom} - ${seedConfig.maxZoom}` : '未启用'
        });
    } else {
        if (item.launchUrl && item.launchUrl !== item.browserUrl && item.launchUrl !== item.accessUrl) {
            endpoints.push({
                key: 'launch',
                label: '程序入口',
                url: normalizeDisplayUrl(item.launchUrl),
                href: resolveInteractiveUrl(item.launchUrl),
                backend: getEndpointBackendLabel(item.launchUrl),
                description: '给客户端或前端程序使用的入口地址。'
            });
        }
        if (item.accessUrl) {
            endpoints.push({
                key: 'access',
                label: '访问地址',
                url: normalizeDisplayUrl(item.accessUrl),
                href: resolveInteractiveUrl(item.accessUrl),
                backend: getEndpointBackendLabel(item.accessUrl),
                description: '这是当前发布记录的主要访问地址。'
            });
        }
        if (item.sampleUrl && item.sampleUrl !== item.accessUrl && item.sampleUrl !== item.browserUrl) {
            endpoints.push({
                key: 'sample',
                label: '示例地址',
                url: normalizeDisplayUrl(item.sampleUrl),
                href: resolveInteractiveUrl(item.sampleUrl),
                backend: getEndpointBackendLabel(item.sampleUrl),
                description: '用于快速验证发布内容。'
            });
        }
    }

    return {
        endpoints: dedupeGuideEndpoints(endpoints),
        notes,
        concepts,
        metadataRows
    };
}

const detailGuide = computed(() => getPublicationGuide(detailPublication.value));

function resetForm() {
    form.sourceMode = 'task';
    form.taskId = '';
    form.workspacePath = '';
    form.alias = '';
    form.publishType = 'imagery';
    form.publishMethod = 'wmts';
    form.seedEnabled = true;
    form.seedMinZoom = 0;
    form.seedMaxZoom = 16;
    form.vectorMinZoom = 0;
    form.vectorMaxZoom = 14;
    form.vectorLayerName = '';
    form.enabled = true;
    form.visibility = 'public';
    form.note = '';
}

function applyIntentToForm(intent = {}) {
    if (!intent || intent.section !== 'publish') return;
    applyingIntent.value = true;
    editingPublicationId.value = '';
    resetForm();
    if (intent.sourceMode) form.sourceMode = intent.sourceMode;
    if (intent.taskId) form.taskId = intent.taskId;
    if (intent.workspacePath) form.workspacePath = intent.workspacePath;
    if (intent.alias) form.alias = intent.alias;
    if (intent.publishType && publishMethodCatalog[intent.publishType]) form.publishType = intent.publishType;
    if (intent.publishMethod) form.publishMethod = intent.publishMethod;
    if (intent.sourceMode === 'manual' && intent.workspacePath) {
        form.workspacePath = normalizeWorkspacePath(intent.workspacePath);
    }
    if (intent.sourceMode === 'datasource' && intent.workspacePath) {
        form.workspacePath = normalizeDataSourcePath(intent.workspacePath);
        syncDatasourcePublishModeFromPath(form.workspacePath);
    }
    createVisible.value = true;
    if (form.sourceMode === 'task') {
        ensureTasksLoaded();
    }
    queueMicrotask(() => {
        applyingIntent.value = false;
    });
}

async function ensureTasksLoaded(force = false) {
    if (tasksLoading.value) return;
    if (tasksLoaded.value && !force) return;
    tasksLoading.value = true;
    try {
        const response = await api.getAllTasks({
            page: 1,
            pageSize: 500,
            status: 'completed'
        });
        tasks.value = Object.values(response?.data?.tasks || {});
        tasksLoaded.value = true;
    } catch (error) {
        pushToast(`可发布任务加载失败: ${error.message}`, 'error', 4500);
    } finally {
        tasksLoading.value = false;
    }
}

function openCreateModal() {
    editingPublicationId.value = '';
    resetForm();
    createVisible.value = true;
    ensureTasksLoaded();
}

function openPicker(config) {
    Object.assign(picker, config, { visible: true });
}

function getPickerCurrentValue() {
    return picker.field ? String(form[picker.field] || '') : '';
}

function applyPickerSelection(paths) {
    const nextValue = picker.multiple ? paths.join(', ') : (paths[0] || '');
    if (picker.field) {
        form[picker.field] = nextValue;
    }
    if (picker.field === 'workspacePath' && isDatasourceMode.value) {
        syncDatasourcePublishModeFromPath(nextValue);
    }
}

function editPublication(item) {
    editingPublicationId.value = item.publicationId;
    form.sourceMode = item.metadata?.sourceMode || (item.metadata?.taskId ? 'task' : 'manual');
    form.taskId = item.metadata?.taskId || '';
    form.workspacePath = form.sourceMode === 'datasource'
        ? getPublicationDataSourcePaths(item).join(', ')
        : normalizeWorkspacePath(item.metadata?.workspacePath || item.publishPath || '');
    form.alias = item.alias || '';
    form.publishType = item.publishType || 'imagery';
    form.publishMethod = item.metadata?.publishMethod || 'wmts';
    form.seedEnabled = Boolean(item.metadata?.customMetadata?.seedEnabled ?? true);
    form.seedMinZoom = Number(item.metadata?.customMetadata?.minZoom ?? 0);
    form.seedMaxZoom = Number(item.metadata?.customMetadata?.maxZoom ?? 16);
    form.vectorMinZoom = Number(item.metadata?.customMetadata?.minZoom ?? 0);
    form.vectorMaxZoom = Number(item.metadata?.customMetadata?.maxZoom ?? 14);
    form.vectorLayerName = item.metadata?.customMetadata?.layerName || '';
    form.enabled = isPublicationEnabled(item);
    form.visibility = item.metadata?.visibility || 'private';
    form.note = item.metadata?.note || '';
    if (form.sourceMode === 'datasource') {
        form.publishType = DATASOURCE_PUBLISH_TYPE;
        form.publishMethod = item.metadata?.publishMethod || DATASOURCE_PUBLISH_METHOD;
    }
    createVisible.value = true;
    if (form.sourceMode === 'task') {
        ensureTasksLoaded();
    }
}

async function togglePublicationStatus(item, explicitEnabled = null) {
    const nextEnabled = explicitEnabled === null ? !isPublicationEnabled(item) : Boolean(explicitEnabled);
    try {
        await api.togglePublicationEnabled(item.publicationId, nextEnabled);
        pushToast(nextEnabled ? '发布已启用' : '发布已停用', 'success');
        await loadPublications();
    } catch (error) {
        pushToast(`切换发布状态失败: ${error.message}`, 'error', 5000);
    }
}

async function removePublication(item) {
    const confirmed = window.confirm(`确认删除发布记录「${item.alias || item.publicationId}」吗？`);
    if (!confirmed) return;

    try {
        await api.deletePublication(item.publicationId);
        pushToast('发布记录已删除', 'success');
        selectedPublicationIds.value = selectedPublicationIds.value.filter(id => id !== getPublicationId(item));
        await loadPublications();
    } catch (error) {
        pushToast(`删除发布记录失败: ${error.message}`, 'error', 5000);
    }
}

async function reseedPublication(item = detailPublication.value) {
    const publication = getMergedPublication(item);
    const layers = getGeoserverLayerNames(publication);
    const workspace = getGeoserverWorkspace(publication);
    const seedConfig = getPublicationSeedConfig(publication);
    if (!layers.length || !workspace) {
        pushToast('当前发布不存在可用的 GeoServer 图层', 'warning');
        return;
    }
    try {
        await api.geoserverSeedLayer(layers[0], {
            workspace,
            minZoom: seedConfig.minZoom,
            maxZoom: seedConfig.maxZoom,
            format: 'image/png',
            threadCount: 1
        });
        pushToast('预热任务已重新提交', 'success');
        await loadPublicationSeedStatus(publication);
    } catch (error) {
        pushToast(`预热提交失败: ${error.message}`, 'error', 5000);
    }
}

async function cancelPublicationSeed(item = detailPublication.value) {
    const publication = getMergedPublication(item);
    const layers = getGeoserverLayerNames(publication);
    const workspace = getGeoserverWorkspace(publication);
    if (!layers.length || !workspace) {
        pushToast('当前发布不存在可用的 GeoServer 图层', 'warning');
        return;
    }
    try {
        await api.geoserverCancelSeed(layers[0], { workspace });
        pushToast('预热取消指令已发送', 'success');
        await loadPublicationSeedStatus(publication);
    } catch (error) {
        pushToast(`取消预热失败: ${error.message}`, 'error', 5000);
    }
}

async function clearPublicationCache(item = detailPublication.value) {
    const publication = getMergedPublication(item);
    const cachePath = getPublicationCachePath(publication);
    if (!cachePath) {
        pushToast('当前发布没有可清理的缓存目录', 'warning');
        return;
    }
    const confirmed = window.confirm(`确认清理缓存目录「${cachePath}」吗？`);
    if (!confirmed) return;
    try {
        await api.deleteTileCache(cachePath);
        pushToast('缓存目录已清理', 'success');
        await Promise.all([loadPublicationCacheDetail(publication), loadPublications()]);
    } catch (error) {
        pushToast(`清理缓存失败: ${error.message}`, 'error', 5000);
    }
}

async function clearPublicationCacheZoom(zoom) {
    const publication = getMergedPublication(detailPublication.value);
    const cachePath = getPublicationCachePath(publication);
    if (!cachePath) {
        pushToast('当前发布没有可清理的缓存目录', 'warning');
        return;
    }
    try {
        await api.deleteTileCacheZoomLevels(cachePath, [zoom]);
        pushToast(`Z${zoom} 缓存已清理`, 'success');
        await Promise.all([loadPublicationCacheDetail(publication), loadPublications()]);
    } catch (error) {
        pushToast(`清理层级缓存失败: ${error.message}`, 'error', 5000);
    }
}

async function batchTogglePublications(enabled) {
    const targetIds = [...selectedPublicationIds.value];
    if (!targetIds.length) {
        pushToast('请先选择发布记录', 'warning');
        return;
    }
    const failures = [];
    for (const publicationId of targetIds) {
        try {
            await api.togglePublicationEnabled(publicationId, enabled);
        } catch (error) {
            failures.push(`${publicationId}: ${error.message}`);
        }
    }
    if (failures.length) {
        pushToast(`批量操作完成，失败 ${failures.length} 项`, 'warning', 5000);
    } else {
        pushToast(enabled ? '批量启用完成' : '批量停用完成', 'success');
    }
    clearPublicationSelection();
    await loadPublications();
}

async function batchDeletePublications() {
    const targetIds = [...selectedPublicationIds.value];
    if (!targetIds.length) {
        pushToast('请先选择发布记录', 'warning');
        return;
    }
    const confirmed = window.confirm(`确认删除已选择的 ${targetIds.length} 个发布记录吗？`);
    if (!confirmed) return;
    const failures = [];
    for (const publicationId of targetIds) {
        try {
            await api.deletePublication(publicationId);
        } catch (error) {
            failures.push(`${publicationId}: ${error.message}`);
        }
    }
    if (failures.length) {
        pushToast(`批量删除完成，失败 ${failures.length} 项`, 'warning', 5000);
    } else {
        pushToast('批量删除完成', 'success');
    }
    clearPublicationSelection();
    await loadPublications();
}

watch(() => form.publishType, value => {
    if (isDatasourceMode.value) {
        form.publishMethod = value === 'vector' ? MBTILES_PUBLISH_METHOD : DATASOURCE_PUBLISH_METHOD;
        return;
    }
    const options = publishMethodCatalog[value] || [];
    if (!options.some(item => item.value === form.publishMethod)) {
        form.publishMethod = options[0]?.value || '';
    }
}, { immediate: true });

watch(() => form.publishMethod, value => {
    const normalizedValue = String(value || '').toLowerCase();
    if (isDatasourceMode.value) {
        form.publishType = normalizedValue === MBTILES_PUBLISH_METHOD ? 'vector' : DATASOURCE_PUBLISH_TYPE;
        form.taskId = '';
        return;
    }
    if (GEOSERVER_METHODS.includes(normalizedValue)) {
        form.sourceMode = 'datasource';
        form.taskId = '';
    }
});

watch(() => form.sourceMode, value => {
    if (applyingIntent.value) return;
    if (value === 'task') {
        form.workspacePath = '';
    } else {
        form.taskId = '';
    }
    if (value === 'datasource') {
        syncDatasourcePublishModeFromPath();
    } else {
        ensurePublishMethodForCurrentMode();
    }
});

watch(() => form.workspacePath, value => {
    if (applyingIntent.value || !isDatasourceMode.value) return;
    syncDatasourcePublishModeFromPath(value);
});

watch(() => form.taskId, value => {
    const task = publishableTasks.value.find(item => item.taskId === value);
    if (!task) return;
    const publishHints = task.result?.publishHints || {};
    const hintedPublishType = publishHints.publishType === 'geo' ? 'vector' : publishHints.publishType;
    if (hintedPublishType && publishMethodCatalog[hintedPublishType]) {
        form.publishType = hintedPublishType;
    }
    const methodOptions = publishMethodCatalog[form.publishType] || [];
    if (publishHints.publishMethod && methodOptions.some(item => item.value === publishHints.publishMethod)) {
        form.publishMethod = publishHints.publishMethod;
    }
    if (form.alias) return;
    const path = getTaskResultPath(task);
    const pathParts = String(path || '').split('/').filter(Boolean);
    form.alias = pathParts[pathParts.length - 1] || task.taskId;
});

async function loadPublications() {
    if (publicationsLoading.value) return;
    publicationsLoading.value = true;
    try {
        const response = await api.listPublications({
            page: currentPage.value,
            pageSize: pageSize.value,
            includeDetails: false,
            keyword: String(keyword.value || '').trim() || undefined,
            status: String(statusFilter.value || '').trim() || undefined,
            publishType: String(publishTypeFilter.value || '').trim() || undefined
        });
        const data = response?.data || {};
        publications.value = [...(data.publications || [])].sort((a, b) => {
            const left = String(a?.publishedAt || a?.createdAt || '');
            const right = String(b?.publishedAt || b?.createdAt || '');
            return right.localeCompare(left);
        });
        selectedPublicationIds.value = selectedPublicationIds.value.filter(id => publications.value.some(item => getPublicationId(item) === id));
        totalPublications.value = Number(data.total || 0);
        currentPage.value = Number(data.page || currentPage.value);
        pageSize.value = Number(data.pageSize || pageSize.value);
        await refreshPublicationSeedStatuses(publications.value);
    } catch (error) {
        pushToast(`发布记录加载失败: ${error.message}`, 'error', 4500);
    } finally {
        publicationsLoading.value = false;
    }
}

async function loadTasks() {
    await ensureTasksLoaded(true);
}

async function submitPublication() {
    if (form.sourceMode === 'task' && !form.taskId) {
        pushToast('请先选择任务结果', 'warning');
        return;
    }
    if (form.sourceMode === 'manual' && !form.workspacePath) {
        pushToast('请先选择工作空间目录', 'warning');
        return;
    }
    if (form.sourceMode === 'datasource' && !form.workspacePath) {
        pushToast('请先选择数据源文件或目录', 'warning');
        return;
    }

    const normalizedWorkspacePath = getNormalizedSourcePath();
    const normalizedDataSourcePaths = form.sourceMode === 'datasource' ? getNormalizedDataSourcePaths() : [];
    if (form.sourceMode === 'datasource' && !normalizedDataSourcePaths.length) {
        pushToast(isMbtilesPublish.value ? '请选择一个有效的 .mbtiles 文件' : '请至少选择一个有效的 GeoTIFF 文件或目录', 'warning');
        return;
    }
    if (form.sourceMode === 'datasource' && isMbtilesPublish.value && !isVectorDataSourcePath(normalizedWorkspacePath)) {
        pushToast('动态 MVT 发布请选择 .geojson、.shp、.gpkg 或 .mbtiles 文件', 'warning');
        return;
    }
    if (form.sourceMode === 'datasource' && isMbtilesPublish.value && Number(form.vectorMaxZoom) < Number(form.vectorMinZoom)) {
        pushToast('最大层级不能小于最小层级', 'warning');
        return;
    }
    const payload = {
        sourceMode: form.sourceMode,
        taskId: form.sourceMode === 'task' ? form.taskId : undefined,
        workspacePath: form.sourceMode === 'manual' ? normalizedWorkspacePath : undefined,
        sourcePath: form.sourceMode === 'datasource' ? normalizedWorkspacePath : undefined,
        sourcePaths: form.sourceMode === 'datasource' ? normalizedDataSourcePaths : undefined,
        publishPath: form.sourceMode === 'manual' ? normalizedWorkspacePath : undefined,
        alias: form.alias || undefined,
        publishType: form.sourceMode === 'datasource' && !isMbtilesPublish.value ? DATASOURCE_PUBLISH_TYPE : form.publishType,
        publishMethod: form.sourceMode === 'datasource' ? (form.publishMethod || DATASOURCE_PUBLISH_METHOD) : (form.publishMethod || undefined),
        enabled: form.enabled,
        visibility: form.visibility,
        note: form.note || undefined,
        customMetadata: form.sourceMode === 'datasource'
            ? (isMbtilesPublish.value ? {
                minZoom: Number(form.vectorMinZoom || 0),
                maxZoom: Number(form.vectorMaxZoom || 14),
                layerName: String(form.vectorLayerName || '').trim() || undefined
            } : {
                seedEnabled: Boolean(form.seedEnabled),
                minZoom: Number(form.seedMinZoom || 0),
                maxZoom: Number(form.seedMaxZoom || 16)
            })
            : undefined
    };

    try {
        if (editingPublicationId.value) {
            await api.updatePublication(editingPublicationId.value, payload);
            pushToast('发布记录已更新', 'success');
        } else {
            await api.createPublication(payload);
            currentPage.value = 1;
            pushToast(
                form.sourceMode === 'datasource' && isMbtilesPublish.value
                    ? '发布记录已创建，MBTiles 正在后台生成'
                    : (form.sourceMode === 'datasource' ? '发布记录已创建，后台正在构建缓存' : '发布记录已创建'),
                'success'
            );
        }

        createVisible.value = false;
        editingPublicationId.value = '';
        await Promise.all([loadPublications(), loadTasks()]);
    } catch (error) {
        pushToast(`${editingPublicationId.value ? '更新' : '创建'}发布记录失败: ${error.message}`, 'error', 5000);
    }
}

onMounted(async () => {
    await loadPublications();
    const initialIntent = consumeNavigationIntent('publish');
    if (initialIntent) {
        applyIntentToForm(initialIntent);
    }
    removeNavigationIntentListener = addNavigationIntentListener(intent => {
        if (intent?.section === 'publish') {
            applyIntentToForm(intent);
        }
    });
    publicationRefreshTimer = window.setInterval(() => {
        loadPublications();
    }, 15000);
});

onBeforeUnmount(() => {
    if (publicationRefreshTimer) {
        window.clearInterval(publicationRefreshTimer);
        publicationRefreshTimer = null;
    }
    if (detailSeedRefreshTimer) {
        window.clearInterval(detailSeedRefreshTimer);
        detailSeedRefreshTimer = null;
    }
    removeNavigationIntentListener?.();
    removeNavigationIntentListener = null;
});

function handlePageChange(page) {
    currentPage.value = page;
    loadPublications();
}

function handlePageSizeChange(size) {
    pageSize.value = size;
    currentPage.value = 1;
    loadPublications();
}

function applyFilters() {
    currentPage.value = 1;
    loadPublications();
}
</script>

<template>
    <section class="app-view standard-page">
        <div class="page-banner">
            <div class="page-banner__meta">
                <div class="page-banner__title">发布中心</div>
                <div class="page-banner__desc">统一管理发布记录，支持按任务生成发布、手动目录发布、启停切换与生命周期维护。</div>
            </div>
            <div class="page-banner__actions publish-header-actions">
                <el-button :icon="Refresh" @click="loadPublications">刷新</el-button>
                <el-button type="primary" :icon="Plus" @click="openCreateModal">创建发布</el-button>
            </div>
        </div>

        <div class="app-scroll">
            <el-card class="standard-panel publish-panel" shadow="never">
                <div class="publish-toolbar" @keydown.capture.enter.prevent="applyFilters">
                    <el-form class="publish-filter-form" @submit.prevent="applyFilters">
                        <div class="publish-filter-item">
                            <span class="publish-filter-label">状态：</span>
                            <el-select v-model="statusFilter" clearable placeholder="全部状态" class="publish-filter-control publish-filter-status">
                                <el-option label="已启动" value="enabled" />
                                <el-option label="未启动" value="disabled" />
                                <el-option label="构建中" value="draft" />
                                <el-option label="失败" value="failed" />
                            </el-select>
                        </div>
                        <div class="publish-filter-item">
                            <span class="publish-filter-label">类型：</span>
                            <el-select v-model="publishTypeFilter" clearable placeholder="全部类型" class="publish-filter-control publish-filter-type">
                                <el-option label="地图" value="imagery" />
                                <el-option label="地形" value="terrain" />
                                <el-option label="3DTiles" value="3dtiles" />
                                <el-option label="二维矢量" value="vector" />
                            </el-select>
                        </div>
                        <div class="publish-filter-item publish-filter-item-keyword">
                            <span class="publish-filter-label">检索：</span>
                            <el-input
                                v-model="keyword"
                                clearable
                                :prefix-icon="Search"
                                placeholder="发布名称 / 路径 / 任务 / 发布方式"
                                class="publish-filter-control publish-filter-keyword"
                            />
                        </div>
                        <el-button type="primary" native-type="submit">搜索</el-button>
                    </el-form>
                    <div class="publish-batch-toolbar">
                        <el-checkbox :model-value="allSelected" :disabled="!publications.length" @change="toggleSelectAll">全选当前页</el-checkbox>
                        <span class="publish-batch-count">已选 {{ selectedPublicationCount }} 项</span>
                        <div class="publish-batch-actions">
                            <el-button size="small" :icon="Check" :disabled="!selectedPublicationCount" @click="batchTogglePublications(true)">批量启用</el-button>
                            <el-button size="small" :disabled="!selectedPublicationCount" @click="batchTogglePublications(false)">批量停用</el-button>
                            <el-button size="small" type="danger" plain :disabled="!selectedPublicationCount" @click="batchDeletePublications">批量删除</el-button>
                        </div>
                    </div>
                </div>

                <div v-if="publications.length" class="publication-card-grid">
                    <el-card
                        v-for="row in publications"
                        :key="row.id || row.alias || row.publishPath"
                        class="publication-card"
                        shadow="never"
                    >
                        <div class="publication-card-select">
                            <el-checkbox :model-value="isPublicationSelected(row)" @change="value => togglePublicationSelection(row, value)" />
                        </div>
                        <div class="publication-card-header">
                            <button class="publication-card-title-button" type="button" @click="openPublicationDetail(row)">
                                <div class="publication-card-title">{{ row.alias || '-' }}</div>
                            </button>
                            <el-dropdown trigger="click" placement="bottom-end" @command="command => handlePublicationMenu(command, row)">
                                <button class="publication-card-more publication-card-more-inline publication-card-more-top" type="button" aria-label="更多操作">
                                    <el-icon><MoreFilled /></el-icon>
                                </button>
                                <template #dropdown>
                                    <el-dropdown-menu class="publication-card-menu">
                                        <el-dropdown-item command="edit">
                                            <el-icon><EditPen /></el-icon>
                                            <span>编辑</span>
                                        </el-dropdown-item>
                                        <el-dropdown-item command="delete" class="is-danger">
                                            <el-icon><Delete /></el-icon>
                                            <span>删除</span>
                                        </el-dropdown-item>
                                    </el-dropdown-menu>
                                </template>
                            </el-dropdown>
                        </div>

                        <div class="publication-card-summary">
                            <span class="publication-inline-text" :class="getPublicationStatusBadgeClass(row)">{{ getPublicationStatusLabel(row.status) }}</span>
                            <span class="publication-summary-separator">|</span>
                            <span class="publication-inline-text" :class="getPublicationVisibilityBadgeClass(row)">{{ getPublicationVisibilityBadgeLabel(row) }}</span>
                            <span class="publication-summary-separator">|</span>
                            <span class="publication-inline-text is-type">{{ getPublishTypeLabel(row?.publishType) }}</span>
                            <span class="publication-summary-separator">|</span>
                            <span class="publication-inline-text is-method">{{ getPublishMethodLabel(row?.publishType, row?.metadata?.publishMethod || row?.publishMethod) }}</span>
                        </div>

                        <div class="publication-card-meta">
                            <span class="publication-card-meta-item">
                                <el-icon><Clock /></el-icon>
                                <span>发布时间：{{ getPublicationPublishedTime(row) }}</span>
                                <span class="publication-meta-separator">|</span>
                                <span>更新时间：{{ getPublicationUpdatedTime(row) }}</span>
                            </span>
                        </div>

                        <div class="publication-card-extra">
                            <span class="publication-extra-label">预热</span>
                            <span class="publication-inline-text" :class="getPublicationSeedClass(row)">{{ getPublicationSeedSummary(row) }}</span>
                        </div>

                        <div class="publication-card-toolbar">
                            <el-button size="default" class="publication-action-button" :icon="View" @click="openPublicationPreview(row)">
                                预览
                            </el-button>
                            <el-button size="default" class="publication-action-button" :icon="CopyDocument" :disabled="!getPublicationCopyUrl(row)" @click="copyPublicationUrl(getPublicationCopyUrl(row))">
                                复制地址
                            </el-button>
                            <div class="publication-card-switch-inline">
                                <span class="publication-card-switch-label">启用状态</span>
                                <el-switch
                                    :model-value="isPublicationEnabled(row)"
                                    @change="value => togglePublicationStatus(row, value)"
                                />
                            </div>
                        </div>
                    </el-card>
                </div>
                <el-empty v-else description="暂无发布记录" />

                <div class="standard-pagination">
                    <el-pagination
                        :current-page="currentPage"
                        :page-size="pageSize"
                        :page-sizes="[10, 20, 50, 100]"
                        :total="totalPublications"
                        background
                        layout="total, sizes, prev, pager, next, jumper"
                        @current-change="handlePageChange"
                        @size-change="handlePageSizeChange"
                    />
                </div>
            </el-card>
        </div>

        <ResizableDrawer v-model="createVisible" :title="modalTitle" :width="980" :min-width="640" :max-width="1320" destroy-on-close>
            <div class="publish-editor-shell">
                <div class="publish-source-tabs">
                    <button type="button" class="publish-source-tab" :class="{ 'is-active': form.sourceMode === 'task' }" @click="form.sourceMode = 'task'">按任务发布</button>
                    <button type="button" class="publish-source-tab" :class="{ 'is-active': form.sourceMode === 'manual' }" @click="form.sourceMode = 'manual'">手动目录</button>
                    <button type="button" class="publish-source-tab" :class="{ 'is-active': form.sourceMode === 'datasource' }" @click="form.sourceMode = 'datasource'">数据源文件</button>
                </div>

                <el-form class="publish-editor-form" label-position="top">
                    <div class="publish-editor-grid">
                        <div class="publish-editor-section publish-editor-section-source">
                            <div class="publish-section-title">发布来源</div>

                            <el-form-item v-if="form.sourceMode === 'task'" label="任务结果">
                                <el-select v-model="form.taskId" filterable placeholder="请选择已完成任务" :loading="tasksLoading" :teleported="false">
                                    <el-option v-for="task in publishableTasks" :key="task.taskId" :label="`${task.taskId} / ${getTaskResultPath(task)}`" :value="task.taskId" />
                                </el-select>
                                <div v-if="selectedTask" class="publish-source-preview">
                                    <span>结果目录：{{ getTaskResultPath(selectedTask) }}</span>
                                    <span>产物 ID：{{ selectedTask.result?.artifactId || '-' }}</span>
                                    <span>开始时间：{{ formatDateTime(selectedTask.startTime) }}</span>
                                </div>
                            </el-form-item>

                            <el-form-item v-else-if="form.sourceMode === 'datasource'" label="数据源">
                                <div class="path-field">
                                    <el-input v-model="form.workspacePath" :placeholder="dataSourcePlaceholder" />
                                    <div class="path-field-actions">
                                        <el-button @click="openPicker({ title: '选择数据源文件', source: 'datasource', selectionMode: 'file', multiple: false, field: 'workspacePath', allowedExtensions: dataSourceAllowedExtensions })">选择文件</el-button>
                                        <el-button v-if="!isMbtilesPublish" @click="openPicker({ title: '选择影像目录', source: 'datasource', selectionMode: 'folder', multiple: false, field: 'workspacePath', allowedExtensions: [] })">选择目录</el-button>
                                        <el-button @click="form.workspacePath = ''">清空</el-button>
                                    </div>
                                </div>
                                <div class="publish-source-preview">
                                    <span>已选项数：{{ getNormalizedDataSourcePaths().length }}</span>
                                    <span>发布模式：{{ isMbtilesPublish ? '生成 MBTiles 并动态发布' : '数据源影像发布' }}</span>
                                    <span>{{ isMbtilesPublish ? '选择 GeoJSON/SHP/GPKG 时会先生成 .mbtiles；选择已有 .mbtiles 时直接动态发布。' : '支持单文件或整个目录，发布细节由系统自动处理。' }}</span>
                                </div>
                            </el-form-item>

                            <el-form-item v-else label="工作空间目录">
                                <div class="path-field">
                                    <el-input v-model="form.workspacePath" placeholder="选择需要发布的工作空间目录" />
                                    <div class="path-field-actions">
                                        <el-button @click="openPicker({ title: '选择工作空间目录', source: 'workspace', selectionMode: 'folder', multiple: false, field: 'workspacePath', allowedExtensions: [] })">选择目录</el-button>
                                        <el-button @click="form.workspacePath = ''">清空</el-button>
                                    </div>
                                </div>
                            </el-form-item>
                        </div>

                        <div class="publish-editor-section publish-editor-section-full">
                            <div class="publish-section-title">基础信息</div>

                            <el-form-item label="发布别名">
                                <el-input v-model="form.alias" placeholder="例如 imagery-release-v1" />
                            </el-form-item>

                            <el-form-item label="发布类型">
                                <el-select v-model="form.publishType" :teleported="false">
                                    <el-option label="地图" value="imagery" />
                                    <el-option v-if="!isDatasourceMode" label="地形" value="terrain" />
                                    <el-option v-if="!isDatasourceMode" label="3DTiles" value="3dtiles" />
                                    <el-option label="二维矢量" value="vector" />
                                </el-select>
                            </el-form-item>

                            <el-form-item label="发布方式">
                                <el-select v-model="form.publishMethod" :teleported="false">
                                    <el-option v-for="option in publishMethodOptions" :key="option.value" :label="option.label" :value="option.value" />
                                </el-select>
                            </el-form-item>
                        </div>

                        <div class="publish-editor-section publish-editor-section-full">
                            <div class="publish-section-title">发布配置</div>

                            <template v-if="isDatasourceMode && !isMbtilesPublish">
                                <el-form-item label="发布后预热">
                                    <el-switch v-model="form.seedEnabled" active-text="启动预热" inactive-text="仅发布服务" />
                                </el-form-item>

                                <el-form-item label="预热层级">
                                    <div class="publish-seed-range">
                                        <el-input-number v-model="form.seedMinZoom" :min="0" :max="24" />
                                        <span class="publish-seed-range-separator">至</span>
                                        <el-input-number v-model="form.seedMaxZoom" :min="0" :max="24" />
                                    </div>
                                </el-form-item>
                            </template>

                            <template v-if="isDatasourceMode && isMbtilesPublish">
                                <el-alert
                                    type="info"
                                    :closable="false"
                                    show-icon
                                    title="GeoJSON/SHP/GPKG 会先生成 MBTiles；已有 .mbtiles 会直接动态发布。发布后使用 TileJSON 或 XYZ 模板访问。"
                                />
                                <el-form-item label="生成层级">
                                    <div class="publish-seed-range">
                                        <el-input-number v-model="form.vectorMinZoom" :min="0" :max="22" />
                                        <span class="publish-seed-range-separator">至</span>
                                        <el-input-number v-model="form.vectorMaxZoom" :min="0" :max="22" />
                                    </div>
                                    <div class="tile-help">仅对 GeoJSON/SHP/GPKG 生成 MBTiles 生效；已有 .mbtiles 使用文件内置层级。</div>
                                </el-form-item>
                                <el-form-item label="source-layer（可选）">
                                    <el-input v-model="form.vectorLayerName" placeholder="留空则使用源文件名" />
                                </el-form-item>
                            </template>

                            <el-form-item label="可见性">
                                <el-select v-model="form.visibility" :teleported="false">
                                    <el-option label="公开" value="public" />
                                    <el-option label="内部" value="internal" />
                                    <el-option label="私有" value="private" />
                                </el-select>
                            </el-form-item>

                            <el-form-item label="启用状态">
                                <el-switch v-model="form.enabled" active-text="启用" inactive-text="停用" />
                            </el-form-item>
                        </div>

                        <div class="publish-editor-section publish-editor-section-full">
                            <div class="publish-section-title">发布说明</div>
                            <el-form-item label="说明备注">
                                <el-input v-model="form.note" type="textarea" :rows="5" placeholder="记录来源、用途和版本说明" />
                            </el-form-item>
                        </div>
                    </div>
                </el-form>
            </div>

            <template #footer>
                <el-button @click="createVisible = false">取消</el-button>
                <el-button type="primary" @click="submitPublication">{{ editingPublicationId ? '保存修改' : '创建发布' }}</el-button>
            </template>
        </ResizableDrawer>

        <ResizableDrawer
            v-model="detailVisible"
            title="发布详情"
            :width="920"
            :min-width="560"
            :max-width="1320"
            destroy-on-close
            @closed="closePublicationDetail"
        >
            <div v-if="detailPublication" class="detail-content">
                <div class="detail-tabs">
                    <button type="button" class="detail-tab-button" :class="{ 'is-active': detailTab === 'core' }" @click="detailTab = 'core'">核心信息</button>
                    <button type="button" class="detail-tab-button" :class="{ 'is-active': detailTab === 'process' }" @click="detailTab = 'process'">过程信息</button>
                </div>

                <div v-if="detailTab === 'core'" class="detail-tab-panel">
                    <div class="detail-section">
                        <div class="detail-section-head">
                            <div class="detail-section-title">核心信息</div>
                            <div class="detail-inline-actions">
                                <el-button size="small" type="primary" plain @click="openPublicationPreview(detailPublication)">预览</el-button>
                                <el-button size="small" plain @click="editPublication(detailPublication)">编辑</el-button>
                            </div>
                        </div>
                    </div>

                    <div class="detail-field-list">
                        <div class="detail-field">
                            <span class="detail-field-label">发布名称</span>
                            <span class="detail-field-value">{{ detailPublication.alias || '-' }}</span>
                        </div>
                        <div class="detail-field">
                            <span class="detail-field-label">发布类型</span>
                            <span class="detail-field-value">{{ getPublishTypeLabel(detailPublication.publishType) }} / {{ getPublishMethodLabel(detailPublication.publishType, detailPublication.metadata?.publishMethod) }}</span>
                        </div>
                        <div class="detail-field">
                            <span class="detail-field-label">状态</span>
                            <span class="detail-field-value">
                                <span class="detail-status-chip" :class="getPublicationStatusBadgeClass(detailPublication)">
                                    <span class="detail-status-dot" :class="getPublicationStatusBadgeClass(detailPublication)"></span>
                                    {{ getPublicationStatusLabel(detailPublication.status) }}
                                </span>
                            </span>
                        </div>
                        <div class="detail-field">
                            <span class="detail-field-label">数据源</span>
                            <span class="detail-field-value">{{ getPublicationSourceSummary(detailPublication) || (detailPublication.publishPath || '-') }}</span>
                        </div>
                        <div v-if="(detailPublication?.metadata?.sourceMode || 'manual') === 'manual'" class="detail-field">
                            <span class="detail-field-label">手动目录路径</span>
                            <span class="detail-field-value detail-field-value-mono">{{ normalizeWorkspacePath(detailPublication?.metadata?.workspacePath || detailPublication?.publishPath || '') || '-' }}</span>
                        </div>
                        <div v-if="(detailPublication?.metadata?.sourceMode || '') === 'datasource'" class="detail-field">
                            <span class="detail-field-label">数据源路径</span>
                            <span class="detail-field-value detail-field-value-mono">{{ detailPublication?.metadata?.sourcePath || detailPublication?.metadata?.workspacePath || '-' }}</span>
                        </div>
                        <div class="detail-field">
                            <span class="detail-field-label">切片文件/文件夹</span>
                            <span class="detail-field-value detail-field-value-mono">{{ getPublicationSourceTarget(detailPublication) }}</span>
                        </div>
                        <div v-if="detailPublication.metadata?.taskId" class="detail-field">
                            <span class="detail-field-label">来源任务</span>
                            <span class="detail-field-value">{{ detailPublication.metadata?.taskId }}</span>
                        </div>
                        <div v-if="detailPublication.artifactId" class="detail-field">
                            <span class="detail-field-label">产物 ID</span>
                            <span class="detail-field-value">{{ detailPublication.artifactId }}</span>
                        </div>
                        <div v-if="detailPublication.bounds?.length === 4" class="detail-field">
                            <span class="detail-field-label">范围</span>
                            <span class="detail-field-value">{{ formatBounds(detailPublication.bounds) }}</span>
                        </div>
                    </div>

                    <div v-if="detailGuide.metadataRows.length" class="detail-section">
                        <div class="detail-section-title">接入参数</div>
                        <div class="detail-field-list">
                            <div
                                v-for="row in detailGuide.metadataRows"
                                :key="row.key"
                                class="detail-field"
                            >
                                <span class="detail-field-label">{{ row.label }}</span>
                                <span class="detail-field-value">{{ row.value || '-' }}</span>
                            </div>
                        </div>
                    </div>

                    <div class="detail-section">
                        <div class="detail-section-head">
                            <div class="detail-section-title">地址</div>
                        </div>
                        <div class="detail-endpoint-list">
                            <div
                                v-for="endpoint in detailGuide.endpoints"
                                :key="endpoint.key"
                                class="detail-endpoint"
                            >
                                <div class="detail-endpoint-head">
                                    <span class="detail-endpoint-label">{{ endpoint.label }}</span>
                                    <span v-if="endpoint.backend" class="detail-endpoint-backend">{{ endpoint.backend }}</span>
                                    <el-button size="small" text @click="copyPublicationUrl(endpoint.url)">复制</el-button>
                                </div>
                                <a class="detail-endpoint-url" :href="endpoint.href || endpoint.url" target="_blank" rel="noreferrer">{{ endpoint.url }}</a>
                                <p class="detail-endpoint-desc">{{ endpoint.description }}</p>
                            </div>
                        </div>
                    </div>
                </div>

                <div v-else class="detail-tab-panel">
                    <div v-if="GEOSERVER_METHODS.includes(String(detailPublication?.metadata?.publishMethod || detailPublication?.publishMethod || '').toLowerCase())" class="detail-section">
                        <div class="detail-section-head">
                            <div class="detail-section-title">预热管理</div>
                            <div class="detail-inline-actions">
                                <el-button size="small" plain :loading="detailSeedLoading" @click="loadPublicationSeedStatus(detailPublication)">刷新状态</el-button>
                                <el-button size="small" type="primary" plain @click="reseedPublication(detailPublication)">重新预热</el-button>
                                <el-button size="small" type="danger" plain @click="cancelPublicationSeed(detailPublication)">取消预热</el-button>
                            </div>
                        </div>
                        <div class="detail-field-list">
                            <div class="detail-field">
                                <span class="detail-field-label">状态</span>
                                <span class="detail-field-value">
                                    <span class="detail-status-chip" :class="getSeedStatusTone(detailSeedStatus?.state)">
                                        <span class="detail-status-dot" :class="getSeedStatusTone(detailSeedStatus?.state)"></span>
                                        {{ getSeedStatusLabel(detailSeedStatus) }}
                                    </span>
                                </span>
                            </div>
                            <div class="detail-field">
                                <span class="detail-field-label">过程信息</span>
                                <span class="detail-field-value">{{ getSeedStatusDescription(detailSeedStatus) }}</span>
                            </div>
                            <div class="detail-field">
                                <span class="detail-field-label">运行中</span>
                                <span class="detail-field-value">{{ detailSeedStatus?.running ? '是' : '否' }}</span>
                            </div>
                            <div v-if="detailSeedStatus?.taskCount" class="detail-field">
                                <span class="detail-field-label">运行队列</span>
                                <span class="detail-field-value">GeoServer 返回 {{ detailSeedStatus.taskCount }} 组队列</span>
                            </div>
                        </div>
                    </div>

                    <div class="detail-section">
                        <div class="detail-section-head">
                            <div class="detail-section-title">缓存运维</div>
                            <div class="detail-inline-actions">
                                <el-button size="small" plain :loading="detailCacheLoading" @click="loadPublicationCacheDetail(detailPublication)">刷新缓存</el-button>
                                <el-button size="small" type="danger" plain @click="clearPublicationCache(detailPublication)">清理全部缓存</el-button>
                            </div>
                        </div>
                        <div class="detail-field-list">
                            <div class="detail-field">
                                <span class="detail-field-label">缓存目录</span>
                                <span class="detail-field-value detail-field-value-mono">{{ getPublicationCachePath(detailPublication) || '-' }}</span>
                            </div>
                            <div class="detail-field">
                                <span class="detail-field-label">缓存大小</span>
                                <span class="detail-field-value">{{ detailCacheInfo?.sizeBytes !== undefined ? `${(Number(detailCacheInfo.sizeBytes || 0) / 1024 / 1024).toFixed(2)} MB` : '-' }}</span>
                            </div>
                        </div>
                        <div v-if="detailCacheInfo?.zoomLevels?.length" class="detail-cache-zoom-list">
                            <div v-for="zoomItem in detailCacheInfo.zoomLevels" :key="zoomItem.zoom" class="detail-cache-zoom-item">
                                <span>Z{{ zoomItem.zoom }}</span>
                                <span>{{ zoomItem.tileFiles }} 个文件</span>
                                <el-button size="small" text type="danger" @click="clearPublicationCacheZoom(zoomItem.zoom)">清理该层</el-button>
                            </div>
                        </div>
                    </div>
                </div>

                <div v-if="detailLoading" class="dialog-loading-text">详情刷新中...</div>
            </div>
        </ResizableDrawer>

        <PathPickerModal
            v-model="picker.visible"
            :title="picker.title"
            :source="picker.source"
            :selection-mode="picker.selectionMode"
            :multiple="picker.multiple"
            :current-value="getPickerCurrentValue()"
            :allowed-extensions="picker.allowedExtensions"
            overlay-class="picker-modal-overlay-top"
            @apply="applyPickerSelection"
        />

        <PublicationPreviewModal
            v-model="previewVisible"
            :publication="detailPublication"
        />
    </section>
</template>

<style scoped>
.page-banner {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
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

.page-banner__actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
}

.standard-panel {
    border-radius: 12px;
}

.publish-toolbar {
    margin-bottom: 18px;
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.publish-filter-form {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    align-items: center;
}

.publish-panel {
    border-radius: 20px;
    border-color: var(--tf-border);
}

.publish-panel :deep(.el-card__body) {
    padding: 22px;
}

.publish-filter-item {
    display: flex;
    align-items: center;
    gap: 8px;
}

.publish-filter-item-keyword {
    flex: 1 1 360px;
}

.publish-filter-label {
    color: var(--tf-text-secondary);
    font-size: 13px;
    white-space: nowrap;
}

.publish-filter-control {
    min-width: 160px;
}

.publish-filter-keyword {
    width: 100%;
}

.publish-filter-keyword :deep(.el-input__wrapper),
.publish-filter-status :deep(.el-input__wrapper),
.publish-filter-type :deep(.el-input__wrapper) {
    min-height: 44px;
    border-radius: 14px;
    box-shadow: 0 0 0 1px var(--tf-border-strong) inset;
}

.publish-filter-keyword :deep(.el-input__wrapper.is-focus),
.publish-filter-status :deep(.el-input__wrapper.is-focus),
.publish-filter-type :deep(.el-input__wrapper.is-focus) {
    box-shadow: 0 0 0 1px var(--tf-accent) inset;
}

.publish-filter-form :deep(.el-button) {
    min-width: 92px;
    height: 44px;
    border-radius: 14px;
    padding: 0 18px;
    font-weight: 600;
}

.standard-pagination {
    display: flex;
    justify-content: flex-end;
    margin-top: 24px;
}

.publish-batch-toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    justify-content: space-between;
    padding: 14px 16px;
    border: 1px solid var(--tf-border);
    border-radius: 16px;
    background: var(--tf-surface-soft);
}

.publish-batch-toolbar :deep(.el-checkbox__label) {
    color: var(--tf-text-primary);
    font-weight: 600;
}

.publish-batch-toolbar :deep(.el-checkbox) {
    margin-right: 2px;
}

.publish-batch-actions {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
}

.publish-batch-toolbar :deep(.el-button) {
    min-width: 108px;
    height: 38px;
    border-radius: 12px;
    font-weight: 700;
}

.publish-batch-count {
    color: var(--tf-text-secondary);
    font-size: 13px;
    font-weight: 600;
    margin-left: auto;
}

.publish-batch-toolbar :deep(.el-button--danger.is-plain) {
    color: #f87171;
    border-color: rgba(248, 113, 113, 0.36);
    background: rgba(248, 113, 113, 0.1);
}

.publish-batch-toolbar :deep(.el-button--danger.is-plain:hover) {
    color: #fff;
    border-color: #ef4444;
    background: #ef4444;
}

.publication-card-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16px;
}

.publication-card {
    position: relative;
    height: 100%;
    border-radius: 18px;
    border: 1px solid var(--tf-border);
    background: var(--tf-surface);
    transition:
        border-color 0.2s ease,
        box-shadow 0.2s ease,
        transform 0.2s ease;
}

.publication-card-select {
    position: absolute;
    top: 18px;
    right: 74px;
    z-index: 1;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 32px;
    height: 32px;
    padding: 0 6px;
    border-radius: 999px;
    background: var(--tf-surface);
    border: 1px solid var(--tf-border);
    box-shadow: 0 6px 14px rgba(15, 23, 42, 0.08);
}

.publication-card:hover {
    transform: translateY(-2px);
    border-color: var(--tf-border-strong);
    box-shadow: 0 14px 30px rgba(46, 84, 134, 0.08);
}

.publication-card :deep(.el-card__body) {
    display: flex;
    flex-direction: column;
    gap: 18px;
    padding: 22px 24px 20px;
}

.publication-card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}

.publication-card-summary {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    flex-wrap: nowrap;
}

.publication-inline-text {
    display: inline-block;
    font-size: 15px;
    font-weight: 700;
    line-height: 1.2;
    white-space: nowrap;
    flex: 0 0 auto;
}

.publication-summary-separator {
    color: var(--tf-border-strong);
    font-size: 14px;
    line-height: 1;
    flex: 0 0 auto;
}

.publication-inline-text.is-success {
    color: #2fa84f;
}

.publication-inline-text.is-warning {
    color: #d9911a;
}

.publication-inline-text.is-danger {
    color: #e34d59;
}

.publication-inline-text.is-muted {
    color: #8a94a6;
}

.publication-inline-text.is-private {
    color: #4a8ef7;
}

.publication-inline-text.is-shared {
    color: #ed9a1a;
}

.publication-inline-text.is-type {
    color: #2563eb;
}

.publication-inline-text.is-method {
    color: var(--tf-text-secondary);
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
}

.publication-card-more {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
}

.publication-card-title {
    font-size: 20px;
    font-weight: 700;
    line-height: 1.3;
    color: #2f6bff;
    word-break: break-word;
    text-decoration: underline;
    text-decoration-thickness: 2px;
    text-underline-offset: 4px;
    transition: color 0.18s ease, text-decoration-color 0.18s ease;
}

.publication-card-title-button {
    padding: 0;
    border: 0;
    background: transparent;
    text-align: left;
    cursor: pointer;
    align-self: flex-start;
}

.publication-card-title-button:hover .publication-card-title {
    color: #1f57e7;
    text-decoration-color: #1f57e7;
}

.publication-card-title-button:focus-visible {
    outline: 2px solid rgba(47, 107, 255, 0.28);
    outline-offset: 4px;
    border-radius: 8px;
}

.publication-card-meta {
    display: flex;
    align-items: center;
    min-height: 28px;
}

.publication-card-extra {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 24px;
}

.publication-extra-label {
    color: var(--tf-text-muted);
    font-size: 13px;
    white-space: nowrap;
}

.publication-card-meta-item {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--tf-text-muted);
    font-size: 14px;
    flex-wrap: wrap;
}

.publication-card-meta-item .el-icon {
    font-size: 18px;
}

.publication-meta-separator {
    color: var(--tf-border-strong);
    font-size: 13px;
    line-height: 1;
}

.publication-card-toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding-top: 12px;
    border-top: 1px solid var(--tf-border);
    flex-wrap: nowrap;
}

.publication-action-button {
    min-width: 0;
    height: 50px;
    padding: 0 22px;
    margin: 0;
    border-radius: 16px;
    border: 1px solid var(--tf-border-strong);
    color: var(--tf-text-secondary);
    background: var(--tf-surface-soft);
    font-size: 15px;
    font-weight: 600;
    box-shadow: none;
}

.publication-action-button:hover {
    border-color: var(--tf-accent);
    color: var(--tf-accent);
    background: var(--tf-accent-soft);
    box-shadow: none;
}

.publication-action-button :deep(.el-icon) {
    font-size: 18px;
}

.publication-card-menu :deep(.el-dropdown-menu__item) {
    gap: 8px;
}

.publication-card-menu :deep(.el-dropdown-menu__item.is-danger) {
    color: #ef4444;
}

.publication-card-menu :deep(.el-dropdown-menu__item.is-danger:not(.is-disabled):focus) {
    background: rgba(239, 68, 68, 0.08);
    color: #ef4444;
}

.publication-card-footer :deep(.el-switch) {
    --el-switch-on-color: #2f87f6;
    --el-switch-off-color: #d5deeb;
}

.publish-header-actions :deep(.el-button) {
    height: 46px;
    padding: 0 18px;
    border-radius: 12px;
    font-weight: 600;
}

.publish-header-actions :deep(.el-button--primary) {
    box-shadow: 0 12px 24px rgba(47, 135, 246, 0.18);
}

.publish-header-actions :deep(.el-button .el-icon) {
    font-size: 16px;
}

.publication-card-switch-inline {
    min-height: 50px;
    padding: 0 0 0 18px;
    display: inline-flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    border-left: 1px solid var(--tf-border);
    margin-left: 8px;
    flex: 0 0 auto;
}

.publication-card-switch-label {
    font-size: 15px;
    font-weight: 600;
    color: var(--tf-text-secondary);
    white-space: nowrap;
}

.publication-card-switch-inline :deep(.el-switch) {
    --el-switch-on-color: #409eff;
    --el-switch-off-color: #d5deeb;
}

.publication-card-more-inline {
    width: 50px;
    height: 50px;
    padding: 0;
    border: 1px solid var(--tf-border-strong);
    border-radius: 16px;
    background: var(--tf-surface-soft);
    color: var(--tf-text-muted);
    cursor: pointer;
    transition: all 0.18s ease;
    flex: 0 0 auto;
    box-shadow: none;
}

.publication-card-more-top {
    margin-left: auto;
}

.publication-card-more-inline:hover {
    border-color: var(--tf-accent);
    color: var(--tf-accent);
    background: var(--tf-accent-soft);
}

.publication-card-more-inline .el-icon {
    font-size: 20px;
}

.publish-panel :deep(.el-pagination) {
    width: 100%;
    justify-content: flex-end;
}

.publish-fixed-field {
    width: 100%;
    min-height: 44px;
    display: flex;
    align-items: center;
    padding: 0 14px;
    border: 1px solid var(--tf-border-strong);
    border-radius: 14px;
    background: var(--tf-surface-soft);
    color: var(--tf-text-primary);
}

.path-field {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 8px;
}

.path-field-actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    flex: 0 0 auto;
}

.standard-table-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
}

.publish-source-preview {
    margin-top: 10px;
    padding: 14px 16px;
    border-radius: 14px;
    border: 1px solid var(--tf-border);
    background: var(--tf-surface-soft);
    display: flex;
    flex-direction: column;
    gap: 6px;
    color: var(--tf-text-secondary);
    line-height: 1.6;
}

.publish-editor-shell {
    display: flex;
    flex-direction: column;
    gap: 20px;
}

.publish-source-tabs {
    display: flex;
    gap: 0;
    flex-wrap: wrap;
    border: 1px solid var(--tf-border);
    border-radius: 16px;
    overflow: hidden;
    align-self: flex-start;
    background: var(--tf-surface-soft);
}

.publish-source-tab {
    min-width: 132px;
    height: 48px;
    padding: 0 22px;
    border: 0;
    border-right: 1px solid var(--tf-border);
    background: transparent;
    color: var(--tf-text-secondary);
    font-size: 15px;
    font-weight: 700;
    cursor: pointer;
    transition: background-color 0.18s ease, color 0.18s ease;
}

.publish-source-tab:last-child {
    border-right: 0;
}

.publish-source-tab.is-active {
    background: var(--tf-accent);
    color: #ffffff;
}

.publish-editor-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 18px;
}

.publish-editor-section {
    padding: 18px;
    border: 1px solid var(--tf-border);
    border-radius: 18px;
    background: var(--tf-surface);
}

.publish-editor-section-source,
.publish-editor-section-full {
    grid-column: 1 / -1;
}

.publish-section-title {
    margin-bottom: 16px;
    color: var(--tf-text-primary);
    font-size: 16px;
    font-weight: 700;
}

.publish-seed-range {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
}

.publish-seed-range :deep(.el-input-number) {
    width: 164px;
}

.detail-content {
    display: flex;
    flex-direction: column;
    gap: 18px;
}

.detail-tabs {
    display: flex;
    align-items: flex-end;
    gap: 10px;
    padding-bottom: 2px;
    border-bottom: 1px solid var(--tf-border);
}

.detail-tab-button {
    appearance: none;
    border: 1px solid transparent;
    background: transparent;
    color: var(--tf-text-secondary);
    font-size: 13px;
    font-weight: 700;
    line-height: 1;
    padding: 11px 16px;
    border-radius: 12px 12px 0 0;
    cursor: pointer;
    transition: color 0.18s ease, background 0.18s ease, border-color 0.18s ease;
}

.detail-tab-button:hover {
    color: var(--tf-text-primary);
    background: var(--tf-surface-soft);
}

.detail-tab-button.is-active {
    color: var(--tf-text-primary);
    background: var(--tf-surface);
    border-color: var(--tf-border);
    border-bottom-color: var(--tf-surface);
}

.detail-tab-panel {
    display: flex;
    flex-direction: column;
    gap: 24px;
}

.detail-field-list {
    display: flex;
    flex-direction: column;
    gap: 0;
    border: 1px solid var(--tf-border);
    border-radius: 12px;
    overflow: hidden;
    background: var(--tf-surface);
}

.detail-field {
    display: flex;
    align-items: baseline;
    gap: 16px;
    padding: 13px 18px;
    border-bottom: 1px solid var(--tf-border);
}

.detail-field:last-child {
    border-bottom: none;
}

.detail-field-label {
    flex: 0 0 120px;
    font-size: 13px;
    color: var(--tf-text-muted);
    white-space: nowrap;
}

.detail-field-value {
    flex: 1;
    min-width: 0;
    font-size: 14px;
    color: var(--tf-text-primary);
    line-height: 1.6;
    word-break: break-all;
    display: flex;
    align-items: center;
    gap: 8px;
}

.detail-status-chip {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-height: 32px;
    padding: 6px 12px;
    border-radius: 999px;
    border: 1px solid transparent;
    font-size: 13px;
    font-weight: 700;
    line-height: 1;
}

.detail-status-chip.is-success {
    color: #95de64;
    background: rgba(103, 194, 58, 0.16);
    border-color: rgba(103, 194, 58, 0.3);
}

.detail-status-chip.is-warning {
    color: #ffd166;
    background: rgba(217, 145, 26, 0.18);
    border-color: rgba(217, 145, 26, 0.34);
}

.detail-status-chip.is-danger {
    color: #ffb3b3;
    background: rgba(227, 77, 89, 0.18);
    border-color: rgba(227, 77, 89, 0.34);
}

.detail-status-chip.is-muted {
    color: var(--tf-text-secondary);
    background: rgba(138, 148, 166, 0.14);
    border-color: rgba(138, 148, 166, 0.22);
}

.detail-field-value-mono {
    font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', Consolas, monospace;
    font-size: 13px;
    color: var(--tf-text-secondary);
}

.detail-status-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
}

.detail-status-dot.is-success {
    background: #2fa84f;
}

.detail-status-dot.is-warning {
    background: #d9911a;
}

.detail-status-dot.is-danger {
    background: #e34d59;
}

.detail-status-dot.is-muted {
    background: #8a94a6;
}

.detail-section {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.detail-section-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}

.detail-inline-actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
}

.detail-section-title {
    font-size: 15px;
    font-weight: 600;
    color: var(--tf-text-primary);
}

.detail-endpoint-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.detail-endpoint {
    padding: 14px 18px;
    border: 1px solid var(--tf-border);
    border-radius: 12px;
    background: var(--tf-surface);
    transition: border-color 0.18s ease;
}

.detail-endpoint:hover {
    border-color: var(--tf-border-strong);
}

.detail-endpoint-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    margin-bottom: 8px;
}

.detail-endpoint-label {
    font-size: 14px;
    font-weight: 600;
    color: var(--tf-text-primary);
}

.detail-endpoint-backend {
    display: inline-flex;
    align-items: center;
    padding: 1px 8px;
    font-size: 11px;
    font-weight: 500;
    line-height: 18px;
    border-radius: 20px;
    background: var(--tf-surface-soft);
    color: var(--tf-text-muted);
    border: 1px solid var(--tf-border);
    margin-right: auto;
    letter-spacing: 0.01em;
    white-space: nowrap;
    user-select: none;
}

.detail-endpoint-url {
    display: inline-block;
    color: var(--tf-accent);
    text-decoration: none;
    font-size: 13px;
    line-break: anywhere;
    transition: color 0.2s ease;
}

.detail-endpoint-url:hover,
.publish-address-link:hover {
    filter: brightness(0.92);
}

.detail-endpoint-desc {
    margin: 8px 0 0;
    color: var(--tf-text-muted);
    font-size: 13px;
    line-height: 1.6;
}

.detail-cache-zoom-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.detail-cache-zoom-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 14px;
    border: 1px solid var(--tf-border);
    border-radius: 10px;
    background: var(--tf-surface-soft);
}

.publish-address-cell {
    min-width: 0;
    display: flex;
    align-items: flex-start;
    gap: 10px;
}

.publish-address-stack {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.publish-address-line {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
}

.publish-address-line-secondary {
    opacity: 0.92;
}

.publish-address-type {
    font-size: 12px;
    color: var(--tf-text-muted);
}

.publish-address-link {
    flex: 1;
    min-width: 0;
    line-break: anywhere;
    font-size: 14px;
    line-height: 1.6;
}

.dialog-loading-text {
    color: var(--tf-text-muted);
    font-size: 12px;
}


.publish-editor-form :deep(.el-input__wrapper),
.publish-editor-form :deep(.el-textarea__inner),
.publish-editor-form :deep(.el-select__wrapper) {
    min-height: 46px;
    border-radius: 14px;
    background: var(--tf-surface-soft);
    box-shadow: 0 0 0 1px var(--tf-border-strong) inset;
}

.publish-editor-form :deep(.el-select) {
    width: 100%;
}

.publish-editor-form :deep(.el-select__popper) {
    z-index: 3600 !important;
}

:deep(.el-textarea__inner) {
    min-height: 136px;
    border-radius: 16px;
    background: var(--tf-surface-soft);
    color: var(--tf-text-primary);
}

.publish-editor-form :deep(.el-form-item) {
    margin-bottom: 0;
}

.publish-editor-form :deep(.el-form-item__label) {
    padding-bottom: 8px;
    color: var(--tf-text-secondary);
    font-size: 13px;
    font-weight: 600;
}

.publish-editor-form :deep(.el-switch) {
    --el-switch-on-color: #409eff;
    --el-switch-off-color: var(--tf-border-strong);
}

.publish-editor-form :deep(.el-switch__label) {
    color: var(--tf-text-primary) !important;
}

.publish-editor-form :deep(.el-switch__label.is-active) {
    color: var(--tf-text-primary) !important;
}

.publish-editor-form :deep(.el-button) {
    min-height: 42px;
    border-radius: 12px;
}

@media (max-width: 768px) {
    .page-banner {
        flex-direction: column;
        align-items: stretch;
    }

    .publication-card-grid {
        grid-template-columns: 1fr;
    }

    .publication-card :deep(.el-card__body) {
        min-height: unset;
    }
}

@media (max-width: 960px) {
    .publish-editor-grid {
        grid-template-columns: 1fr;
    }

    .path-field {
        flex-direction: column;
        align-items: stretch;
    }

    .path-field-actions {
        width: 100%;
    }
}

@media (max-width: 760px) {
    .publish-source-tabs {
        width: 100%;
    }

    .publish-source-tab {
        flex: 1 1 33.33%;
        min-width: 0;
        padding: 0 10px;
    }

    .publication-card-summary {
        flex-wrap: wrap;
        white-space: normal;
    }

    .publication-card-toolbar {
        flex-wrap: wrap;
    }

    .publication-card-switch-inline {
        width: 100%;
        margin-left: 0;
        padding-left: 0;
        border-left: 0;
        border-top: 1px solid var(--tf-border);
        padding-top: 12px;
    }

    .publication-card-select {
        position: static;
        margin-bottom: -6px;
    }
}
</style>
