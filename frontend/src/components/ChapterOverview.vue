<script setup lang="ts">
import { computed } from "vue";
const props = defineProps<{
  chapters: { index: number; title: string; characters: number }[];
  start: number;
  end: number;
}>();
const range = computed(() => {
  const total = props.chapters.length;
  const end = props.end === -1 ? total : props.end;
  const valid =
    Number.isInteger(props.start) &&
    Number.isInteger(end) &&
    props.start >= 1 &&
    end >= props.start &&
    end <= total;
  const selected = valid
    ? props.chapters.filter((c) => c.index >= props.start && c.index <= end)
    : [];
  return {
    total,
    count: selected.length,
    first: selected[0]?.title,
    last: selected.at(-1)?.title,
    characters: selected.reduce((sum, c) => sum + c.characters, 0),
    transform:
      valid && total
        ? `translateX(${((props.start - 1) / total) * 100}%) scaleX(${selected.length / total})`
        : "scaleX(0)",
  };
});
</script>
<template>
  <div class="chapter-overview" aria-live="polite" aria-atomic="true">
    <div class="chapter-overview-top">
      <strong>{{ range.count === 1 ? "单章试生成" : "本次生成范围" }}</strong>
      <span>已选 {{ range.count }} 章 / 共 {{ range.total }} 章</span>
    </div>
    <div class="chapter-track" aria-hidden="true">
      <span class="chapter-fill" :style="{ transform: range.transform }" />
    </div>
    <p v-if="range.count">
      {{ range.first
      }}<template v-if="range.count > 1"> → {{ range.last }}</template> ·
      {{ range.characters.toLocaleString() }} 字符
    </p>
    <p v-else>请选择有效的起止章节，结束章节不能早于起始章节。</p>
  </div>
</template>
