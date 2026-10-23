<script setup lang="ts">
import { ref, watch } from "vue";
const props = defineProps<{ open: boolean; id: string }>();
const visited = ref(false);
watch(
  () => props.open,
  (open) => {
    if (open) visited.value = true;
  },
  { immediate: true },
);
</script>
<template>
  <div
    :id="id"
    class="expand-panel"
    :class="{ 'is-open': open }"
    :aria-hidden="!open"
    :inert="!open"
  >
    <div class="expand-panel-content"><slot v-if="visited" /></div>
  </div>
</template>
