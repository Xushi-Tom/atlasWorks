import { readonly, ref } from 'vue';

const toasts = ref([]);
let toastSeed = 0;

export function pushToast(message, type = 'info', timeout = 3200) {
    const id = ++toastSeed;
    const toast = { id, message, type };
    toasts.value = [...toasts.value, toast];

    if (timeout > 0) {
        window.setTimeout(() => removeToast(id), timeout);
    }

    return id;
}

export function removeToast(id) {
    toasts.value = toasts.value.filter(item => item.id !== id);
}

export function useToastState() {
    return readonly(toasts);
}
