<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { fileUrl, type FileRef } from "../api";
const props = defineProps<{ file: FileRef }>();
const loaded = ref(false),
  failed = ref(false);
const title = computed(() => props.file.name.replace(/\.[^.]+$/, ""));
watch(
  () => props.file.cover_id,
  () => {
    loaded.value = false;
    failed.value = false;
  },
);
</script>
<template>
  <div class="book-cover" :class="{ 'has-image': loaded }">
    <div class="book-cover-placeholder" aria-hidden="true">
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.4"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path
          d="M5 3h14v18H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Zm2 0v18M10 8h6M10 11h4"
        />
      </svg>
      <span>{{ title }}</span>
      <small>{{ file.category.toUpperCase() }}</small>
    </div>
    <img
      v-if="file.cover_id && !failed"
      :src="fileUrl(file.cover_id)"
      :alt="`${title}的封面缩略图`"
      decoding="async"
      @load="loaded = true"
      @error="failed = true"
    />
  </div>
</template>
