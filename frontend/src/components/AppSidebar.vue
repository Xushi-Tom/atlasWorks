<script setup>
import { computed } from 'vue';

const props = defineProps({
    currentSection: { type: String, required: true },
    currentTool: { type: String, required: true },
    currentSystem: { type: String, required: true },
    expandedGroups: { type: Object, required: true },
    collapsed: { type: Boolean, required: true }
});

const emit = defineEmits(['navigate', 'toggle-group', 'request-expand']);

const primaryItems = [
    { id: 'dashboard', label: '仪表盘', tag: 'DB' },
    { id: 'datasource', label: '数据源管理', tag: 'DS' },
    { id: 'map-tiles', label: '地图切片', tag: 'MP' },
    { id: 'terrain-tiles', label: '地形切片', tag: 'TR' },
    { id: 'workspace', label: '工作空间', tag: 'WS' },
    { id: 'tasks', label: '任务列表', tag: 'TK' },
    { id: 'publish', label: '发布中心', tag: 'PB' }
];

const toolsItems = [
    { id: 'toolNodataTiles', label: '透明瓦片治理', tag: 'ND' },
    { id: 'toolLayerJson', label: '地形元数据修复', tag: 'LJ' },
    { id: 'toolTerrainDecompress', label: '地形数据解压', tag: 'TD' },
    { id: 'toolPreflight', label: '生产预检', tag: 'PF' },
    { id: 'toolArtifacts', label: '成果索引', tag: 'AR' },
    { id: 'toolTileConverter', label: '瓦片结构转换', tag: 'CV' },
    { id: 'toolSplit', label: '大文件切分', tag: 'SP' }
];

const systemItems = [
    { id: 'systemUpdates', label: '系统更新', tag: 'UP' },
    { id: 'systemRoutes', label: 'API 路由', tag: 'RT' },
    { id: 'systemConfig', label: '系统配置', tag: 'CF' }
];

const isToolsActive = computed(() => props.currentSection === 'tools');
const isSystemActive = computed(() => props.currentSection === 'system');

function openPrimary(section) {
    emit('navigate', { section });
}

function openGroup(group) {
    const config = group === 'tools'
        ? { section: 'tools', subsection: props.currentTool || toolsItems[0].id }
        : { section: 'system', subsection: props.currentSystem || systemItems[0].id };

    if (props.collapsed) {
        emit('request-expand');
        emit('navigate', config);
        return;
    }

    if ((group === 'tools' && isToolsActive.value) || (group === 'system' && isSystemActive.value)) {
        emit('toggle-group', group);
        return;
    }

    emit('navigate', config);
}

function openSubsection(section, subsection) {
    emit('navigate', { section, subsection });
}
</script>

<template>
    <aside class="console-sidebar-shell" :class="{ 'console-sidebar-shell-collapsed': collapsed }">
        <div class="console-sidebar-head">
            <div v-if="!collapsed" class="console-sidebar-brand">
                <span class="console-sidebar-kicker">Operations Grid</span>
                <strong>AtlasWorks Command Surface</strong>
                <p>面向地理数据接入、切片生产、资产发布与运行治理，统一承载全链路生产调度。</p>
            </div>
            <div v-else class="console-sidebar-rail-mark" aria-hidden="true">TF</div>
        </div>

        <div class="console-sidebar-scroll">
            <nav class="console-nav" aria-label="主导航">
                <ul class="console-nav-list">
                    <li
                        v-for="item in primaryItems"
                        :key="item.id"
                        class="console-nav-item"
                    >
                        <button
                            class="console-nav-link"
                            type="button"
                            :title="item.label"
                            :class="{ active: currentSection === item.id }"
                            @click="openPrimary(item.id)"
                        >
                            <span class="console-nav-token" aria-hidden="true">{{ item.tag }}</span>
                            <span v-if="!collapsed" class="console-nav-copy">
                                <strong>{{ item.label }}</strong>
                                <small>{{ item.id }}</small>
                            </span>
                        </button>
                    </li>
                </ul>
            </nav>

            <div v-if="!collapsed" class="console-nav-divider"></div>

            <div class="console-nav-clusters">
                <section
                    class="console-group-card"
                    :class="{ active: isToolsActive, expanded: expandedGroups.tools }"
                >
                    <div class="console-group-header">
                        <button
                            class="console-nav-link console-nav-link-group"
                            type="button"
                            title="分析工具"
                            :aria-expanded="!collapsed && expandedGroups.tools"
                            @click.stop="openGroup('tools')"
                        >
                            <span class="console-nav-token" aria-hidden="true">TL</span>
                            <span v-if="!collapsed" class="console-nav-copy">
                                <strong>分析工具</strong>
                                <small>质量治理与结构处理</small>
                            </span>
                        </button>
                        <button
                            v-if="!collapsed"
                            class="console-group-toggle"
                            type="button"
                            :aria-label="expandedGroups.tools ? '收起分析工具' : '展开分析工具'"
                            :aria-expanded="expandedGroups.tools"
                            @click.stop="$emit('toggle-group', 'tools')"
                        >
                            <span class="console-group-caret" aria-hidden="true"></span>
                        </button>
                    </div>
                    <transition name="sidebar-slide">
                        <ul v-if="!collapsed && expandedGroups.tools" class="console-subnav-list">
                            <li v-for="item in toolsItems" :key="item.id">
                                <button
                                    class="console-subnav-link"
                                    type="button"
                                    :title="item.label"
                                    :class="{ active: isToolsActive && currentTool === item.id }"
                                    @click.stop="openSubsection('tools', item.id)"
                                >
                                    <span class="console-subnav-token" aria-hidden="true">{{ item.tag }}</span>
                                    <span>{{ item.label }}</span>
                                </button>
                            </li>
                        </ul>
                    </transition>
                </section>

                <section
                    class="console-group-card"
                    :class="{ active: isSystemActive, expanded: expandedGroups.system }"
                >
                    <div class="console-group-header">
                        <button
                            class="console-nav-link console-nav-link-group"
                            type="button"
                            title="系统管理"
                            :aria-expanded="!collapsed && expandedGroups.system"
                            @click.stop="openGroup('system')"
                        >
                            <span class="console-nav-token" aria-hidden="true">SY</span>
                            <span v-if="!collapsed" class="console-nav-copy">
                                <strong>系统管理</strong>
                                <small>平台状态与接口治理</small>
                            </span>
                        </button>
                        <button
                            v-if="!collapsed"
                            class="console-group-toggle"
                            type="button"
                            :aria-label="expandedGroups.system ? '收起系统管理' : '展开系统管理'"
                            :aria-expanded="expandedGroups.system"
                            @click.stop="$emit('toggle-group', 'system')"
                        >
                            <span class="console-group-caret" aria-hidden="true"></span>
                        </button>
                    </div>
                    <transition name="sidebar-slide">
                        <ul v-if="!collapsed && expandedGroups.system" class="console-subnav-list">
                            <li v-for="item in systemItems" :key="item.id">
                                <button
                                    class="console-subnav-link"
                                    type="button"
                                    :title="item.label"
                                    :class="{ active: isSystemActive && currentSystem === item.id }"
                                    @click.stop="openSubsection('system', item.id)"
                                >
                                    <span class="console-subnav-token" aria-hidden="true">{{ item.tag }}</span>
                                    <span>{{ item.label }}</span>
                                </button>
                            </li>
                        </ul>
                    </transition>
                </section>
            </div>
        </div>

    </aside>
</template>
