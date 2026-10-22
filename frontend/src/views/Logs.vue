<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from "vue";
import GlassCard from "../components/GlassCard.vue";
import Field from "../components/Field.vue";
import { api, active, type Task } from "../api";
import { useStudio } from "../stores/studio";
const store = useStudio(),
  tasks = ref<Task[]>([]),
  selected = ref(""),
  text = ref(""),
  cursor = ref<number | undefined>(),
  follow = ref(true);
let timer: ReturnType<typeof setTimeout> | undefined,
  disposed = false;
async function refresh() {
  try {
    tasks.value = await api("/tasks");
    if (!selected.value)
      selected.value = store.task?.id || tasks.value[0]?.id || "";
  } catch (e) {
    store.fail(e);
  }
}
async function logs() {
  clearTimeout(timer);
  const key = selected.value;
  if (!key) return;
  try {
    const data = await api(
      `/tasks/${key}/logs` +
        (cursor.value === undefined ? "" : `?cursor=${cursor.value}`),
    );
    if (key !== selected.value) return;
    text.value = (text.value + data.text).split("\n").slice(-2000).join("\n");
    cursor.value = data.cursor;
    const current = await api<Task>("/tasks/" + key);
    if (!disposed && follow.value && active(current))
      timer = setTimeout(logs, 2000);
  } catch (e) {
    store.fail(e);
    if (!disposed && follow.value) timer = setTimeout(logs, 2000);
  }
}
watch(selected, () => {
  cursor.value = undefined;
  text.value = "";
  logs();
});
watch(follow, () => {
  if (follow.value) logs();
  else clearTimeout(timer);
});
onMounted(refresh);
onUnmounted(() => {
  disposed = true;
  clearTimeout(timer);
});
</script>
<template>
  <div class="page-view">
    <div class="hero">
      <h1>运行日志</h1>
      <p>查看每一次生成、拆分与试听任务的执行记录。</p>
    </div>
    <GlassCard title="任务记录"
      ><div class="fields-grid">
        <Field
          label="选择任务"
          v-model="selected"
          :options="
            tasks.map((t) => ({
              value: t.id,
              label: `${new Date(t.created_at * 1000).toLocaleString()} · ${t.kind} · ${t.status}`,
            }))
          "
        /><Field label="自动更新运行日志" type="checkbox" v-model="follow" />
      </div>
      <div class="toolbar section-space">
        <button @click="refresh">刷新任务列表</button
        ><button :disabled="!selected" @click="logs">读取最新日志</button>
      </div>
      <pre v-if="selected" class="logs" tabindex="0" aria-label="任务日志">{{
        text || "等待任务输出…"
      }}</pre>
      <p v-else class="empty">尚无任务记录。</p></GlassCard
    >
  </div>
</template>
