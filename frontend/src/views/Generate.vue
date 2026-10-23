<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import GlassCard from "../components/GlassCard.vue";
import BookUpload from "../components/BookUpload.vue";
import ChapterOverview from "../components/ChapterOverview.vue";
import Field from "../components/Field.vue";
import EngineFields from "../components/EngineFields.vue";
import VoiceProfilePicker from "../components/VoiceProfilePicker.vue";
import RoleStudio from "../components/RoleStudio.vue";
import QualityPanel from "../components/QualityPanel.vue";
import SegmentedControl from "../components/SegmentedControl.vue";
import SettingsDialog from "../components/SettingsDialog.vue";
import RoleModeSwitch from "../components/RoleModeSwitch.vue";
import ExpandPanel from "../components/ExpandPanel.vue";
import LiquidGlassEdge from "../components/LiquidGlassEdge.vue";
import WorkflowNav from "../components/WorkflowNav.vue";
import { api, send, upload, fileUrl, type FileRef } from "../api";
import { useStudio } from "../stores/studio";
const store = useStudio(),
  files = ref<FileRef[]>([]),
  catalog = ref<any>(null),
  catalogLoading = ref(false),
  catalogError = ref(""),
  uploading = ref(false),
  submitting = ref(false),
  stopping = ref(false),
  roleMode = ref(false),
  advancedOpen = ref(false),
  project = ref<any>(null),
  auditionText = ref("每一本好书，都值得被认真倾听。欢迎来到有声书工坊。");
const engineDrafts: Record<string, any> = {};
const defaults = store.bootstrap.settings;
const form = ref<any>({
  file_ids: [],
  engine: { ...store.bootstrap.providers[0].defaults },
  parser: {
    title_mode: "auto",
    newline_mode: "double",
    remove_endnotes: defaults.remove_endnotes,
    remove_reference_numbers: defaults.remove_reference_numbers,
    search_and_replace_file: null,
  },
  output_dir: "",
  worker_count: 1,
  log_level: "INFO",
  output_text: defaults.output_text,
  preview: defaults.preview,
  chapter_start: 1,
  chapter_end: -1,
  audio_core_enabled: !!store.bootstrap.providers[0].quality,
  audio_core_repair: false,
  role_quality_enabled: false,
  role_quality_max_rate: 4.3,
  allow_role_text_override: false,
  allow_role_title_mismatch: false,
  allow_role_fallback: false,
});
const provider = computed(() =>
  store.bootstrap.providers.find(
    (p: any) => p.id === form.value.engine.provider,
  ),
);
const audio = computed(() => store.lastTask?.result?.audio);
const workflowSteps = [
  {
    id: "book-setup",
    label: "书籍与章节",
    shortLabel: "书籍",
    detail: "上传与章节范围",
  },
  {
    id: "voice-setup",
    label: "选择声音",
    shortLabel: "声音",
    detail: "引擎与音色",
  },
  {
    id: "role-setup",
    label: "多角色配音",
    shortLabel: "多角色",
    detail: "可选 · 剧本与试听",
  },
  {
    id: "quality-setup",
    label: "音频检查",
    shortLabel: "检查",
    detail: "检查与修复设置",
  },
  {
    id: "generation-setup",
    label: "确认与生成",
    shortLabel: "生成",
    detail: "生成后到资源库下载",
  },
];
const stopPending = computed(
  () => stopping.value || store.task?.status === "stopping",
);
watch(
  () => store.task?.id,
  () => {
    if (store.task?.kind === "split" && store.busy) {
      roleMode.value = true;
    }
  },
  { immediate: true },
);
const startLabel = computed(() =>
  store.busy
    ? stopPending.value
      ? "正在停止…"
      : store.task?.kind === "generate"
        ? "停止生成"
        : "停止任务"
    : submitting.value
      ? "正在提交…"
      : form.value.preview && !roleMode.value
        ? "开始解析书籍"
        : "开始生成有声书",
);
let catalogTimer: ReturnType<typeof setTimeout> | undefined;
let catalogController: AbortController | undefined;
let catalogVersion = 0;
const catalogCache = new Map<string, any>();
watch(
  () =>
    JSON.stringify([
      form.value.parser,
      form.value.engine.provider,
      files.value.map((f) => f.id),
      uploading.value,
    ]),
  (next, previous) => {
    // 仅切换引擎时保留目录和所选范围，避免上方卡片先收起再展开。
    const [parser, , ids, loading] = JSON.parse(next);
    const prior = previous ? JSON.parse(previous) : [];
    const keepSelection =
      JSON.stringify(parser) === JSON.stringify(prior[0]) &&
      JSON.stringify(ids) === JSON.stringify(prior[2]) &&
      loading === prior[3];
    catalogVersion++;
    clearTimeout(catalogTimer);
    catalogController?.abort();
    if (!keepSelection) catalog.value = null;
    catalogError.value = "";
    catalogLoading.value = files.value.length === 1 && !uploading.value;
    if (catalogLoading.value)
      catalogTimer = setTimeout(() => chapters(keepSelection), 180);
  },
);
onUnmounted(() => {
  clearTimeout(catalogTimer);
  catalogController?.abort();
});
watch(
  () => store.lastTask?.result?.project,
  (p) => {
    if (p) project.value = p;
  },
);
function engine(id: string) {
  if (id === form.value.engine.provider) return;
  engineDrafts[form.value.engine.provider] = JSON.parse(
    JSON.stringify(form.value.engine),
  );
  form.value.engine = {
    ...(engineDrafts[id] ||
      store.bootstrap.providers.find((p: any) => p.id === id).defaults),
  };
  form.value.audio_core_enabled = !!provider.value.quality;
  if (!provider.value.roles) roleMode.value = false;
}
watch(
  () => form.value.audio_core_enabled,
  (enabled) => {
    if (enabled) form.value.worker_count = 1;
  },
);
async function addSelected(chosen: File[]) {
  if (uploading.value || store.busy || !chosen.length) return;
  uploading.value = true;
  try {
    for (const file of chosen) files.value.push(await upload(file));
  } catch (e) {
    store.fail(e);
  } finally {
    uploading.value = false;
  }
}
async function chapters(keepSelection = false) {
  if (files.value.length !== 1 || uploading.value) return;
  const version = ++catalogVersion;
  catalogController?.abort();
  catalogController = new AbortController();
  catalogLoading.value = true;
  catalogError.value = "";
  try {
    const payload = JSON.stringify({
      file_id: files.value[0].id,
      provider: form.value.engine.provider,
      parser: form.value.parser,
    });
    const result =
      catalogCache.get(payload) ||
      (await api("/books/chapters", {
        method: "POST",
        signal: catalogController.signal,
        body: payload,
      }));
    if (version !== catalogVersion) return;
    catalogCache.set(payload, result);
    catalog.value = result;
    const total = catalog.value.chapters.length;
    form.value.chapter_start = keepSelection
      ? Math.max(1, Math.min(form.value.chapter_start, total))
      : 1;
    form.value.chapter_end =
      keepSelection && form.value.chapter_end !== -1
        ? Math.max(
            form.value.chapter_start,
            Math.min(form.value.chapter_end, total),
          )
        : total;
  } catch (e) {
    if (
      version === catalogVersion &&
      !(e instanceof DOMException && e.name === "AbortError")
    ) {
      catalog.value = null;
      catalogError.value =
        e instanceof Error
          ? e.message
          : "目录暂时无法读取，可重试或使用数字章节范围。";
    }
  } finally {
    if (version === catalogVersion) catalogLoading.value = false;
  }
}
async function auxiliary(event: Event, key: string) {
  try {
    const f = (event.target as HTMLInputElement).files?.[0];
    if (f) form.value.parser[key] = (await upload(f)).id;
  } catch (e) {
    store.fail(e);
  }
}
function generation() {
  const g = JSON.parse(JSON.stringify(form.value));
  g.file_ids = files.value.map((f) => f.id);
  g.catalog_fingerprint = catalog.value?.fingerprint || null;
  if (!["openai", "minimax"].includes(g.engine.provider))
    g.voice_profile_id = g.voice_profile_version = null;
  if (roleMode.value && project.value) {
    g.voice_profile_id = g.voice_profile_version = null;
    g.project_id = project.value.id;
    g.project_revision = project.value.revision;
  }
  return g;
}
async function start() {
  submitting.value = true;
  try {
    if (!files.value.length) throw new Error("请先上传书籍文件。");
    if (roleMode.value && !project.value?.confirmed)
      throw new Error("请先载入并确认角色剧本。");
    await store.start({ generation: generation(), kind: "generate" });
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (e) {
    store.fail(e);
  } finally {
    submitting.value = false;
  }
}
async function primaryAction() {
  if (!store.busy) return start();
  if (stopPending.value) return;
  stopping.value = true;
  try {
    await store.stop();
  } catch (e) {
    store.fail(e);
  } finally {
    stopping.value = false;
  }
}
async function preview() {
  try {
    if (!auditionText.value.trim()) throw new Error("请输入试听文本。");
    const draft = generation();
    draft.file_ids = [];
    draft.catalog_fingerprint = null;
    draft.project_id = null;
    draft.project_revision = null;
    draft.audio_core_enabled = false;
    draft.audio_core_repair = false;
    draft.audio_core_settings_file = null;
    draft.audio_core_casting_file = null;
    await store.start({
      generation: draft,
      kind: "preview",
      text: auditionText.value.trim(),
    });
  } catch (e) {
    store.fail(e);
  }
}
async function persist(key: string, value: any) {
  try {
    await send("/preferences", { [key]: value }, "PATCH");
  } catch (e) {
    store.fail(e);
  }
}
</script>
<template>
  <div class="page-view generate-view">
    <div class="hero">
      <h1>让文字化作声音</h1>
      <p>从一本书开始，选好声音，再生成和下载。</p>
    </div>
    <WorkflowNav :steps="workflowSteps" />
    <GlassCard
      id="book-setup"
      class="workflow-section"
      role="region"
      aria-labelledby="workflow-link-book-setup"
      tabindex="0"
      title="书籍与章节"
      description="上传书籍，选择这次要生成的章节范围。"
      ><BookUpload
        :files="files"
        :uploading="uploading"
        :busy="store.busy"
        @select="addSelected"
        @remove="(index) => files.splice(index, 1)" />
      <div
        class="catalog-status"
        aria-live="polite"
        :aria-busy="catalogLoading"
      >
        <span v-if="catalogError" class="warning"
          >{{ catalogError }}
          <button class="quiet" @click="chapters()">重试读取</button></span
        >
        <span v-else class="muted">{{
          catalogLoading
            ? "正在读取章节目录…"
            : catalog
              ? `已自动读取 ${catalog.chapters.length} 章`
              : files.length > 1
                ? "批量转换使用共用数字范围"
                : "上传后自动读取章节目录"
        }}</span>
      </div>
      <div class="fields-grid section-space">
        <Field
          label="起始章节"
          v-model="form.chapter_start"
          :type="catalog ? undefined : 'number'"
          :options="
            catalog?.chapters.map((c: any) => ({
              value: c.index,
              label: `${c.index} · ${c.title}`,
            }))
          "
          :min="1"
        /><Field
          label="结束章节"
          v-model="form.chapter_end"
          :type="catalog ? undefined : 'number'"
          :options="
            catalog?.chapters.map((c: any) => ({
              value: c.index,
              label: `${c.index} · ${c.title}`,
            }))
          "
          hint="数字 -1 表示最后一章"
        />
      </div>
      <ChapterOverview
        v-if="catalog"
        :chapters="catalog.chapters"
        :start="form.chapter_start"
        :end="form.chapter_end" />
      <div class="advanced-settings-entry">
        <button
          type="button"
          class="advanced-settings-trigger"
          aria-haspopup="dialog"
          :aria-expanded="advancedOpen"
          @click="advancedOpen = true"
        >
          <svg
            aria-hidden="true"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linecap="round"
          >
            <path d="M4 7h9m4 0h3M4 17h3m4 0h9M13 4v6M7 14v6" />
          </svg>
          高级设置
        </button>
      </div>
      <SettingsDialog v-model="advancedOpen">
        <div class="fields-grid">
          <Field
            label="标题识别"
            v-model="form.parser.title_mode"
            :options="[
              { value: 'auto', label: '自动' },
              { value: 'tag_text', label: '标题标签' },
              { value: 'first_few', label: '开头文字' },
            ]"
          /><Field
            label="段落识别"
            v-model="form.parser.newline_mode"
            :options="[
              { value: 'single', label: '单换行' },
              { value: 'double', label: '双换行' },
              { value: 'none', label: '不按换行拆分' },
            ]"
          /><Field
            label="移除尾注"
            type="checkbox"
            v-model="form.parser.remove_endnotes"
            @update:model-value="persist('remove_endnotes', $event)"
          /><Field
            label="移除引用编号"
            type="checkbox"
            v-model="form.parser.remove_reference_numbers"
            @update:model-value="persist('remove_reference_numbers', $event)"
          /><Field
            label="服务端输出目录"
            v-model="form.output_dir"
            hint="留空自动创建书籍批次"
          /><Field
            label="章节并行数"
            type="number"
            :min="1"
            :max="16"
            v-model="form.worker_count"
            :disabled="form.audio_core_enabled"
            :hint="
              form.audio_core_enabled
                ? '统一音频检查使用单个 worker，控制模型内存与资源。'
                : '本地 GPU 引擎建议保持 1'
            "
          /><Field
            label="日志级别"
            v-model="form.log_level"
            :options="['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']"
          /><label class="field"
            ><span>替换规则文件</span
            ><input
              type="file"
              accept=".txt,.json,.csv"
              @change="auxiliary($event, 'search_and_replace_file')" /></label
          ><Field
            label="保存解析文字"
            type="checkbox"
            v-model="form.output_text"
            @update:model-value="persist('output_text', $event)"
          /><Field
            label="仅解析，不生成音频"
            type="checkbox"
            v-model="form.preview"
            @update:model-value="persist('preview', $event)"
          /></div></SettingsDialog></GlassCard
    ><GlassCard
      id="voice-setup"
      class="workflow-section"
      role="region"
      aria-labelledby="workflow-link-voice-setup"
      tabindex="0"
      title="选择声音"
      description="在线语音与本地模型共用相同的生成流程。"
      ><SegmentedControl
        label="语音引擎"
        :model-value="provider.id"
        :options="
          store.bootstrap.providers.map((p: any) => ({
            value: p.id,
            label: p.label,
          }))
        "
        @update:model-value="engine" />
      <EngineFields :engine="form.engine" :capability="provider" />
      <VoiceProfilePicker :generation="form" :disabled="roleMode" />
      <details class="voice-audition">
        <summary>试听当前声音</summary>
        <Field label="试听文本" type="textarea" v-model="auditionText" />
        <div class="toolbar section-space">
          <button :disabled="store.busy" @click="preview">开始试听</button
          ><span class="muted">首次加载本地声音可能需要较长时间。</span>
        </div>
        <audio
          v-if="audio"
          :src="fileUrl(audio)"
          controls
        /></details></GlassCard
    ><GlassCard
      id="role-setup"
      class="workflow-section"
      role="region"
      aria-labelledby="workflow-link-role-setup"
      tabindex="0"
      title="多角色配音"
      description="拆分人物与段落，设置声音，复核后统一确认。"
      ><RoleModeSwitch
        v-model="roleMode"
        :disabled="!provider.roles"
        controls="role-workspace" />
      <p v-if="!provider.roles" class="muted section-space">
        此引擎不支持多角色，请选择 MiMo 或 MiniMax。
      </p>
      <ExpandPanel id="role-workspace" :open="roleMode">
        <RoleStudio
          v-model:project="project"
          :generation="generation"
          :provider="provider"
          :split-ready="files.length === 1 && !uploading && !catalogLoading"
          :split-hint="
            uploading
              ? '正在上传书籍，请稍候。'
              : catalogLoading
                ? '正在读取章节目录，请稍候。'
                : files.length > 1
                  ? '多角色剧本每次处理一本书，请只保留一本。'
                  : '请先在上方上传一本书，并选择章节范围。'
          "
        />
        <details>
          <summary>角色高级设置</summary>
          <div class="fields-grid">
            <Field
              label="允许剧本文字覆盖"
              type="checkbox"
              v-model="form.allow_role_text_override"
            /><Field
              label="允许章节标题不一致"
              type="checkbox"
              v-model="form.allow_role_title_mismatch"
            /><Field
              label="允许旁白回退"
              type="checkbox"
              v-model="form.allow_role_fallback"
            /><Field
              label="旧版角色质量检查"
              type="checkbox"
              v-model="form.role_quality_enabled"
            /><Field
              label="角色最大语速"
              type="number"
              :min="0.1"
              :step="0.1"
              v-model="form.role_quality_max_rate"
            />
          </div>
        </details> </ExpandPanel></GlassCard
    ><QualityPanel
      id="quality-setup"
      class="workflow-section"
      role="region"
      aria-labelledby="workflow-link-quality-setup"
      tabindex="0"
      :form="form"
      :supported="provider.quality"
    />
    <GlassCard
      id="generation-setup"
      class="workflow-section"
      role="region"
      aria-labelledby="workflow-link-generation-setup"
      tabindex="0"
      title="确认与生成"
    >
      <div class="submit-bar">
        <div class="submit-context">
          <strong>{{
            store.busy
              ? "任务进行中"
              : files.length
                ? `已选择 ${files.length} 本书`
                : "等待上传书籍"
          }}</strong>
          <p id="generation-hint" class="muted" aria-live="polite">
            {{
              uploading
                ? "正在上传书籍，请稍候。"
                : catalogLoading
                  ? "正在读取章节目录，请稍候。"
                  : store.busy
                    ? store.task?.kind === "split"
                      ? "剧本正在后台生成，可在多角色配音模块查看进度或停止。"
                      : "任务正在后台执行，可在此停止，或到页面顶部查看进度。"
                    : !files.length
                      ? "上传书籍并选好声音，即可开始。"
                      : roleMode
                        ? "角色模式将执行真实合成；开始前请确认剧本。"
                        : form.preview
                          ? "本次只解析章节，不生成音频。"
                          : "生成期间可离开页面，稍后回来查看进度。"
            }}
          </p>
        </div>
        <button
          class="generate-button"
          :class="{ 'is-running': store.busy }"
          :aria-label="startLabel"
          aria-describedby="generation-hint"
          :aria-busy="submitting || stopPending"
          :disabled="
            store.busy
              ? stopPending
              : uploading || submitting || catalogLoading || !files.length
          "
          @click="primaryAction"
        >
          <LiquidGlassEdge />
          <span class="generate-button-play" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="currentColor">
              <rect
                v-if="store.busy"
                x="6"
                y="6"
                width="12"
                height="12"
                rx="2"
              />
              <path
                v-else
                d="M9 5.8a1 1 0 0 1 1.5-.86l9 5.2a1 1 0 0 1 0 1.72l-9 5.2A1 1 0 0 1 9 16.2Z"
              />
            </svg>
          </span>
          <span class="generate-button-label">{{ startLabel }}</span>
          <span class="generate-button-arrow" aria-hidden="true">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path
                :d="
                  store.busy ? 'm7 7 10 10M17 7 7 17' : 'M5 12h14m-6-6 6 6-6 6'
                "
              />
            </svg>
          </span>
        </button>
      </div>
    </GlassCard>
  </div>
</template>
