<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";

const props = defineProps<{
  steps: { id: string; label: string; shortLabel: string; detail: string }[];
}>();
const guide = ref<HTMLElement>();
const current = ref(props.steps[0]?.id);
let frame = 0;
let observer: ResizeObserver | undefined;
let page: HTMLElement | null | undefined;
let header: HTMLElement | null;
let offset = 110;

function syncPosition() {
  frame = 0;
  const inset = header ? parseFloat(getComputedStyle(header).top) || 0 : 0;
  offset = (header?.getBoundingClientRect().height || 0) + inset + 16;
  page?.style.setProperty("--workflow-scroll-offset", `${offset}px`);
  const sections = props.steps
    .map((step) => document.getElementById(step.id))
    .filter((section): section is HTMLElement => !!section);
  let active: HTMLElement | undefined = sections[0];
  for (const section of sections) {
    if (section.getBoundingClientRect().top <= offset + 1) active = section;
  }
  if (
    window.scrollY > 0 &&
    window.scrollY + window.innerHeight >=
      document.documentElement.scrollHeight - 2
  )
    active = sections.at(-1);
  if (active) current.value = active.id;
}
function scheduleSync() {
  if (!frame) frame = requestAnimationFrame(syncPosition);
}
function navigate(event: MouseEvent, id: string) {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const section = document.getElementById(id);
  if (!section) return;
  event.preventDefault();
  syncPosition();
  section.focus({ preventScroll: true });
  section.scrollIntoView({
    block: "start",
    behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
      ? "instant"
      : "smooth",
  });
  scheduleSync();
}
onMounted(() => {
  page = guide.value?.parentElement;
  header = document.querySelector<HTMLElement>(".app-header");
  observer = new ResizeObserver(scheduleSync);
  if (header) observer.observe(header);
  if (page) observer.observe(page);
  window.addEventListener("scroll", scheduleSync, { passive: true });
  window.addEventListener("resize", scheduleSync);
  syncPosition();
});
onUnmounted(() => {
  observer?.disconnect();
  cancelAnimationFrame(frame);
  window.removeEventListener("scroll", scheduleSync);
  window.removeEventListener("resize", scheduleSync);
  page?.style.removeProperty("--workflow-scroll-offset");
});
</script>
<template>
  <nav ref="guide" class="workflow-guide" aria-label="生成流程">
    <div class="workflow-links">
      <a
        v-for="(step, index) in steps"
        :id="`workflow-link-${step.id}`"
        :key="step.id"
        :href="`#${step.id}`"
        :aria-label="`第 ${index + 1} 步：${step.label}，${step.detail}`"
        :aria-current="current === step.id ? 'location' : undefined"
        @click="navigate($event, step.id)"
      >
        <span class="workflow-number" aria-hidden="true">{{ index + 1 }}</span>
        <span class="workflow-label">{{ step.label }}</span>
        <span class="workflow-short" aria-hidden="true">{{
          step.shortLabel
        }}</span>
        <small>{{ step.detail }}</small>
      </a>
    </div>
  </nav>
</template>
