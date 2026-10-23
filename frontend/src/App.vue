<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { useStudio } from "./stores/studio";
import { mountAmbient } from "./ambient";
import SegmentedControl from "./components/SegmentedControl.vue";
const store = useStudio();
const route = useRoute();
const navigation = [
  { value: "/", to: "/", label: "生成有声书" },
  { value: "/library", to: "/library", label: "资源库" },
  { value: "/logs", to: "/logs", label: "运行日志" },
  { value: "/settings", to: "/settings", label: "设置" },
];
const direction = ref("forward"),
  keyboardNavigation = ref(false);
watch(
  () => route.path,
  (next, previous) => {
    direction.value =
      navigation.findIndex((item) => item.value === next) >=
      navigation.findIndex((item) => item.value === previous)
        ? "forward"
        : "backward";
  },
);
const theme = ref(localStorage.getItem("ata-theme") || "auto");
const media = matchMedia("(prefers-color-scheme: dark)");
let ambient: ReturnType<typeof mountAmbient> | undefined;
function guardTitles() {
  document.querySelectorAll<HTMLElement>(".hero h1").forEach((title) => {
    title.classList.remove("ata-title-solid");
    if (getComputedStyle(title).backgroundImage === "none")
      title.classList.add("ata-title-solid");
  });
}
watch(
  () => [route.fullPath, store.ready],
  () => nextTick(guardTitles),
);
function applyTheme() {
  document.documentElement.classList.toggle(
    "dark",
    theme.value === "dark" || (theme.value === "auto" && media.matches),
  );
  document.dispatchEvent(new Event("ata-theme-change"));
  nextTick(guardTitles);
}
function cycleTheme() {
  theme.value =
    theme.value === "auto"
      ? "light"
      : theme.value === "light"
        ? "dark"
        : "auto";
  localStorage.setItem("ata-theme", theme.value);
  applyTheme();
}
function scrollToTop() {
  window.scrollTo({
    top: 0,
    behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
      ? "instant"
      : "smooth",
  });
}
watch(
  () => store.busy,
  (busy) => ambient?.setState(busy ? "generating" : "settling"),
);
onMounted(() => {
  applyTheme();
  ambient = mountAmbient();
  media.addEventListener("change", applyTheme);
  store.initialize();
});
onUnmounted(() => {
  store.dispose();
  ambient?.cleanup();
  media.removeEventListener("change", applyTheme);
});
</script>
<template>
  <div class="studio-shell">
    <header class="app-header" @click="scrollToTop">
      <button
        type="button"
        class="brand"
        aria-label="有声书工坊，回到页面顶部"
        title="回到顶部"
        @click.stop="scrollToTop"
      >
        <span class="logo">🎧</span
        ><span
          ><strong>有声书工坊</strong
          ><small>EPUB · DOC · DOCX → 高品质语音</small></span
        ></button
      ><button
        class="theme-toggle"
        @click.stop="cycleTheme"
        aria-label="切换深浅色主题"
      >
        {{
          theme === "auto" ? "跟随系统" : theme === "light" ? "浅色" : "深色"
        }}
      </button>
    </header>
    <SegmentedControl
      class="main-nav"
      :navigation="true"
      label="主导航"
      :options="navigation"
      :model-value="route.path"
      @activate="(_value, keyboard) => (keyboardNavigation = keyboard)"
    />
    <div v-if="!store.connected" class="notice warning" role="status">
      连接已断开，正在重试。后台任务不会因此停止。
    </div>
    <div v-if="store.error" class="notice error" role="alert">
      <span>{{ store.error }}</span
      ><button
        class="quiet"
        @click="store.error = ''"
        aria-label="关闭错误提示"
      >
        关闭
      </button>
    </div>
    <div v-if="store.notice" class="notice" role="status">
      {{ store.notice }}
    </div>
    <section
      v-show="store.progressVisible && store.task?.kind !== 'split'"
      class="progress-card"
      aria-live="polite"
    >
      <div class="toolbar">
        <strong>{{
          store.task?.status === "succeeded"
            ? "已完成"
            : store.task?.status === "stopped"
              ? "已停止（可再次点击开始）"
              : store.task?.status === "failed"
                ? "任务失败"
                : store.task?.progress?.detail || "正在处理…"
        }}</strong
        ><span>{{ store.task?.progress?.pct || 0 }}%</span
        ><button
          v-if="store.busy"
          class="danger"
          @click="store.stop().catch(store.fail)"
        >
          停止任务
        </button>
      </div>
      <div class="progress-track">
        <div
          class="progress-fill"
          :style="{
            transform: `scaleX(${(store.task?.progress?.pct || 0) / 100})`,
          }"
        />
      </div>
    </section>
    <main
      class="page-stage"
      :class="{ 'route-backward': direction === 'backward' }"
    >
      <RouterView
        v-if="store.ready"
        v-slot="{ Component, route: currentRoute }"
      >
        <Transition :name="keyboardNavigation ? 'route-instant' : 'route'">
          <KeepAlive include="Generate"
            ><component :is="Component" :key="currentRoute.path"
          /></KeepAlive>
        </Transition>
      </RouterView>
      <div v-else class="empty" role="status">正在连接有声书工坊…</div>
    </main>
    <footer>有声书工坊 · 让每一本好书，都有声音</footer>
  </div>
</template>
