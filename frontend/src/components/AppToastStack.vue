<script setup>
import { removeToast } from '../composables/useToast';

defineProps({
    toasts: {
        type: Array,
        required: true
    }
});
</script>

<template>
    <div class="toast-stack">
        <div
            v-for="toast in toasts"
            :key="toast.id"
            class="toast-card"
            :class="`toast-card-${toast.type}`"
        >
            <span>{{ toast.message }}</span>
            <button type="button" class="message-close" @click="removeToast(toast.id)">×</button>
        </div>
    </div>
</template>
