<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';

defineProps({
    sectionLabel: { type: String, required: true },
    sectionCaption: { type: String, required: true },
    sidebarCollapsed: { type: Boolean, required: true },
    themeMode: { type: String, required: true }
});

defineEmits(['toggle-sidebar', 'toggle-theme']);

const now = ref(new Date());
let timerId = null;

onMounted(() => {
    timerId = window.setInterval(() => {
        now.value = new Date();
    }, 1000);
});

onBeforeUnmount(() => {
    if (timerId) {
        window.clearInterval(timerId);
    }
});

const currentDate = computed(() => now.value.toLocaleDateString('zh-CN').replace(/\//g, '/'));
const currentTime = computed(() => now.value.toLocaleTimeString('zh-CN', { hour12: false }));
</script>

<template>
    <header class="header product-header">
        <div class="header-left">
            <button
                class="shell-icon-button"
                type="button"
                :aria-label="sidebarCollapsed ? '展开导航' : '折叠导航'"
                @click="$emit('toggle-sidebar')"
            >
                <span class="shell-hamburger" aria-hidden="true">
                    <span></span>
                    <span></span>
                    <span></span>
                </span>
            </button>
            <div class="logo">
                <span>AtlasWorks</span>
            </div>
        </div>
        <div class="header-right">
            <button
                class="shell-icon-button theme-toggle-button"
                type="button"
                :aria-label="themeMode === 'light' ? '切换到暗色模式' : '切换到亮色模式'"
                @click="$emit('toggle-theme')"
            >
                <span class="theme-toggle-text">{{ themeMode === 'light' ? '暗色' : '亮色' }}</span>
            </button>
            <div class="datetime-info">
                <span id="currentDate">{{ currentDate }}</span>
                <span id="currentTime">{{ currentTime }}</span>
            </div>
        </div>
    </header>
</template>
