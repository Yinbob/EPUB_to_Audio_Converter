<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import type { Task } from "../api";
const props = defineProps<{
  task: Task | null;
  submitting: boolean;
  error: string;
}>();
const root = ref<HTMLElement>();
const visible = ref(true);
const foreground = ref(!document.hidden);
let observer: IntersectionObserver | undefined;
function visibility() {
  foreground.value = !document.hidden;
}
onMounted(() => {
  document.addEventListener("visibilitychange", visibility);
  observer = new IntersectionObserver(([entry]) => {
    visible.value = entry.isIntersecting;
  });
  if (root.value) observer.observe(root.value);
});
onUnmounted(() => {
  observer?.disconnect();
  document.removeEventListener("visibilitychange", visibility);
});
const state = computed(() =>
  props.submitting
    ? "submitting"
    : props.error
      ? "failed"
      : props.task?.status || "idle",
);
const busy = computed(() =>
  ["submitting", "starting", "running", "stopping"].includes(state.value),
);
const title = computed(
  () =>
    ({
      idle: "等待生成剧本",
      submitting: "正在提交剧本任务",
      starting: "正在准备剧本",
      running: "DeepSeek 正在生成剧本",
      stopping: "正在停止生成剧本",
      succeeded: "剧本已准备好",
      failed: "剧本未生成成功",
      stopped: "已停止生成剧本",
    })[state.value] || "等待生成剧本",
);
const detail = computed(() => {
  if (props.error) return props.error;
  if (state.value === "submitting") return "请求已提交，正在等待后台确认…";
  if (state.value === "idle")
    return "使用 DeepSeek 分析所选章节中的人物、叙述与对白，生成后请复核并确认。";
  if (state.value === "succeeded")
    return "请在下方为人物分配声音、试听并复核，再确认用于生成有声书。";
  if (state.value === "failed")
    return props.task?.error || "请检查 DeepSeek 连接与所选章节后重试。";
  if (state.value === "stopped")
    return "可再次点击生成，继续复用已保存的分析结果。";
  if (state.value === "stopping") return "正在清理后台进程，请稍候。";
  return (
    props.task?.progress?.detail || "正在准备所选章节；长章节可能需要几分钟。"
  );
});
// 阶段只根据真实后台日志高亮，不按时间模拟完成进度。
const phase = computed(() => {
  if (state.value === "succeeded") return 3;
  if (!busy.value) return -1;
  if (/已保存|保存结果/.test(detail.value)) return 3;
  if (/人物表|人物索引|叙述者|叙述视角/.test(detail.value)) return 1;
  if (/正在拆分|逐段/.test(detail.value)) return 2;
  return /读取/.test(detail.value) ? 0 : -1;
});
const percent = computed(() => {
  if (state.value === "succeeded") return 100;
  const value = Number(props.task?.progress?.pct);
  return Number.isFinite(value) ? Math.min(100, Math.max(0, value)) : 0;
});
const determinate = computed(() => percent.value > 0);
</script>
<template>
  <div
    ref="root"
    class="script-status"
    :data-state="state"
    :class="{ 'is-animating': busy && visible && foreground }"
  >
    <div class="script-wave" aria-hidden="true">
      <span
        v-for="(height, index) in [
          12, 20, 30, 38, 28, 18, 26, 40, 32, 22, 34, 28, 18, 24, 12,
        ]"
        :key="index"
        :style="{ height: `${height}px`, animationDelay: `${index * -110}ms` }"
      />
    </div>
    <div
      class="script-status-copy"
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      <strong>{{ title }}</strong>
      <p>{{ detail }}</p>
    </div>
    <slot v-if="busy && !submitting" name="stop" />
    <div v-if="busy || state === 'succeeded'" class="script-progress">
      <div class="script-progress-label">
        <span>{{ determinate ? "当前任务进度" : "正在处理所选章节" }}</span
        ><span v-if="determinate">{{ Math.round(percent) }}%</span
        ><span v-else>处理中…</span>
      </div>
      <div
        class="script-progress-track"
        role="progressbar"
        aria-label="剧本生成进度"
        :aria-valuenow="determinate ? percent : undefined"
        :aria-valuemin="0"
        :aria-valuemax="100"
      >
        <span
          class="script-progress-fill"
          :class="{ 'is-indeterminate': !determinate }"
          :style="
            determinate ? { transform: `scaleX(${percent / 100})` } : undefined
          "
        />
      </div>
    </div>
    <ol class="script-stages" aria-label="剧本处理阶段">
      <li
        v-for="(stage, index) in [
          '读取章节',
          '梳理人物',
          '拆分剧本',
          '保存结果',
        ]"
        :key="stage"
        :aria-current="phase === index ? 'step' : undefined"
      >
        {{ stage }}
      </li>
    </ol>
  </div>
</template>
