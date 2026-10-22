<script setup lang="ts">
import { onMounted, onUnmounted, ref, useId } from "vue";
const id = `glass-edge-${useId()}`;
const surface = ref<SVGSVGElement>();
const paused = ref(true);
let observer: IntersectionObserver | undefined;
let inView = false;
let motion: MediaQueryList | undefined;
function syncVisibility() {
  paused.value = !inView || document.hidden || !!motion?.matches;
  if (paused.value) surface.value?.pauseAnimations();
  else surface.value?.unpauseAnimations();
}
onMounted(() => {
  motion = matchMedia("(prefers-reduced-motion: reduce)");
  motion.addEventListener("change", syncVisibility);
  observer = new IntersectionObserver(([entry]) => {
    inView = entry.isIntersecting;
    syncVisibility();
  });
  if (surface.value) observer.observe(surface.value);
  document.addEventListener("visibilitychange", syncVisibility);
  syncVisibility();
});
onUnmounted(() => {
  observer?.disconnect();
  document.removeEventListener("visibilitychange", syncVisibility);
  motion?.removeEventListener("change", syncVisibility);
});
</script>

<template>
  <svg
    ref="surface"
    class="liquid-glass-edge"
    :class="{ 'is-paused': paused }"
    aria-hidden="true"
    focusable="false"
  >
    <defs>
      <linearGradient :id="id" x1="0%" y1="0%" x2="100%" y2="100%">
        <animateTransform
          attributeName="gradientTransform"
          type="rotate"
          from="0 0.5 0.5"
          to="360 0.5 0.5"
          dur="36s"
          repeatCount="indefinite"
        />
        <stop offset="0%" class="glass-light-cyan" />
        <stop offset="45%" class="glass-light-violet" />
        <stop offset="72%" class="glass-light-rose" />
        <stop offset="100%" class="glass-light-cyan" />
      </linearGradient>
    </defs>
    <g :stroke="`url(#${id})`" fill="none">
      <rect class="glass-edge-bloom" width="100%" height="100%" rx="22" />
      <rect class="glass-edge-trail" width="100%" height="100%" rx="22" />
      <rect class="glass-edge-core" width="100%" height="100%" rx="22" />
    </g>
  </svg>
</template>
