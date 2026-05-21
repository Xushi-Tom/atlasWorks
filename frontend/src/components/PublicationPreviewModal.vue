<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import 'ol/ol.css';
import { Aim, Monitor, Orange } from '@element-plus/icons-vue';
import Map from 'ol/Map';
import View from 'ol/View';
import TileLayer from 'ol/layer/Tile';
import VectorTileLayer from 'ol/layer/VectorTile';
import XYZ from 'ol/source/XYZ';
import VectorTileSource from 'ol/source/VectorTile';
import MVT from 'ol/format/MVT';
import GeoJSON from 'ol/format/GeoJSON';
import { Fill, Stroke, Style, Circle as CircleStyle } from 'ol/style';
import { fromLonLat, transformExtent } from 'ol/proj';
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
const vectorContainer = ref(null);
const previewStatus = ref('');
const previewReady = ref(false);
const sceneMode = ref('3d');

let viewerInstance = null;
let vectorMapInstance = null;
let cesiumLibPromise = null;
let activeCesium = null;
let vectorResizeObserver = null;
let vectorRefreshTimers = [];
let vectorRetryTimer = null;

const GEOSERVER_METHODS = ['geoserver-wms', 'geoserver-wmts'];
const RASTER_METHODS = ['xyz', 'tms', ...GEOSERVER_METHODS];
const TERRAIN_METHODS = ['cesium-terrain', 'quantized-mesh', 'terrain'];
const VECTOR_MVT_METHODS = ['mvt', 'mvt-xyz', 'mvt-tms', 'vector-tile', 'vector-tiles', 'mbtiles-mvt', 'mvt-dynamic', 'dynamic-mvt'];
const VECTOR_GEOJSON_METHODS = ['geojson-tile', 'geojson-tiles'];
const TILES_3D_METHODS = ['3d-tiles'];
const WEB_MERCATOR_EXTENT = [-20037508.342789244, -20037508.342789244, 20037508.342789244, 20037508.342789244];

const vectorPointStyle = new Style({
    image: new CircleStyle({
        radius: 4,
        fill: new Fill({ color: 'rgba(87, 210, 255, 0.92)' }),
        stroke: new Stroke({ color: 'rgba(7, 23, 36, 0.95)', width: 1.2 })
    })
});

const vectorLineStyle = new Style({
    stroke: new Stroke({
        color: 'rgba(87, 210, 255, 0.95)',
        width: 1.8
    })
});

const vectorPolygonStyle = new Style({
    fill: new Fill({ color: 'rgba(87, 210, 255, 0.18)' }),
    stroke: new Stroke({ color: 'rgba(87, 210, 255, 0.95)', width: 1.4 })
});

const vectorFallbackStyle = new Style({
    stroke: new Stroke({
        color: 'rgba(87, 210, 255, 0.95)',
        width: 1.4
    }),
    fill: new Fill({ color: 'rgba(87, 210, 255, 0.12)' }),
    image: new CircleStyle({
        radius: 3,
        fill: new Fill({ color: 'rgba(87, 210, 255, 0.92)' })
    })
});

function normalizeTileScheme(value) {
    const scheme = String(value || '').trim().toLowerCase();
    if (scheme === 'xyz' || scheme === 'google') return 'xyz';
    return 'tms';
}

function getPublicationTileScheme(publication) {
    const publishMethod = String(publication?.metadata?.publishMethod || publication?.publishMethod || '').trim().toLowerCase();
    if (
        publishMethod === 'xyz'
        || publishMethod === 'wmts'
        || publishMethod === 'mvt-xyz'
        || publishMethod === 'mbtiles-mvt'
        || publishMethod === 'mvt-dynamic'
        || publishMethod === 'dynamic-mvt'
        || GEOSERVER_METHODS.includes(publishMethod)
    ) return 'xyz';
    if (publishMethod === 'tms' || publishMethod === 'mvt-tms') return 'tms';
    return normalizeTileScheme(
        publication?.vectorPublication?.scheme
        || publication?.metadata?.tileScheme
        || publication?.customMetadata?.tileScheme
        || publication?.metadata?.sourceTileScheme
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

function tileTemplateForOpenLayers(url, tileScheme = 'xyz') {
    const value = String(url || '').trim();
    if (!value) return '';
    if (tileScheme === 'tms') {
        return value.replace('{reverseY}', '{-y}').replace('{y}', '{-y}');
    }
    return value.replace('{reverseY}', '{y}');
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

function getVectorStyle(feature) {
    const geometry = feature?.getGeometry?.();
    const type = geometry?.getType?.() || '';
    if (type.includes('Point')) return vectorPointStyle;
    if (type.includes('LineString')) return vectorLineStyle;
    if (type.includes('Polygon')) return vectorPolygonStyle;
    return vectorFallbackStyle;
}

function getStaticAssetUrl(path) {
    const normalized = String(path || '').replace(/^\/+/, '');
    return `${window.location.origin}/static/${normalized}`;
}

function replaceTileTokens(url, replacements = {}) {
    let result = String(url || '').trim();
    Object.entries(replacements).forEach(([key, value]) => {
        result = result.replaceAll(`{${key}}`, String(value));
    });
    return result;
}

function buildVectorTileUrl(config, z, x, y) {
    const normalizedY = config.tileScheme === 'tms'
        ? ((2 ** z) - y - 1)
        : y;
    return replaceTileTokens(config.url, {
        z,
        x,
        y: normalizedY,
        reverseY: (2 ** z) - y - 1
    });
}

function describeVectorSource(config) {
    const url = String(config?.url || '').trim();
    if (!url) return '';
    try {
        const parsed = new URL(url, window.location.origin);
        return `${config?.tileScheme?.toUpperCase?.() || 'XYZ'} · ${parsed.origin}${parsed.pathname}`;
    } catch {
        return `${config?.tileScheme?.toUpperCase?.() || 'XYZ'} · ${url}`;
    }
}

const previewConfig = computed(() => {
    const publication = props.publication || {};
    const vectorPublication = publication?.vectorPublication || {};
    const publishMethod = String(publication?.metadata?.publishMethod || publication?.publishMethod || '').trim().toLowerCase();
    const tileScheme = getPublicationTileScheme(publication);
    const sourceProjection = normalizeProjection(publication?.sourceProjection || publication?.metadata?.sourceProjection || publication?.customMetadata?.sourceProjection);
    const sampleTile = parseSampleTile(vectorPublication?.sampleTileUrl || publication?.sampleUrl);
    const vectorBounds = normalizeWgs84Bounds(vectorPublication?.bounds);
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
            engine: 'cesium',
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
            engine: 'cesium',
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
            engine: 'cesium',
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
            engine: 'cesium',
            mode: '3dtiles',
            title: 'Cesium 3D Tiles 预览',
            description: '使用 Cesium3DTileset 加载 tileset.json。',
            url: String(publication.launchUrl).trim(),
            sampleTile,
            bounds: focusBounds
        };
    }

    if (VECTOR_MVT_METHODS.includes(publishMethod)) {
        return {
            supported: Boolean(vectorPublication.xyzTemplate || publication?.accessUrl),
            engine: 'ol',
            mode: 'vector-mvt',
            title: 'MVT 矢量瓦片预览',
            description: '在发布预览中直接加载 MVT / PBF 瓦片，便于快速验证样式、范围和层级可用性。',
            url: String(vectorPublication.xyzTemplate || publication?.accessUrl || '').trim(),
            tileJsonUrl: String(vectorPublication.tileJsonUrl || publication?.launchUrl || '').trim(),
            tileScheme,
            sampleTile,
            bounds: focusBounds
        };
    }

    if (VECTOR_GEOJSON_METHODS.includes(publishMethod)) {
        return {
            supported: Boolean(vectorPublication.xyzTemplate || publication?.accessUrl),
            engine: 'ol',
            mode: 'vector-geojson',
            title: 'GeoJSON 瓦片预览',
            description: '在发布预览中直接加载 GeoJSON 瓦片，适合快速验证切片结果与范围。',
            url: String(vectorPublication.xyzTemplate || publication?.accessUrl || '').trim(),
            tileJsonUrl: String(vectorPublication.tileJsonUrl || publication?.launchUrl || '').trim(),
            tileScheme,
            sampleTile,
            bounds: focusBounds
        };
    }

    return {
        supported: false,
        engine: '',
        mode: '',
        title: '暂不支持预览',
        description: '当前发布类型没有可用的 Cesium 内置预览。',
        url: String(publication?.accessUrl || '').trim()
    };
});

const previewRenderSignature = computed(() => {
    const publication = props.publication || {};
    const vectorPublication = publication?.vectorPublication || {};
    return JSON.stringify({
        publicationId: publication?.publicationId || publication?.id || '',
        publishType: publication?.publishType || '',
        publishMethod: publication?.publishMethod || publication?.metadata?.publishMethod || '',
        accessUrl: publication?.accessUrl || '',
        launchUrl: publication?.launchUrl || '',
        sampleUrl: publication?.sampleUrl || '',
        wmsUrl: publication?.wmsUrl || '',
        wmtsTileUrl: publication?.wmtsTileUrl || '',
        vectorXyzTemplate: vectorPublication?.xyzTemplate || '',
        vectorTileJsonUrl: vectorPublication?.tileJsonUrl || '',
        vectorSampleTileUrl: vectorPublication?.sampleTileUrl || '',
        vectorScheme: vectorPublication?.scheme || '',
        bounds: vectorPublication?.bounds || publication?.bounds || publication?.metadata?.bounds || null,
    });
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
    if (vectorResizeObserver) {
        vectorResizeObserver.disconnect();
        vectorResizeObserver = null;
    }
    vectorRefreshTimers.forEach(timer => window.clearTimeout(timer));
    vectorRefreshTimers = [];
    if (vectorRetryTimer) {
        window.clearTimeout(vectorRetryTimer);
        vectorRetryTimer = null;
    }
    if (vectorMapInstance) {
        vectorMapInstance.setTarget(undefined);
        vectorMapInstance = null;
    }
    previewReady.value = false;
    activeCesium = null;
}

async function waitForRenderableContainer(element, timeoutMs = 1200) {
    const startedAt = Date.now();
    while (element && (Date.now() - startedAt) < timeoutMs) {
        const width = Number(element.clientWidth || 0);
        const height = Number(element.clientHeight || 0);
        if (width > 0 && height > 0) return true;
        await new Promise(resolve => window.setTimeout(resolve, 60));
    }
    return Boolean(element && element.clientWidth > 0 && element.clientHeight > 0);
}

function scheduleVectorMapRefresh(config) {
    if (!vectorMapInstance) return;
    vectorRefreshTimers.forEach(timer => window.clearTimeout(timer));
    vectorRefreshTimers = [];

    [0, 160, 320, 640].forEach(delay => {
        const timer = window.setTimeout(async () => {
            if (!vectorMapInstance) return;
            vectorMapInstance.updateSize();
            vectorMapInstance.renderSync();
            if (delay >= 160) {
                await focusVectorPreview(config, 0);
            }
        }, delay);
        vectorRefreshTimers.push(timer);
    });
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

async function focusVectorPreview(config, duration = 250) {
    if (!vectorMapInstance) return;
    const bounds = await resolveFocusBounds(config);
    const focusBounds = bounds && !shouldUseSampleTileFocus(bounds, config)
        ? bounds
        : sampleTileBounds(config);
    const view = vectorMapInstance.getView();
    if (focusBounds) {
        view.fit(transformExtent(focusBounds, 'EPSG:4326', 'EPSG:3857'), {
            padding: [36, 36, 36, 36],
            duration,
            maxZoom: 7
        });
        return;
    }
    if (config.sampleTile) {
        const sampleY = config.tileScheme === 'tms'
            ? (2 ** config.sampleTile.z) - config.sampleTile.y - 1
            : config.sampleTile.y;
        const [west, north] = tileToLonLat(config.sampleTile.z, config.sampleTile.x, sampleY);
        const [east, south] = tileToLonLat(config.sampleTile.z, config.sampleTile.x + 1, sampleY + 1);
        view.fit(transformExtent([west, south, east, north], 'EPSG:4326', 'EPSG:3857'), {
            padding: [36, 36, 36, 36],
            duration,
            maxZoom: 7
        });
        return;
    }
    view.animate({
        center: fromLonLat([110, 24]),
        zoom: 3,
        duration
    });
}

async function renderVectorPreview(config) {
    if (!vectorContainer.value) return;
    await waitForRenderableContainer(vectorContainer.value);
    if (vectorResizeObserver) {
        vectorResizeObserver.disconnect();
        vectorResizeObserver = null;
    }
    if (vectorMapInstance) {
        vectorMapInstance.setTarget(undefined);
        vectorMapInstance = null;
    }

    const format = config.mode === 'vector-geojson'
        ? new GeoJSON()
        : new MVT();

    const olTemplateUrl = tileTemplateForOpenLayers(config.url, config.tileScheme);
    const source = new VectorTileSource({
        url: olTemplateUrl || undefined,
        format,
        projection: 'EPSG:3857'
    });

    const basemapUrl = getStaticAssetUrl('basemap/global-imagery/{z}/{x}/{y}.jpeg');
    const baseLayer = new TileLayer({
        source: new XYZ({
            url: basemapUrl,
            projection: 'EPSG:3857',
            minZoom: 0,
            maxZoom: 7,
            crossOrigin: 'anonymous',
            wrapX: true
        }),
        opacity: 0.88
    });

    const vectorLayer = new VectorTileLayer({
        source,
        style: getVectorStyle,
        renderMode: 'hybrid',
        declutter: true
    });

    let loadedTileCount = 0;
    let anyVectorTileRequest = false;
    source.on('tileloadend', () => {
        anyVectorTileRequest = true;
        loadedTileCount++;
        previewStatus.value = `已加载 ${loadedTileCount} 个矢量瓦片`;
    });
    source.on('tileloadstart', () => {
        anyVectorTileRequest = true;
        const requestSample = config.sampleTile
            ? buildVectorTileUrl(config, config.sampleTile.z, config.sampleTile.x, config.sampleTile.y)
            : olTemplateUrl;
        previewStatus.value = requestSample
            ? `正在请求矢量瓦片... ${describeVectorSource(config)} · 请求示例 ${requestSample}`
            : `正在请求矢量瓦片... ${describeVectorSource(config)}`;
    });
    source.on('tileloaderror', (event) => {
        anyVectorTileRequest = true;
        const coord = event.tile?.tileCoord;
        if (coord) {
            const [z, x, rawY] = coord;
            const y = -rawY - 1;
            console.warn(`MVT tile load failed: z=${z} x=${x} y=${y}`);
            previewStatus.value = `矢量瓦片加载失败: z=${z}, x=${x}, y=${y}`;
        } else {
            previewStatus.value = '矢量瓦片加载失败';
        }
    });

    baseLayer.getSource()?.on('imageloaderror', () => {
        previewStatus.value = '离线底图加载失败';
    });
    baseLayer.getSource()?.on('imageloadstart', () => {
        if (!previewStatus.value) {
            previewStatus.value = '正在加载预览底图...';
        }
    });

    vectorMapInstance = new Map({
        target: vectorContainer.value,
        layers: [baseLayer, vectorLayer],
        view: new View({
            center: fromLonLat([110, 24]),
            zoom: 3,
            minZoom: 1,
            maxZoom: 22,
            extent: WEB_MERCATOR_EXTENT
        }),
        controls: []
    });
    vectorMapInstance.once('postrender', async () => {
        if (!vectorMapInstance) return;
        vectorMapInstance.updateSize();
        vectorMapInstance.renderSync();
        await focusVectorPreview(config, 0);
    });

    if (typeof ResizeObserver !== 'undefined' && vectorContainer.value) {
        vectorResizeObserver = new ResizeObserver(() => {
            if (!vectorMapInstance) return;
            vectorMapInstance.updateSize();
            vectorMapInstance.renderSync();
        });
        vectorResizeObserver.observe(vectorContainer.value);
    }

    window.requestAnimationFrame(() => {
        if (!vectorMapInstance) return;
        vectorMapInstance.updateSize();
        vectorMapInstance.renderSync();
        source.refresh();
    });

    previewStatus.value = '正在加载矢量瓦片...';
    const sourceDescription = describeVectorSource(config);
    if (sourceDescription) {
        previewStatus.value = `正在加载矢量瓦片... ${sourceDescription}`;
    }
    scheduleVectorMapRefresh(config);
    await focusVectorPreview(config, 0);
    source.refresh();
    vectorRetryTimer = window.setTimeout(async () => {
        if (vectorMapInstance && !anyVectorTileRequest && !loadedTileCount) {
            if (!config.retry) {
                previewStatus.value = '首次渲染未触发请求，正在自动重试...';
                await renderVectorPreview({ ...config, retry: true });
                return;
            }
            previewStatus.value = '未触发矢量瓦片请求，请检查范围、缩放级别或发布地址';
        }
    }, 1200);
}

async function renderPreview() {
    destroyViewer();
    previewStatus.value = '';

    if (!props.modelValue || !previewConfig.value.supported) {
        return;
    }

    await nextTick();
    const isOl = previewConfig.value.engine === 'ol';
    if (isOl ? !vectorContainer.value : !viewerContainer.value) return;

    try {
        if (isOl) {
            await new Promise(resolve => window.setTimeout(resolve, 260));
            await renderVectorPreview(previewConfig.value);
        } else {
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
        }

        previewReady.value = true;
    } catch (error) {
        console.error('Publication preview failed:', error);
        previewStatus.value = `预览加载失败: ${error.message}`;
    }
}

async function flyToRegion() {
    if (!previewConfig.value.supported) return;
    if (previewConfig.value.engine === 'ol') {
        await focusVectorPreview(previewConfig.value, 350);
        return;
    }
    if (!viewerInstance || !activeCesium) return;
    await focusViewer(activeCesium, viewerInstance, previewConfig.value, 0.8);
}

function switchSceneMode(mode) {
    if (previewConfig.value.engine !== 'cesium' || !viewerInstance || !activeCesium) return;
    sceneMode.value = mode;
    if (mode === '3d') {
        viewerInstance.scene.morphTo3D(0.6);
    } else {
        viewerInstance.scene.morphTo2D(0.6);
    }
}

watch(
    () => [props.modelValue, previewRenderSignature.value],
    async () => {
        if (props.modelValue) {
            await renderPreview();
        } else {
            destroyViewer();
        }
    },
    { flush: 'post' }
);

onMounted(async () => {
    if (props.modelValue) {
        await nextTick();
        await renderPreview();
    }
});

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
                    <div v-if="previewConfig.supported && previewConfig.engine === 'cesium'" class="scene-mode-switch">
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
                    <el-tag v-if="previewConfig.supported && previewConfig.engine === 'ol'" type="success">MVT 预览</el-tag>
                    <el-tag v-else-if="!previewConfig.supported" type="info">暂不支持</el-tag>
                </div>
            </div>

            <div v-if="previewConfig.supported" class="preview-map-shell">
                <div v-if="previewConfig.engine === 'cesium'" ref="viewerContainer" class="preview-map" />
                <div v-else ref="vectorContainer" class="preview-map preview-map-vector" />
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

.preview-map-vector {
    position: relative;
    touch-action: none;
    cursor: grab;
    pointer-events: auto;
}

.preview-map-vector:active {
    cursor: grabbing;
}

.preview-map-vector :deep(.ol-viewport),
.preview-map-vector :deep(.ol-overlaycontainer-stopevent),
.preview-map-vector :deep(.ol-overlaycontainer) {
    width: 100%;
    height: 100%;
}

.preview-map-vector :deep(.ol-viewport) {
    touch-action: none;
}

.preview-map-vector :deep(canvas) {
    pointer-events: auto;
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
