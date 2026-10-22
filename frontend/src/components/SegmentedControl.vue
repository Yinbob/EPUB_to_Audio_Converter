<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
type Option = { value: string; label: string; to?: string };
const props = withDefaults(
  defineProps<{
    modelValue: string;
    options: Option[];
    label: string;
    navigation?: boolean;
  }>(),
  { navigation: false },
);
const emit = defineEmits<{
  "update:modelValue": [value: string];
  activate: [value: string, keyboard: boolean];
}>();
const root = ref<HTMLElement>();
const indicator = ref({
  transform: "translate3d(0, 0, 0)",
  width: "0px",
  height: "0px",
});
const measured = ref(false),
  instant = ref(false);
const columns = computed(() => ({
  gridTemplateColumns: `repeat(${props.options.length}, minmax(0, 1fr))`,
}));
let observer: ResizeObserver | undefined;
function measure() {
  const active = Array.from(
    root.value?.querySelectorAll<HTMLElement>("[data-segment]") || [],
  ).find((el) => el.dataset.segment === props.modelValue);
  if (!active) return;
  indicator.value = {
    transform: `translate3d(${active.offsetLeft}px, ${active.offsetTop}px, 0)`,
    width: `${active.offsetWidth}px`,
    height: `${active.offsetHeight}px`,
  };
  measured.value = true;
}
function activate(option: Option, event: MouseEvent) {
  instant.value = event.detail === 0;
  emit("activate", option.value, instant.value);
  emit("update:modelValue", option.value);
}
watch(
  () => [props.modelValue, props.options],
  () => nextTick(measure),
  { deep: true },
);
onMounted(() => {
  measure();
  observer = new ResizeObserver(measure);
  if (root.value) observer.observe(root.value);
});
onUnmounted(() => observer?.disconnect());
</script>
<template>
  <component
    :is="navigation ? 'nav' : 'div'"
    ref="root"
    class="segmented-control"
    :class="{
      'is-measured': measured,
      'is-instant': instant,
      'six-options': options.length === 6,
    }"
    :style="columns"
    :aria-label="label"
    :role="navigation ? undefined : 'group'"
  >
    <span aria-hidden="true" class="segment-indicator" :style="indicator" />
    <template v-for="option in options" :key="option.value">
      <RouterLink
        v-if="option.to"
        :to="option.to"
        :data-segment="option.value"
        :class="{ 'is-selected': modelValue === option.value }"
        @click="activate(option, $event)"
        >{{ option.label }}</RouterLink
      >
      <button
        v-else
        type="button"
        :data-segment="option.value"
        :aria-pressed="modelValue === option.value"
        :class="{ 'is-selected': modelValue === option.value }"
        @click="activate(option, $event)"
      >
        {{ option.label }}
      </button>
    </template>
  </component>
</template>
