<script setup lang="ts">
import { onDeactivated, onMounted, onUnmounted, ref, watch } from "vue";
const props = defineProps<{ modelValue: boolean }>();
const emit = defineEmits<{ "update:modelValue": [value: boolean] }>();
const dialog = ref<HTMLDialogElement>();
function sync() {
  if (props.modelValue && !dialog.value?.open) dialog.value?.showModal();
  else if (!props.modelValue && dialog.value?.open) dialog.value.close();
}
function close() {
  dialog.value?.close();
}
function closed() {
  emit("update:modelValue", false);
}
function backdrop(event: MouseEvent) {
  if (event.target !== dialog.value) return;
  const rect = dialog.value.getBoundingClientRect();
  if (
    event.clientX < rect.left ||
    event.clientX > rect.right ||
    event.clientY < rect.top ||
    event.clientY > rect.bottom
  )
    close();
}
watch(() => props.modelValue, sync, { flush: "post" });
onMounted(sync);
onDeactivated(close);
onUnmounted(close);
</script>
<template>
  <Teleport to="body">
    <dialog
      ref="dialog"
      class="settings-dialog"
      aria-labelledby="advanced-settings-title"
      @close="closed"
      @click="backdrop"
    >
      <div class="settings-dialog-layout">
        <header class="settings-dialog-header">
          <div>
            <h2 id="advanced-settings-title">高级设置</h2>
            <p class="muted">解析与输出设置</p>
          </div>
          <button
            type="button"
            class="quiet dialog-close"
            aria-label="关闭高级设置"
            autofocus
            @click="close"
          >
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.6"
              stroke-linecap="round"
            >
              <path d="m6 6 12 12M18 6 6 18" />
            </svg>
          </button>
        </header>
        <div class="settings-dialog-body"><slot /></div>
        <footer class="settings-dialog-footer">
          <span class="muted">设置会自动应用</span
          ><button type="button" class="primary" @click="close">完成</button>
        </footer>
      </div>
    </dialog>
  </Teleport>
</template>
