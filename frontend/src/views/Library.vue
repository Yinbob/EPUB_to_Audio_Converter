<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import GlassCard from "../components/GlassCard.vue";
import Field from "../components/Field.vue";
import SegmentedControl from "../components/SegmentedControl.vue";
import { api, send, fileUrl, type FileRef } from "../api";
import { useStudio } from "../stores/studio";
const store = useStudio(),
  batches = ref<any[]>([]),
  folder = ref(""),
  files = ref<FileRef[]>([]),
  selected = ref<string[]>([]),
  search = ref(""),
  ack = ref(false),
  archive = ref<FileRef | null>(null),
  preview = ref(""),
  autoDelete = ref(false),
  exportMode = ref("direct"),
  working = ref(false);
const filtered = computed(() =>
  files.value.filter((f) =>
    f.name.toLocaleLowerCase().includes(search.value.toLocaleLowerCase()),
  ),
);
const chosen = computed(() =>
  files.value.filter((f) => selected.value.includes(f.name)),
);
const audio = computed(() =>
  chosen.value.filter((f) =>
    ["mp3", "wav", "flac", "ogg", "m4a", "aac", "opus"].includes(f.category),
  ),
);
async function refresh() {
  try {
    batches.value = await api("/library");
    if (folder.value) await load(folder.value);
  } catch (e) {
    store.fail(e);
  }
}
async function load(name: string) {
  try {
    folder.value = name;
    files.value = await api(
      "/library/files?folder=" + encodeURIComponent(name),
    );
    selected.value = [];
    archive.value = null;
    preview.value = "";
    ack.value = false;
  } catch (e) {
    store.fail(e);
  }
}
async function zip() {
  working.value = true;
  try {
    archive.value = (
      await send("/library/archive", {
        folder: folder.value,
        names: selected.value,
      })
    ).file;
  } catch (e) {
    store.fail(e);
  } finally {
    working.value = false;
  }
}
async function remove(all = false) {
  if (!ack.value) return;
  try {
    await send("/library/delete", {
      folder: folder.value,
      names: all ? [] : selected.value,
      acknowledged: true,
    });
    if (all) {
      folder.value = "";
      files.value = [];
    }
    await refresh();
  } catch (e) {
    store.fail(e);
  }
}
async function downloaded() {
  if (autoDelete.value)
    store.notice =
      "ZIP 下载已发起。确认文件下载完成后，可在资源库勾选确认并清理源文件。";
}
onMounted(refresh);
</script>
<template>
  <div class="page-view">
    <div class="hero">
      <h1>你的声音资源库</h1>
      <p>按书籍批次管理、试听和下载生成的文件。</p>
    </div>
    <GlassCard title="已生成的文件"
      ><div class="toolbar">
        <button @click="refresh">刷新资源库</button
        ><span class="muted">{{ batches.length }} 个批次</span>
      </div>
      <div v-if="batches.length" class="split-layout section-space">
        <aside class="batch-list" aria-label="书籍批次">
          <button
            v-for="b in batches"
            :class="{ selected: folder === b.name }"
            @click="load(b.name)"
          >
            {{ b.label || b.name }}
          </button>
        </aside>
        <div v-if="folder">
          <Field label="搜索文件" v-model="search" />
          <div class="toolbar section-space">
            <button @click="selected = filtered.map((f) => f.name)">
              全选当前结果</button
            ><button @click="selected = []">取消全选</button
            ><span class="muted"
              >已选择 {{ chosen.length }} 个文件 ·
              {{
                (chosen.reduce((n, f) => n + f.size, 0) / 1024 / 1024).toFixed(
                  1,
                )
              }}
              MB</span
            >
          </div>
          <div class="section-space">
            <label v-for="f in filtered" :key="f.id" class="check-row"
              ><input
                type="checkbox"
                :value="f.name"
                v-model="selected"
                @change="archive = null"
              /><span>{{ f.name }}</span
              ><small>{{ (f.size / 1024).toFixed(0) }} KB</small></label
            >
          </div>
          <template v-if="chosen.length"
            ><Field
              class="section-space"
              label="试听文件"
              v-model="preview"
              :options="[
                { value: '', label: '选择音频' },
                ...audio.map((f) => ({ value: f.id, label: f.name })),
              ]"
            /><audio v-if="preview" :src="fileUrl(preview)" controls />
            <SegmentedControl
              class="section-space"
              label="下载方式"
              v-model="exportMode"
              :options="[
                { value: 'direct', label: '逐个下载' },
                { value: 'zip', label: 'ZIP 打包' },
              ]"
            />
            <div v-if="exportMode === 'direct'" class="file-list">
              <a v-for="f in chosen" class="button" :href="fileUrl(f, true)">{{
                f.name
              }}</a>
            </div>
            <template v-else
              ><button :disabled="working" @click="zip">
                {{ working ? "正在打包…" : "准备 ZIP" }}</button
              ><a
                v-if="archive"
                class="button primary"
                :href="fileUrl(archive, true)"
                @click="downloaded"
                >下载 ZIP</a
              ><Field
                class="section-space"
                label="下载后提醒清理源文件"
                type="checkbox"
                v-model="autoDelete"
              />
              <p class="muted">
                浏览器无法可靠确认下载完成，请完成下载后再手动清理。
              </p></template
            ></template
          >
          <details>
            <summary>清理文件</summary>
            <Field
              label="我已确认，删除后无法恢复"
              type="checkbox"
              v-model="ack"
            />
            <div class="toolbar section-space">
              <button
                class="danger"
                :disabled="!ack || !selected.length || store.busy"
                @click="remove()"
              >
                删除已选文件</button
              ><button
                class="danger"
                :disabled="!ack || store.busy"
                @click="remove(true)"
              >
                删除整个批次
              </button>
            </div>
          </details>
        </div>
        <p v-else class="empty">选择一个书籍批次查看文件。</p>
      </div>
      <p v-else class="empty">
        还没有生成的文件。先上传一本书，生成后会出现在这里。
      </p></GlassCard
    >
  </div>
</template>
