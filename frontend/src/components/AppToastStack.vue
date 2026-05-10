<script setup>
import { removeToast } from '../composables/useToast';

defineProps({
    toasts: {
        type: Array,
        required: true
    }
});

function getToastSymbol(type) {
    const normalizedType = String(type || 'info').toLowerCase();
    if (normalizedType === 'success') return '✓';
    if (normalizedType === 'error') return '×';
    if (normalizedType === 'warning') return '!';
    return 'i';
}
</script>

<template>
    <div class="toast-stack">
        <div
            v-for="toast in toasts"
            :key="toast.id"
            class="layui-layer-msg"
            :class="`layui-layer-msg-${toast.type}`"
        >
            <span class="layui-layer-msg__icon">{{ getToastSymbol(toast.type) }}</span>
            <span class="layui-layer-msg__content">{{ toast.message }}</span>
            <button type="button" class="layui-layer-msg__close" @click="removeToast(toast.id)">×</button>
        </div>
    </div>
</template>
