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

const GEOSERVER_METHODS = ['geoserver-wms', 'geoserver-wmts'];
const RASTER_METHODS = ['xyz', 'tms', ...GEOSERVER_METHODS];
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
    if (publishMethod === 'xyz' || publishMethod === 'wmts' || GEOSERVER_METHODS.includes(publishMethod)) return 'xyz';
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

function normalizeWgs84Bounds(bounds) {
    if (!Array.isArray(bounds) || bounds.length !== 4) return null;
    const values = bounds.map(value => Number(value));
    if (values.some(value => !Number.isFinite(value))) return null;
    const [west, south, east, north] = values;
    if (west < -180 || east > 180 || south < -90 || north > 90) return null;
    const normalized = [
        Math.max(-180, Math.min(180, west)),
        Math.max(-85.05112878, Math.min(85.05112878, south)),
        Math.max(-180, Math.min(180, east)),
        Math.max(-85.05112878, Math.min(85.05112878, north))
    ];
    if (normalized[0] >= normalized[2] || normalized[1] >= normalized[3]) return null;
    return normalized;
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

function normalizeGeoserverWmtsTemplate(url) {
    const value = String(url || '').trim();
    if (!value) return '';
    try {
        const parsed = new URL(value, window.location.origin);
        const service = String(parsed.searchParams.get('SERVICE') || '').toUpperCase();
        const request = String(parsed.searchParams.get('REQUEST') || '').toUpperCase();
        if (service === 'WMTS' && request === 'GETTILE') {
            parsed.searchParams.set('TILEMATRIXSET', 'EPSG:900913');
            const matrix = parsed.searchParams.get('TILEMATRIX') || '{z}';
            if (matrix === '{z}' || /^\d+$/.test(matrix)) {
                parsed.searchParams.set('TILEMATRIX', `EPSG:900913:${matrix}`);
            }
        }
        return parsed.toString().replace(/%7B/ig, '{').replace(/%7D/ig, '}');
    } catch {
        return value
            .replace(/TILEMATRIXSET=EPSG:3857/ig, 'TILEMATRIXSET=EPSG:900913')
            .replace(/TILEMATRIX=\{z\}/ig, 'TILEMATRIX=EPSG:900913:{z}');
    }
}

function buildGeoserverWmtsTemplates(publication) {
    const metadata = publication?.metadata || {};
    const customMetadata = publication?.customMetadata || metadata?.customMetadata || {};
    const layerNames = Array.isArray(metadata.geoserverLayerNames) && metadata.geoserverLayerNames.length
        ? metadata.geoserverLayerNames
        : (Array.isArray(customMetadata.geoserverLayerNames) ? customMetadata.geoserverLayerNames : []);
    const workspace = String(metadata.geoserverWorkspace || customMetadata.geoserverWorkspace || 'atlasworks').trim() || 'atlasworks';
    const template = normalizeGeoserverWmtsTemplate(publication?.wmtsTileUrl || publication?.accessUrl || '');
    if (!template) return [];
    if (!layerNames.length) return [template];
    return layerNames
        .map(name => String(name || '').trim())
        .filter(Boolean)
        .map(name => template.replace(/LAYER=([^&]*)/i, `LAYER=${encodeURIComponent(`${workspace}:${name}`).replace('%3A', ':')}`));
}

function parseWmsPreviewUrl(url) {
    const value = String(url || '').trim();
    if (!value) return null;
    try {
        const parsed = new URL(value, window.location.origin);
        const layers = parsed.searchParams.get('LAYERS') || parsed.searchParams.get('layers') || '';
        const styles = parsed.searchParams.get('STYLES') || parsed.searchParams.get('styles') || '';
        const format = parsed.searchParams.get('FORMAT') || parsed.searchParams.get('format') || 'image/png';
        const transparent = parsed.searchParams.get('TRANSPARENT') || parsed.searchParams.get('transparent') || 'true';
        parsed.search = '';
        return {
            url: parsed.toString(),
            layers,
            parameters: {
                transparent,
                format,
                styles
            }
        };
    } catch (error) {
        console.warn('Parse WMS preview URL failed:', error);
        return null;
    }
}

async function fetchTileJsonMetadata(url) {
    const target = String(url || '').trim();
    if (!target || !/tilejson\.json(\?|$)/i.test(target)) return null;
    try {
        const response = await fetch(target);
        if (!response.ok) return null;
        const payload = await response.json();
        const rawBounds = Array.isArray(payload?.bounds) ? payload.bounds : null;
        const bounds = normalizeWgs84Bounds(rawBounds);
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
    const vectorBounds = normalizeWgs84Bounds(publication?.vectorPublication?.bounds);
    const publicationBounds = normalizeWgs84Bounds(publication?.bounds)
        || normalizeWgs84Bounds(publication?.metadata?.bounds)
        || normalizeWgs84Bounds(publication?.customMetadata?.bounds)
        || normalizeWgs84Bounds(publication?.metadata?.customMetadata?.bounds);
    const focusBounds = vectorBounds || publicationBounds;

    if (GEOSERVER_METHODS.includes(publishMethod) && (publication?.wmtsTileUrl || publication?.accessUrl || publication?.wmsUrl)) {
        const wmtsTemplates = buildGeoserverWmtsTemplates(publication);
        const wmsConfig = parseWmsPreviewUrl(publication?.wmsUrl);
        return {
            supported: true,
            mode: wmtsTemplates.length ? 'wmts-imagery' : (wmsConfig ? 'wms-imagery' : 'imagery'),
            title: 'Cesium 影像预览',
            description: wmtsTemplates.length
                ? '使用 GeoServer GWC/WMTS 缓存瓦片预览；首次访问会生成缓存，后续会更快。'
                : wmsConfig
                    ? '使用 GeoServer WMS 动态请求影像图层，性能取决于源 TIFF 读取和重采样。'
                : `使用 Cesium 按 ${tileScheme.toUpperCase()} 规则请求影像瓦片。`,
            url: wmtsTemplates[0] || (wmsConfig ? wmsConfig.url : String(publication.accessUrl).trim()),
            wmtsTemplates,
            wmsConfig,
            tileJsonUrl: String(publication?.launchUrl || '').trim(),
            tileScheme,
            sourceProjection,
            sampleTile,
            bounds: focusBounds
        };
    }

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
            bounds: focusBounds
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
            bounds: focusBounds
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
            bounds: focusBounds
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
        baseLayer: false,
        terrainProvider: new Cesium.EllipsoidTerrainProvider(),
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
    viewer.scene.globe.show = true;
    viewer.scene.globe.depthTestAgainstTerrain = false;
    viewer.scene.skyAtmosphere.show = true;
    viewer.scene.globe.showGroundAtmosphere = true;
    viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString('#000000');
    viewer.scene.backgroundColor = Cesium.Color.fromCssColorString('#000000');
    viewer.scene.screenSpaceCameraController.enableCollisionDetection = false;
    viewer.scene.screenSpaceCameraController.maximumZoomDistance = 40000000;
    viewer.resize();
    viewer.scene.requestRender();

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

function boundsCameraDestination(Cesium, bounds, options = {}) {
    const normalized = normalizeWgs84Bounds(bounds);
    if (!normalized) return null;
    const [west, south, east, north] = normalized;
    const centerLon = (west + east) / 2;
    const centerLat = (south + north) / 2;
    const widthMeters = Math.abs(east - west) * 111320 * Math.max(0.2, Math.cos(Cesium.Math.toRadians(centerLat)));
    const heightMeters = Math.abs(north - south) * 110540;
    const rangeMeters = Math.max(widthMeters, heightMeters);
    const minAltitude = Number.isFinite(Number(options.minAltitude)) ? Number(options.minAltitude) : 12000;
    const altitude = Math.max(minAltitude, Math.min(26000000, rangeMeters * 2.6));
    return Cesium.Cartesian3.fromDegrees(centerLon, centerLat, altitude);
}

function boundsSpanDegrees(bounds) {
    const normalized = normalizeWgs84Bounds(bounds);
    if (!normalized) return null;
    return {
        lon: Math.abs(normalized[2] - normalized[0]),
        lat: Math.abs(normalized[3] - normalized[1])
    };
}

function sampleTileBounds(config) {
    if (!config.sampleTile) return null;
    const xyzY = config.tileScheme === 'tms'
        ? (2 ** config.sampleTile.z) - config.sampleTile.y - 1
        : config.sampleTile.y;
    const [west, north] = tileToLonLat(config.sampleTile.z, config.sampleTile.x, xyzY);
    const [east, south] = tileToLonLat(config.sampleTile.z, config.sampleTile.x + 1, xyzY + 1);
    return [west, south, east, north];
}

function shouldUseSampleTileFocus(bounds, config) {
    if (!config.sampleTile) return false;
    const span = boundsSpanDegrees(bounds);
    if (!span) return true;
    return span.lon > 20 || span.lat > 12;
}

async function resolveFocusBounds(config) {
    let bounds = normalizeWgs84Bounds(config.bounds);
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
    const focusBounds = bounds && !shouldUseSampleTileFocus(bounds, config)
        ? bounds
        : sampleTileBounds(config);
    if (focusBounds) {
        const destination = boundsCameraDestination(Cesium, focusBounds, {
            minAltitude: focusBounds === bounds ? 12000 : 1400000
        });
        if (!destination) {
            setDefaultCamera(Cesium, viewer);
            return false;
        }
        viewer.camera.flyTo({
            destination,
            orientation: {
                heading: 0,
                pitch: Cesium.Math.toRadians(-90),
                roll: 0
            },
            duration
        });
        return true;
    }

    setDefaultCamera(Cesium, viewer);
    return false;
}

async function addWorldBaseLayer(Cesium, viewer) {
    try {
        const provider = await Cesium.TileMapServiceImageryProvider.fromUrl(
            Cesium.buildModuleUrl('Assets/Textures/NaturalEarthII')
        );
        viewer.imageryLayers.addImageryProvider(provider);
        return 'Cesium 内置全球底图';
    } catch (localError) {
        console.warn('Local NaturalEarthII basemap failed, fallback to OpenStreetMap:', localError);
        const provider = new Cesium.UrlTemplateImageryProvider({
            url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
            tilingScheme: new Cesium.WebMercatorTilingScheme(),
            minimumLevel: 0,
            maximumLevel: 19,
            credit: 'OpenStreetMap'
        });
        provider.errorEvent.addEventListener(error => {
            console.warn('Online basemap tile failed:', error);
            previewStatus.value = `底图加载失败: ${error?.message || '本地和在线底图都不可用'}`;
        });
        viewer.imageryLayers.addImageryProvider(provider);
        return 'OpenStreetMap 全球底图';
    }
}

async function renderImageryPreview(Cesium, viewer, config) {
    const resolvedBounds = await resolveFocusBounds(config);
    const bounds = resolvedBounds && !shouldUseSampleTileFocus(resolvedBounds, config) ? resolvedBounds : undefined;
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

async function renderWmtsImageryPreview(Cesium, viewer, config) {
    const templates = Array.isArray(config.wmtsTemplates) && config.wmtsTemplates.length
        ? config.wmtsTemplates
        : [config.url].filter(Boolean);
    const resolvedBounds = await resolveFocusBounds(config);
    const bounds = resolvedBounds && !shouldUseSampleTileFocus(resolvedBounds, config) ? resolvedBounds : undefined;
    const tilingScheme = new Cesium.WebMercatorTilingScheme();
    templates.forEach(template => {
        const imageryProvider = new Cesium.UrlTemplateImageryProvider({
            url: toCesiumImageryTemplate(template, 'xyz'),
            tilingScheme,
            rectangle: bounds ? Cesium.Rectangle.fromDegrees(bounds[0], bounds[1], bounds[2], bounds[3]) : undefined,
            credit: 'GeoServer GWC'
        });
        const overlay = viewer.imageryLayers.addImageryProvider(imageryProvider);
        overlay.alpha = 1;
    });
}

async function renderWmsImageryPreview(Cesium, viewer, config) {
    const wmsConfig = config.wmsConfig;
    if (!wmsConfig?.url || !wmsConfig?.layers) {
        await renderImageryPreview(Cesium, viewer, config);
        return;
    }
    const resolvedBounds = await resolveFocusBounds(config);
    const bounds = resolvedBounds && !shouldUseSampleTileFocus(resolvedBounds, config) ? resolvedBounds : undefined;
    const imageryProvider = new Cesium.WebMapServiceImageryProvider({
        url: wmsConfig.url,
        layers: wmsConfig.layers,
        parameters: {
            transparent: true,
            format: 'image/png',
            ...wmsConfig.parameters
        },
        rectangle: bounds ? Cesium.Rectangle.fromDegrees(bounds[0], bounds[1], bounds[2], bounds[3]) : undefined,
        credit: 'GeoServer'
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
        await addWorldBaseLayer(Cesium, viewer);
        setDefaultCamera(Cesium, viewer);

        if (previewConfig.value.mode === 'wmts-imagery') {
            await renderWmtsImageryPreview(Cesium, viewer, previewConfig.value);
        } else if (previewConfig.value.mode === 'wms-imagery') {
            await renderWmsImageryPreview(Cesium, viewer, previewConfig.value);
        } else if (previewConfig.value.mode === 'imagery') {
            await renderImageryPreview(Cesium, viewer, previewConfig.value);
        } else if (previewConfig.value.mode === 'terrain') {
            await renderTerrainPreview(Cesium, viewer, previewConfig.value);
        } else if (previewConfig.value.mode === '3dtiles') {
            await renderTilesetPreview(Cesium, viewer, previewConfig.value);
        }

        previewReady.value = true;
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
        overlay-class="publication-preview-overlay"
        overlay-background="rgba(0, 0, 0, 0.88)"
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
                    <el-tag v-else type="info">暂不支持</el-tag>
                </div>
            </div>

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
    background: #000000;
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

:global(.publication-preview-overlay) {
    background: rgba(0, 0, 0, 0.88) !important;
}
</style>
