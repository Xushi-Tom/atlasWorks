<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import { Aim, Monitor, Orange } from '@element-plus/icons-vue';
import ResizableDrawer from './ResizableDrawer.vue';

const props = defineProps({
    modelValue: {
        type: Boolean,
        default: false
    },
    publication: {
        type: Object,
        default: null
    }
});

const emit = defineEmits(['update:modelValue']);

const viewerContainer = ref(null);
const previewStatus = ref('');
const previewReady = ref(false);
const sceneMode = ref('3d');

let viewerInstance = null;
let cesiumLibPromise = null;
let activeCesium = null;

const TITILER_METHODS = ['titiler-cog', 'titiler', 'cog'];
const RASTER_METHODS = ['xyz', 'tms', ...TITILER_METHODS];
const TERRAIN_METHODS = ['cesium-terrain', 'quantized-mesh', 'terrain'];
const VECTOR_MVT_METHODS = ['mvt', 'vector-tile', 'vector-tiles'];
const VECTOR_GEOJSON_METHODS = ['geojson-tile', 'geojson-tiles'];
const TILES_3D_METHODS = ['3d-tiles'];

function normalizeTileScheme(value) {
    const scheme = String(value || '').trim().toLowerCase();
    if (scheme === 'xyz' || scheme === 'google') return 'xyz';
    return 'tms';
}

function getPublicationTileScheme(publication) {
    const publishMethod = String(publication?.metadata?.publishMethod || publication?.publishMethod || '').trim().toLowerCase();
    if (publishMethod === 'xyz' || publishMethod === 'wmts' || TITILER_METHODS.includes(publishMethod)) return 'xyz';
    if (publishMethod === 'tms') return 'tms';
    return normalizeTileScheme(
        publication?.metadata?.sourceTileScheme
        || publication?.customMetadata?.sourceTileScheme
        || publication?.sourceTileScheme
    );
}

function parseSampleTile(url) {
    const value = String(url || '').trim();
    if (!value) return null;
    const match = value.match(/\/(\d+)\/(\d+)\/(\d+)(?:\.[^/?#]+)?(?:[?#].*)?$/i);
    if (!match) return null;
    return {
        z: Number(match[1]),
        x: Number(match[2]),
        y: Number(match[3])
    };
}

function normalizeProjection(value) {
    const raw = String(value || '').trim().toUpperCase();
    if (!raw) return 'EPSG:3857';
    if (raw.includes('4326') || raw.includes('4490') || raw.includes('CRS84')) return 'EPSG:4326';
    if (raw.includes('3395')) return 'EPSG:3395';
    return 'EPSG:3857';
}

function tileToLonLat(z, x, y) {
    const n = 2 ** z;
    const lon = (x / n) * 360 - 180;
    const latRad = Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / n)));
    const lat = (latRad * 180) / Math.PI;
    return [lon, lat];
}

function buildTerrainRootUrl(publication) {
    const publicationId = String(publication?.publicationId || publication?.id || '').trim();
    if (publicationId) {
        const base = String(publication?.publicBaseUrl || publication?.metadata?.publicBaseUrl || window.location.origin).replace(/\/$/, '');
        return `${base}/publication-assets/${publicationId}`;
    }

    const accessUrl = String(publication?.accessUrl || '').trim();
    if (!accessUrl) return '';
    return accessUrl
        .replace(/\/\{z\}\/\{x\}\/\{y\}[^/?#]*([?#].*)?$/i, '')
        .replace(/\/\d+\/\d+\/\d+[^/?#]*([?#].*)?$/i, '');
}

function toCesiumImageryTemplate(url, tileScheme = 'xyz') {
    const value = String(url || '').trim();
    if (!value) return '';
    return tileScheme === 'tms'
        ? value.replace('{y}', '{reverseY}')
        : value;
}

async function fetchTileJsonMetadata(url) {
    const target = String(url || '').trim();
    if (!target || !/tilejson\.json(\?|$)/i.test(target)) return null;
    try {
        const response = await fetch(target);
        if (!response.ok) return null;
        const payload = await response.json();
        const rawBounds = Array.isArray(payload?.bounds) ? payload.bounds : null;
        const bounds = rawBounds && rawBounds.length === 4 && rawBounds.every(value => Number.isFinite(Number(value)))
            ? rawBounds.map(Number)
            : null;
        const minzoom = Number.isFinite(Number(payload?.minzoom)) ? Number(payload.minzoom) : null;
        const maxzoom = Number.isFinite(Number(payload?.maxzoom)) ? Number(payload.maxzoom) : null;
        return { bounds, minzoom, maxzoom };
    } catch (error) {
        console.warn('Fetch TileJSON failed:', error);
        return null;
    }
}

const previewConfig = computed(() => {
    const publication = props.publication || {};
    const publishMethod = String(publication?.metadata?.publishMethod || publication?.publishMethod || '').trim().toLowerCase();
    const tileScheme = getPublicationTileScheme(publication);
    const sourceProjection = normalizeProjection(publication?.sourceProjection || publication?.metadata?.sourceProjection || publication?.customMetadata?.sourceProjection);
    const sampleTile = parseSampleTile(publication?.sampleUrl);
    const vectorBounds = Array.isArray(publication?.vectorPublication?.bounds) ? publication.vectorPublication.bounds : null;

    if (RASTER_METHODS.includes(publishMethod) && publication?.accessUrl) {
        return {
            supported: true,
            mode: 'imagery',
            title: 'Cesium 影像预览',
            description: `使用 Cesium 按 ${tileScheme.toUpperCase()} 规则请求影像瓦片。`,
            url: String(publication.accessUrl).trim(),
            tileJsonUrl: String(publication?.launchUrl || '').trim(),
            tileScheme,
            sourceProjection,
            sampleTile,
            bounds: vectorBounds
        };
    }

    if ((TERRAIN_METHODS.includes(publishMethod) || publication?.publishType === 'terrain')) {
        const terrainRootUrl = buildTerrainRootUrl(publication);
        return {
            supported: Boolean(terrainRootUrl),
            mode: 'terrain',
            title: 'Cesium 地形预览',
            description: '使用 CesiumTerrainProvider 加载 Quantized Mesh / Cesium Terrain 地形数据。',
            url: terrainRootUrl,
            sampleTile,
            bounds: vectorBounds
        };
    }

    if ((TILES_3D_METHODS.includes(publishMethod) || publication?.publishType === '3dtiles') && publication?.launchUrl) {
        return {
            supported: true,
            mode: '3dtiles',
            title: 'Cesium 3D Tiles 预览',
            description: '使用 Cesium3DTileset 加载 tileset.json。',
            url: String(publication.launchUrl).trim(),
            sampleTile,
            bounds: vectorBounds
        };
    }

    if (VECTOR_MVT_METHODS.includes(publishMethod) || VECTOR_GEOJSON_METHODS.includes(publishMethod)) {
        return {
            supported: false,
            mode: 'vector',
            title: '暂不支持内置预览',
            description: '当前二维矢量瓦片暂未接入 Cesium 内置预览，请直接使用发布地址验证。',
            url: String(publication?.accessUrl || '').trim()
        };
    }

    return {
        supported: false,
        mode: '',
        title: '暂不支持预览',
        description: '当前发布类型没有可用的 Cesium 内置预览。',
        url: String(publication?.accessUrl || '').trim()
    };
});

function close() {
    emit('update:modelValue', false);
}

async function ensureCesium() {
    if (!cesiumLibPromise) {
        window.CESIUM_BASE_URL = '/static/cesium';
        cesiumLibPromise = import('cesium');
    }
    return cesiumLibPromise;
}

function destroyViewer() {
    if (viewerInstance) {
        viewerInstance.destroy();
        viewerInstance = null;
    }
    previewReady.value = false;
    activeCesium = null;
}

async function createViewer(Cesium) {
    if (!viewerContainer.value) return null;

    const viewer = new Cesium.Viewer(viewerContainer.value, {
        sceneMode: Cesium.SceneMode.SCENE3D,
        animation: false,
        timeline: false,
        baseLayerPicker: false,
        geocoder: false,
        homeButton: false,
        sceneModePicker: false,
        navigationHelpButton: false,
        fullscreenButton: false,
        selectionIndicator: false,
        infoBox: false,
        shouldAnimate: false
    });

    viewer.imageryLayers.removeAll();
    viewer.scene.globe.depthTestAgainstTerrain = false;
    viewer.scene.skyAtmosphere.show = true;
    viewer.scene.globe.showGroundAtmosphere = true;
    viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString('#d9e7f5');
    viewer.scene.backgroundColor = Cesium.Color.fromCssColorString('#d9e7f5');
    viewer.scene.screenSpaceCameraController.enableCollisionDetection = false;
    viewer.scene.screenSpaceCameraController.maximumZoomDistance = 40000000;

    return viewer;
}

function setDefaultCamera(Cesium, viewer) {
    viewer.camera.setView({
        destination: Cesium.Cartesian3.fromDegrees(110, 24, 26000000),
        orientation: {
            heading: 0,
            pitch: -Cesium.Math.PI_OVER_TWO,
            roll: 0
        }
    });
    viewer.scene.requestRender();
}

async function resolveFocusBounds(config) {
    let bounds = Array.isArray(config.bounds) && config.bounds.length === 4 ? config.bounds : null;
    if (!bounds && config.tileJsonUrl) {
        const metadata = await fetchTileJsonMetadata(config.tileJsonUrl);
        if (metadata?.bounds) {
            bounds = metadata.bounds;
        }
    }
    return bounds;
}

async function focusViewer(Cesium, viewer, config, duration = 0) {
    const bounds = await resolveFocusBounds(config);
    if (bounds) {
        const rectangle = Cesium.Rectangle.fromDegrees(bounds[0], bounds[1], bounds[2], bounds[3]);
        viewer.camera.flyTo({
            destination: rectangle,
            duration
        });
        return true;
    }

    if (config.sampleTile) {
        const xyzY = config.tileScheme === 'tms'
            ? (2 ** config.sampleTile.z) - config.sampleTile.y - 1
            : config.sampleTile.y;
        const [west, north] = tileToLonLat(config.sampleTile.z, config.sampleTile.x, xyzY);
        const [east, south] = tileToLonLat(config.sampleTile.z, config.sampleTile.x + 1, xyzY + 1);
        viewer.camera.flyTo({
            destination: Cesium.Rectangle.fromDegrees(west, south, east, north),
            duration
        });
        return true;
    }

    setDefaultCamera(Cesium, viewer);
    return false;
}

async function addWorldBaseLayer(Cesium, viewer) {
    const provider = new Cesium.UrlTemplateImageryProvider({
        url: '/static/basemap/global-imagery/{z}/{x}/{y}.jpeg',
        tilingScheme: new Cesium.WebMercatorTilingScheme(),
        minimumLevel: 0,
        credit: 'AtlasWorks Global Imagery'
    });
    const label = '内置全球遥感底图';

    provider.errorEvent.addEventListener(error => {
        console.error('World basemap tile failed:', error);
        previewStatus.value = `底图加载失败: ${error?.message || `${label} 请求异常`}`;
    });

    viewer.imageryLayers.addImageryProvider(provider);
    return label;
}

async function renderImageryPreview(Cesium, viewer, config) {
    const bounds = await resolveFocusBounds(config);
    const tilingScheme = config.sourceProjection === 'EPSG:4326'
        ? new Cesium.GeographicTilingScheme({
            numberOfLevelZeroTilesX: 2,
            numberOfLevelZeroTilesY: 1
        })
        : new Cesium.WebMercatorTilingScheme();
    const imageryProvider = new Cesium.UrlTemplateImageryProvider({
        url: toCesiumImageryTemplate(config.url, config.tileScheme),
        tilingScheme,
        rectangle: bounds ? Cesium.Rectangle.fromDegrees(bounds[0], bounds[1], bounds[2], bounds[3]) : undefined,
        credit: 'AtlasWorks'
    });
    const overlay = viewer.imageryLayers.addImageryProvider(imageryProvider);
    overlay.alpha = 1;
}

async function renderTerrainPreview(Cesium, viewer, config) {
    viewer.terrainProvider = await Cesium.CesiumTerrainProvider.fromUrl(config.url);
    await focusViewer(Cesium, viewer, config);
}

async function renderTilesetPreview(Cesium, viewer, config) {
    const tileset = await Cesium.Cesium3DTileset.fromUrl(config.url);
    viewer.scene.primitives.add(tileset);
    await viewer.zoomTo(tileset);
}

async function renderPreview() {
    destroyViewer();
    previewStatus.value = '';

    if (!props.modelValue || !previewConfig.value.supported) {
        return;
    }

    await nextTick();
    if (!viewerContainer.value) return;

    try {
        const Cesium = await ensureCesium();
        const viewer = await createViewer(Cesium);
        if (!viewer) return;

        viewerInstance = viewer;
        activeCesium = Cesium;
        const baseLayerLabel = await addWorldBaseLayer(Cesium, viewer);
        setDefaultCamera(Cesium, viewer);

        if (previewConfig.value.mode === 'imagery') {
            await renderImageryPreview(Cesium, viewer, previewConfig.value);
        } else if (previewConfig.value.mode === 'terrain') {
            await renderTerrainPreview(Cesium, viewer, previewConfig.value);
        } else if (previewConfig.value.mode === '3dtiles') {
            await renderTilesetPreview(Cesium, viewer, previewConfig.value);
        }

        previewReady.value = true;
        previewStatus.value = `${previewConfig.value.description} 当前底图：${baseLayerLabel}`;
    } catch (error) {
        console.error('Publication preview failed:', error);
        previewStatus.value = `预览加载失败: ${error.message}`;
    }
}

async function flyToRegion() {
    if (!viewerInstance || !activeCesium || !previewConfig.value.supported) return;
    await focusViewer(activeCesium, viewerInstance, previewConfig.value, 0.8);
}

function switchSceneMode(mode) {
    if (!viewerInstance || !activeCesium) return;
    sceneMode.value = mode;
    if (mode === '3d') {
        viewerInstance.scene.morphTo3D(0.6);
    } else {
        viewerInstance.scene.morphTo2D(0.6);
    }
}

watch(
    () => [props.modelValue, props.publication],
    async () => {
        if (props.modelValue) {
            await renderPreview();
        } else {
            destroyViewer();
        }
    },
    { deep: true, flush: 'post' }
);

onBeforeUnmount(() => {
    destroyViewer();
});
</script>

<template>
    <ResizableDrawer
        :model-value="modelValue"
        title="发布预览"
        :width="1120"
        :min-width="720"
        :max-width="1600"
        destroy-on-close
        @update:model-value="value => emit('update:modelValue', value)"
    >
        <div class="preview-dialog-body">
            <div class="preview-toolbar">
                <div>
                    <div class="preview-title">{{ publication?.alias || '未命名发布' }}</div>
                    <div class="preview-subtitle">{{ previewConfig.title }}</div>
                </div>
                <div class="preview-toolbar-actions">
                    <div v-if="previewConfig.supported" class="scene-mode-switch">
                        <el-button
                            :type="sceneMode === '2d' ? 'primary' : 'default'"
                            plain
                            :icon="Monitor"
                            @click="switchSceneMode('2d')"
                        >
                            2D
                        </el-button>
                        <el-button
                            :type="sceneMode === '3d' ? 'primary' : 'default'"
                            plain
                            :icon="Orange"
                            @click="switchSceneMode('3d')"
                        >
                            3D
                        </el-button>
                    </div>
                    <el-button
                        v-if="previewConfig.supported"
                        type="primary"
                        plain
                        :icon="Aim"
                        :disabled="!previewReady"
                        @click="flyToRegion"
                    >
                        飞到区域
                    </el-button>
                    <el-tag v-if="previewConfig.supported" type="success">可预览</el-tag>
                    <el-tag v-else type="info">暂不支持</el-tag>
                </div>
            </div>

            <el-alert
                :title="previewConfig.description"
                :closable="false"
                type="info"
                show-icon
            />

            <div v-if="previewConfig.supported" class="preview-map-shell">
                <div ref="viewerContainer" class="preview-map" />
            </div>
            <el-empty v-else description="当前发布类型还没有内置预览器" />

            <div v-if="previewStatus" class="preview-status">{{ previewStatus }}</div>
        </div>
    </ResizableDrawer>
</template>

<style scoped>
.preview-dialog-body {
    display: flex;
    flex-direction: column;
    gap: 14px;
}

.preview-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}

.preview-toolbar-actions {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    justify-content: flex-end;
}

.scene-mode-switch {
    display: inline-flex;
    align-items: center;
    gap: 8px;
}

.preview-title {
    font-size: 18px;
    font-weight: 600;
    color: var(--tf-text-primary);
}

.preview-subtitle {
    margin-top: 4px;
    color: var(--tf-text-secondary);
    font-size: 13px;
}

.preview-map-shell {
    overflow: hidden;
    border: 1px solid var(--tf-border);
    border-radius: 14px;
    background: #d9e7f5;
}

.preview-map {
    width: 100%;
    height: 640px;
}

.preview-status {
    color: var(--tf-text-secondary);
    font-size: 13px;
}

.preview-map :deep(.cesium-viewer-bottom) {
    display: none;
}
</style>
