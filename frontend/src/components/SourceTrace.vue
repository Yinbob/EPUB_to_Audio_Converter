<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { api, fileUrl } from "../api";
import { useStudio } from "../stores/studio";
const props = defineProps<{ folder: string }>();
const store = useStudio(),
  data = ref<any>(null),
  chapter = ref(1),
  player = ref<HTMLAudioElement>(),
  highlighted = ref<string[]>([]);
const paragraphs = computed(() =>
  (data.value?.paragraphs || []).filter(
    (p: any) => p.chapter_index === Number(chapter.value),
  ),
);
const timeline = computed(() =>
  data.value?.timeline?.chapters.find(
    (c: any) => c.chapter_index === Number(chapter.value),
  ),
);
let pendingSeek = 0;
watch(
  () => props.folder,
  async (folder) => {
    data.value = null;
    if (!folder) return;
    try {
      const result = await api(
        "/library/source?folder=" + encodeURIComponent(folder),
      );
      if (folder !== props.folder) return;
      data.value = result;
      chapter.value =
        result.timeline?.chapters?.[0]?.chapter_index ||
        result.chapters?.[0]?.index ||
        1;
    } catch (e) {
      store.fail(e);
    }
  },
  { immediate: true },
);
watch(chapter, () => {
  pendingSeek = 0;
  highlighted.value = [];
});
function jump(id: string) {
  const span = timeline.value?.spans.find((s: any) =>
    s.paragraph_ids.includes(id),
  );
  highlighted.value = [id];
  if (span && player.value) {
    pendingSeek = span.start_seconds;
    player.value.currentTime = pendingSeek;
    player.value.play().catch(store.fail);
  }
}
function playing() {
  const time = player.value?.currentTime || 0;
  highlighted.value =
    timeline.value?.spans.find(
      (s: any) => s.start_seconds <= time && time < s.end_seconds,
    )?.paragraph_ids || [];
}
</script>
<template>
  <details v-if="data?.available" class="section-space">
    <summary>原文与音频溯源</summary>
    <p class="muted section-space">
      点击原文段落跳到对应音频片段；播放时标记对应段落。定位精度为分片，未进行逐字对齐。
    </p>
    <a v-if="data.source_file" :href="fileUrl(data.source_file, true)"
      >下载保留的原始书籍</a
    >
    <select aria-label="溯源章节" v-model="chapter">
      <option v-for="c in data.chapters" :key="c.index" :value="c.index">
        {{ c.index }} · {{ c.title }}
      </option>
    </select>
    <audio
      v-if="timeline?.audio_file"
      ref="player"
      class="section-space"
      controls
      :src="fileUrl(timeline.audio_file)"
      @timeupdate="playing"
      @loadedmetadata="player && (player.currentTime = pendingSeek)"
    />
    <p v-else class="muted">
      此章节还没有有效音频映射。旧产物重新生成后才会包含溯源数据。
    </p>
    <p
      v-if="timeline?.spans.some((s: any) => s.precision === 'chapter')"
      class="muted"
    >
      当前产物仅能定位到整章。
    </p>
    <div class="source-paragraphs section-space">
      <button
        v-for="p in paragraphs"
        :key="p.id"
        type="button"
        class="source-paragraph"
        :aria-pressed="highlighted.includes(p.id)"
        @click="jump(p.id)"
      >
        <small
          >{{ p.locator.href || p.locator.kind }} ·
          {{
            p.locator.node_path ||
            (p.locator.paragraph_index !== undefined
              ? "段落 " + (p.locator.paragraph_index + 1)
              : "提取段落 " + (p.locator.extracted_paragraph_index + 1))
          }}</small
        >
        <span>{{ p.original_text || p.text }}</span
        ><small v-if="p.locator.note">{{ p.locator.note }}</small>
      </button>
    </div>
  </details>
</template>
<style scoped>
.source-paragraphs {
  display: grid;
  gap: 8px;
  max-height: 560px;
  overflow: auto;
}
.source-paragraph {
  display: grid;
  gap: 6px;
  text-align: left;
  white-space: pre-wrap;
  line-height: 1.7;
}
.source-paragraph small {
  color: var(--apple-text-2);
  overflow-wrap: anywhere;
}
.source-paragraph[aria-pressed="true"] {
  border-color: var(--apple-blue);
  background: var(--apple-blue-soft);
}
</style>
