<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import 'ol/ol.css';
import Map from 'ol/Map';
import View from 'ol/View';
import TileLayer from 'ol/layer/Tile';
import VectorLayer from 'ol/layer/Vector';
import VectorTileLayer from 'ol/layer/VectorTile';
import GeoJSON from 'ol/format/GeoJSON';
import MVT from 'ol/format/MVT';
import VectorSource from 'ol/source/Vector';
import VectorTileSource from 'ol/source/VectorTile';
import XYZ from 'ol/source/XYZ';
import { Circle as CircleStyle, Fill, Stroke, Style } from 'ol/style';
import { createXYZ } from 'ol/tilegrid';
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

const mapContainer = ref(null);
const previewStatus = ref('');
let mapInstance = null;

const VECTOR_MVT_METHODS = ['mvt', 'vector-tile', 'vector-tiles'];
const VECTOR_GEOJSON_METHODS = ['geojson-tile', 'geojson-tiles'];
const TITILER_METHODS = ['titiler-cog', 'titiler', 'cog'];

function normalizeTileScheme(value) {
    const scheme = String(value || '').trim().toLowerCase();
    if (scheme === 'google' || scheme === 'xyz') return 'xyz';
    return 'tms';
}

function getPublicationTileScheme(publication) {
    return normalizeTileScheme(
        publication?.metadata?.sourceTileScheme
        || publication?.customMetadata?.sourceTileScheme
        || publication?.sourceTileScheme
    );
}

function toPublishedTileY(z, y, tileScheme = 'xyz') {
    return tileScheme === 'tms' ? (2 ** z) - y - 1 : y;
}

function buildTileRequestUrl(url, z, x, y, tileScheme = 'xyz') {
    const actualY = toPublishedTileY(z, y, tileScheme);
    return String(url || '')
        .replace('{z}', String(z))
        .replace('{x}', String(x))
        .replace('{y}', String(actualY));
}

const vectorStyle = new Style({
    fill: new Fill({
        color: 'rgba(64, 158, 255, 0.22)'
    }),
    stroke: new Stroke({
        color: '#1d4ed8',
        width: 1.25
    }),
    image: new CircleStyle({
        radius: 4,
        fill: new Fill({
            color: '#2563eb'
        }),
        stroke: new Stroke({
            color: '#ffffff',
            width: 1.2
        })
    })
});

const previewConfig = computed(() => {
    const publication = props.publication || {};
    const publishMethod = String(publication?.metadata?.publishMethod || publication?.publishMethod || '').trim().toLowerCase();
    const accessUrl = String(publication?.accessUrl || '').trim();
    const bounds = publication?.vectorPublication?.bounds;
    const minZoom = Number(publication?.vectorPublication?.minzoom ?? 0);
    const maxZoom = Number(publication?.vectorPublication?.maxzoom ?? 14);
    const tileScheme = getPublicationTileScheme(publication);

    if (VECTOR_MVT_METHODS.includes(publishMethod) && accessUrl) {
        return {
            supported: true,
            mode: 'vector-mvt',
            title: 'OpenLayers 预览',
            description: `MVT 矢量瓦片，当前按 ${tileScheme.toUpperCase()} 行号规则请求。`,
            url: accessUrl,
            bounds,
            minZoom,
            maxZoom,
            tileScheme
        };
    }

    if (VECTOR_GEOJSON_METHODS.includes(publishMethod) && accessUrl) {
        return {
            supported: true,
            mode: 'vector-geojson',
            title: 'OpenLayers 预览',
            description: `GeoJSON 瓦片，按当前视域动态请求可见瓦片，当前按 ${tileScheme.toUpperCase()} 行号规则请求。`,
            url: accessUrl,
            bounds,
            minZoom,
            maxZoom,
            tileScheme
        };
    }

    if ((TITILER_METHODS.includes(publishMethod) || publishMethod === 'xyz' || publishMethod === 'tms') && accessUrl) {
        return {
            supported: true,
            mode: 'raster-xyz',
            title: 'OpenLayers 预览',
            description: `影像瓦片，当前按 ${tileScheme.toUpperCase()} 行号规则请求。`,
            url: accessUrl,
            tileScheme
        };
    }

    return {
        supported: false,
        mode: '',
        title: '暂不支持预览',
        description: '当前只内置了 MVT、GeoJSON 瓦片和 XYZ/TiTiler 的 OpenLayers 预览。',
        url: accessUrl
    };
});

function close() {
    emit('update:modelValue', false);
}

function destroyMap() {
    if (mapInstance) {
        mapInstance.setTarget(undefined);
        mapInstance = null;
    }
}

function fitBounds(view, bounds, projection = 'EPSG:4326') {
    if (!Array.isArray(bounds) || bounds.length !== 4) return;
    const valid = bounds.every(value => Number.isFinite(Number(value)));
    if (!valid) return;
    const extent = projection === 'EPSG:3857' ? transformExtent(bounds, 'EPSG:4326', 'EPSG:3857') : bounds;
    view.fit(extent, {
        padding: [24, 24, 24, 24],
        duration: 0,
        maxZoom: 14
    });
}

function createBaseView(projection = 'EPSG:4326') {
    return new View({
        projection,
        center: projection === 'EPSG:3857' ? fromLonLat([104, 35]) : [104, 35],
        zoom: 3,
        minZoom: 0,
        maxZoom: 20,
        multiWorld: false
    });
}

function createRasterLayer(url, tileScheme = 'xyz') {
    return new TileLayer({
        source: new XYZ({
            tileUrlFunction: tileCoord => {
                if (!tileCoord) return '';
                const [z, x, y] = tileCoord;
                return buildTileRequestUrl(url, z, x, y, tileScheme);
            },
            crossOrigin: 'anonymous'
        })
    });
}

function createMvtLayer(url, tileScheme = 'xyz') {
    return new VectorTileLayer({
        declutter: true,
        source: new VectorTileSource({
            format: new MVT(),
            tileUrlFunction: tileCoord => {
                if (!tileCoord) return '';
                const [z, x, y] = tileCoord;
                return buildTileRequestUrl(url, z, x, y, tileScheme);
            },
            crossOrigin: 'anonymous'
        }),
        style: vectorStyle
    });
}

function createGeoJsonLayer(url, minZoom, maxZoom, view, tileScheme = 'xyz') {
    const tileGrid = createXYZ({
        extent: [-180, -90, 180, 90],
        minZoom,
        maxZoom
    });
    const loadedTiles = new Set();
    const format = new GeoJSON();
    let mapRef = null;

    const source = new VectorSource({
        format,
        strategy: extent => [extent],
        loader: async extent => {
            const currentMap = mapRef;
            const currentZoom = Math.round(currentMap?.getView()?.getZoom?.() ?? minZoom);
            const z = Math.max(minZoom, Math.min(maxZoom, currentZoom));
            const tileRange = tileGrid.getTileRangeForExtentAndZ(extent, z);

            for (let x = tileRange.minX; x <= tileRange.maxX; x += 1) {
                for (let y = tileRange.minY; y <= tileRange.maxY; y += 1) {
                    const key = `${z}/${x}/${y}`;
                    if (loadedTiles.has(key)) continue;
                    loadedTiles.add(key);

                    try {
                        const response = await fetch(buildTileRequestUrl(url, z, x, y, tileScheme));
                        if (!response.ok) continue;
                        const payload = await response.json();
                        const features = format.readFeatures(payload, {
                            dataProjection: 'EPSG:4326',
                            featureProjection: 'EPSG:4326'
                        });
                        if (features.length) {
                            source.addFeatures(features);
                        }
                    } catch (error) {
                        console.warn('GeoJSON tile preview failed:', key, error);
                    }
                }
            }
        }
    });

    const layer = new VectorLayer({
        source,
        style: vectorStyle
    });

    return {
        layer,
        bindMap(map) {
            mapRef = map;
            map.on('moveend', () => {
                source.refresh();
            });
            source.refresh();
        },
        view
    };
}

async function renderPreview() {
    destroyMap();
    previewStatus.value = '';

    if (!props.modelValue || !previewConfig.value.supported || !mapContainer.value) {
        return;
    }

    await nextTick();

    const projection = previewConfig.value.mode === 'vector-geojson' ? 'EPSG:4326' : 'EPSG:3857';
    const view = createBaseView(projection);
    let layer = null;
    let binder = null;

    if (previewConfig.value.mode === 'raster-xyz') {
        layer = createRasterLayer(previewConfig.value.url, previewConfig.value.tileScheme);
    } else if (previewConfig.value.mode === 'vector-mvt') {
        layer = createMvtLayer(previewConfig.value.url, previewConfig.value.tileScheme);
    } else if (previewConfig.value.mode === 'vector-geojson') {
        const geojsonLayer = createGeoJsonLayer(
            previewConfig.value.url,
            previewConfig.value.minZoom,
            previewConfig.value.maxZoom,
            view,
            previewConfig.value.tileScheme
        );
        layer = geojsonLayer.layer;
        binder = geojsonLayer.bindMap;
    }

    if (!layer) return;

    mapInstance = new Map({
        target: mapContainer.value,
        layers: [layer],
        view,
        controls: []
    });

    if (typeof binder === 'function') {
        binder(mapInstance);
    }

    fitBounds(view, previewConfig.value.bounds, projection);
    previewStatus.value = previewConfig.value.description;
}

watch(
    () => [props.modelValue, props.publication],
    async () => {
        if (props.modelValue) {
            await renderPreview();
        } else {
            destroyMap();
        }
    },
    { deep: true }
);

onBeforeUnmount(() => {
    destroyMap();
});
</script>

<template>
    <ResizableDrawer
        :model-value="modelValue"
        title="发布预览"
        :width="980"
        :min-width="620"
        :max-width="1400"
        destroy-on-close
        @update:model-value="value => emit('update:modelValue', value)"
    >
        <div class="preview-dialog-body">
            <div class="preview-toolbar">
                <div>
                    <div class="preview-title">{{ publication?.alias || '未命名发布' }}</div>
                    <div class="preview-subtitle">{{ previewConfig.title }}</div>
                </div>
                <el-tag v-if="previewConfig.supported" type="success">OpenLayers</el-tag>
                <el-tag v-else type="info">暂不支持</el-tag>
            </div>

            <el-alert
                :title="previewConfig.description"
                :closable="false"
                type="info"
                show-icon
            />

            <div v-if="previewConfig.supported" class="preview-map-shell">
                <div ref="mapContainer" class="preview-map" />
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

.preview-title {
    font-size: 18px;
    font-weight: 600;
    color: #303133;
}

.preview-subtitle {
    margin-top: 4px;
    color: #606266;
    font-size: 13px;
}

.preview-map-shell {
    overflow: hidden;
    border: 1px solid #dcdfe6;
    border-radius: 14px;
    background: linear-gradient(180deg, #f8fbff 0%, #eef5ff 100%);
}

.preview-map {
    width: 100%;
    height: 560px;
}

.preview-status {
    color: #606266;
    font-size: 13px;
}
</style>
