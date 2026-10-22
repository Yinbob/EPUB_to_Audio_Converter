<script setup lang="ts">
import { ref } from "vue";
import type { FileRef } from "../api";
import BookCover from "./BookCover.vue";
const props = defineProps<{
  files: FileRef[];
  uploading: boolean;
  busy: boolean;
}>();
const emit = defineEmits<{
  select: [files: File[]];
  remove: [index: number];
}>();
const dragDepth = ref(0);
function select(event: Event) {
  const input = event.target as HTMLInputElement;
  if (input.files?.length) emit("select", Array.from(input.files));
  input.value = "";
}
function drop(event: DragEvent) {
  dragDepth.value = 0;
  if (!props.busy && !props.uploading)
    emit("select", Array.from(event.dataTransfer?.files || []));
}
function size(bytes: number) {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
</script>
<template>
  <div
    class="upload-zone"
    :class="{
      'is-dragging': dragDepth > 0,
      'is-disabled': uploading || busy,
      'has-books': files.length > 0,
    }"
    :aria-busy="uploading"
    @dragenter.prevent="dragDepth++"
    @dragover.prevent
    @dragleave.prevent="dragDepth = Math.max(0, dragDepth - 1)"
    @drop.prevent="drop"
  >
    <label class="upload-prompt">
      <span class="upload-icon" aria-hidden="true"
        ><svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.7"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path
            d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M12 3v12m-5-7 5-5 5 5"
          /></svg
      ></span>
      <span class="upload-prompt-copy"
        ><strong>{{
          uploading
            ? "正在上传书籍…"
            : dragDepth
              ? "松开，添加你的书籍"
              : files.length
                ? "继续添加书籍"
                : "拖放书籍到此处，或点击选择"
        }}</strong
        ><span class="muted">{{
          files.length
            ? "拖入或点击添加 · 上传后自动读取单本书目录"
            : "EPUB、DOC、DOCX · 支持多本书批量生成"
        }}</span></span
      >
      <input
        aria-label="上传书籍"
        type="file"
        accept=".epub,.doc,.docx"
        multiple
        :disabled="uploading || busy"
        @change="select"
      />
    </label>
    <TransitionGroup
      name="book-arrival"
      tag="div"
      class="uploaded-books"
      aria-label="已上传的书籍"
    >
      <article
        v-for="(file, index) in files"
        :key="file.id"
        class="uploaded-book chip"
      >
        <BookCover :file="file" />
        <div class="uploaded-book-copy">
          <strong :title="file.name">{{ file.name }}</strong
          ><span class="muted"
            >{{ size(file.size) }} ·
            {{ file.cover_id ? "已读取书籍封面" : "暂无内嵌封面" }}</span
          ><span class="book-ready"
            ><svg
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              stroke-width="1.5"
              aria-hidden="true"
            >
              <path d="m3 8 3 3 7-7" /></svg
            >已添加</span
          >
        </div>
        <button
          class="quiet book-remove"
          aria-label="移除文件"
          :title="`移除 ${file.name}`"
          :disabled="busy || uploading"
          @click="emit('remove', index)"
        >
          <svg
            viewBox="0 0 20 20"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            aria-hidden="true"
          >
            <path d="m6 6 8 8M14 6l-8 8" />
          </svg>
        </button>
      </article>
    </TransitionGroup>
    <p v-if="uploading" class="upload-feedback" role="status">
      正在接收文件与读取封面，请稍候…
    </p>
  </div>
</template>
