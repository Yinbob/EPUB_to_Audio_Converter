<script setup lang="ts">
import { ref, computed, watch, onMounted } from "vue";
import Field from "./Field.vue";
import SegmentedControl from "./SegmentedControl.vue";
import ScriptStatus from "./ScriptStatus.vue";
import ResearchReview from "./ResearchReview.vue";
import { api, send, upload, fileUrl, active } from "../api";
import { useStudio } from "../stores/studio";
import {
  matchingRolePreview,
  nextReviewSegment,
  reviewSegments,
  scriptLanguage,
  segmentContext,
  voiceIdentity,
  voiceLabel,
} from "../roleReview";
const props = defineProps<{
  project: any;
  generation: () => any;
  provider: any;
  splitReady?: boolean;
  splitHint?: string;
}>();
const emit = defineEmits(["update:project"]);
const store = useStudio();
const projects = ref<any[]>([]),
  selected = ref(""),
  roleId = ref(""),
  tab = ref("prepare"),
  reviewMode = ref("chapter"),
  voiceTool = ref("voices"),
  chapter = ref(1),
  allPeople = ref(false),
  person = ref(""),
  voiceFilter = ref(""),
  scope = ref("all"),
  segmentId = ref(""),
  entity = ref(""),
  mergeSource = ref(""),
  mergeTarget = ref(""),
  text = ref(
    "每一本好书，都值得被认真倾听。让我们跟随书中的人物，走进他们各自的故事。",
  ),
  fullBook = ref(false);
const voice = ref<any>({
  mode: "preset",
  voice: "mimo_default",
  description: "",
  language: "zh",
  speed: 1,
  instructions: "",
  pitch: 0,
  volume: 1,
  reference_id: null,
});
const savedVoice = ref("");
const splitSubmitting = ref(false),
  splitError = ref(""),
  splitTaskId = ref("");
const splitTask = computed(() =>
  store.task?.kind === "split" &&
  (store.task.id === splitTaskId.value || active(store.task))
    ? store.task
    : null,
);
const splitBusy = computed(
  () => splitSubmitting.value || active(splitTask.value),
);
const workflowSteps = [
  { value: "prepare", label: "准备剧本", hint: "生成或导入" },
  { value: "voices", label: "人物声音", hint: "分配并试听" },
  { value: "review", label: "段落归属", hint: "核对原文与人物" },
  { value: "confirm", label: "复核与确认", hint: "确认后生成有声书" },
];
watch(
  () => props.project?.id,
  () => {
    reviewMode.value = props.project?.research_enabled ? "priority" : "chapter";
  },
);
watch(
  () => store.task,
  (task) => {
    if (task?.kind === "split" && active(task)) splitTaskId.value = task.id;
  },
  { immediate: true },
);
async function generateScript() {
  if (splitSubmitting.value || store.busy || !props.splitReady) return;
  splitSubmitting.value = true;
  tab.value = "prepare";
  splitError.value = "";
  try {
    if (!compatible.value)
      throw new Error("请切回项目对应的语音引擎，再生成剧本。");
    const result = await store.start({
      kind: "split",
      generation: props.generation(),
      project_id: props.project?.id || null,
      revision: props.project?.revision ?? null,
      full_book: fullBook.value,
    });
    splitTaskId.value = result.id;
  } catch (e) {
    splitError.value =
      e instanceof Error ? e.message : "提交失败，请检查 DeepSeek 连接后重试。";
  } finally {
    splitSubmitting.value = false;
  }
}
function textKindLabel(kind: string) {
  return (
    (
      { narration: "叙述", dialogue: "对白", unknown: "待判断" } as Record<
        string,
        string
      >
    )[kind] || "旧剧本未区分"
  );
}
const portableProfiles = ref<any[]>([]),
  portableProfile = ref("");
const voiceChanged = computed(
  () => savedVoice.value !== JSON.stringify(voice.value),
);
const casting = ref<any>(null),
  bank = ref(""),
  importedBank = ref<any>(null),
  bankInfo = ref<any>(null),
  bookLanguage = ref("zh"),
  draft = ref<any>(null),
  raw = ref(""),
  pending = ref(false);
const script = computed(() => props.project?.script);
const compatible = computed(
  () => !script.value || script.value.provider === props.provider.id,
);
const supportsCasting = computed(
  () =>
    compatible.value &&
    props.provider.id === "openai" &&
    script.value?.schema_version === 2,
);
const preview = computed(() =>
  matchingRolePreview(store.lastTask, props.project, roleId.value)
    ? store.lastTask
    : null,
);
const roleVoiceOptions = computed(() =>
  props.provider.role_voices?.length
    ? props.provider.role_voices
    : props.provider.voices,
);
const roles = computed(() =>
  Object.entries(script.value?.roles || {}).map(([id, r]: [string, any]) => ({
    id,
    ...r,
  })),
);
const chapters = computed<any[]>(() => script.value?.chapters || []);
const chapterSegments = computed<any[]>(
  () =>
    chapters.value.find((c: any) => c.chapter_index === Number(chapter.value))
      ?.segments || [],
);
const people = computed(() =>
  allPeople.value
    ? roles.value
    : roles.value.filter((r) =>
        chapterSegments.value.some((s) => s.role_id === r.id),
      ),
);
const segments = computed(() =>
  reviewSegments(
    script.value,
    Number(chapter.value),
    person.value,
    voiceFilter.value,
    scope.value,
  ),
);
const segment = computed(() =>
  chapterSegments.value.find((s) => s.segment_id === segmentId.value),
);
const context = computed(() =>
  segmentContext(chapterSegments.value, segmentId.value),
);
const voices = computed(() => {
  const groups = new Map<
    string,
    { value: string; label: string; names: string[]; count: number }
  >();
  for (const role of roles.value) {
    const value = voiceIdentity(script.value.provider, role.provider_params);
    const group = groups.get(value) || {
      value,
      label: voiceLabel(role.provider_params),
      names: [],
      count: 0,
    };
    const count = chapterSegments.value.filter(
      (s) => s.role_id === role.id,
    ).length;
    if (count) group.names.push(role.display_name);
    group.count += count;
    groups.set(value, group);
  }
  return Array.from(groups.values())
    .filter((g) => g.count)
    .map((g) => ({
      value: g.value,
      label: `${g.label} · ${g.names.slice(0, 3).join(" / ")} · ${g.count} 段`,
    }));
});
const usageRows = computed(() =>
  Object.entries(casting.value?.usage?.roles || {})
    .map(([id, r]: [string, any]) => ({ id, ...r }))
    .sort((a, b) => b.reading_count - a.reading_count),
);
const mergeCount = computed(() =>
  chapters.value.reduce(
    (sum, c) =>
      sum +
      c.segments.filter((s: any) => s.role_id === mergeSource.value).length,
    0,
  ),
);
const calibration = computed(() =>
  store.lastTask?.kind === "calibrate" &&
  store.lastTask?.result?.project?.id === props.project?.id
    ? store.lastTask?.result?.calibration
    : null,
);
watch(
  () => props.project,
  (p) => {
    if (p) {
      selected.value = p.id;
      raw.value = JSON.stringify(p.script, null, 2);
      if (!p.script.roles[roleId.value])
        roleId.value = Object.keys(p.script.roles)[0] || "";
      if (
        !p.script.chapters.some(
          (c: any) => c.chapter_index === Number(chapter.value),
        )
      )
        chapter.value = p.script.chapters[0]?.chapter_index || 1;
    }
  },
  { immediate: true },
);
watch(
  () => props.project?.id,
  () => {
    bookLanguage.value = scriptLanguage(script.value);
    casting.value = null;
    draft.value = null;
    bank.value = "";
    importedBank.value = null;
    bankInfo.value = null;
  },
  { immediate: true },
);
watch(
  [roleId, () => props.project?.revision],
  () => {
    const r = script.value?.roles[roleId.value];
    if (r) {
      const p = r.provider_params;
      voice.value = {
        mode: p.voice_mode || "preset",
        voice:
          p.voice ||
          p.voice_id ||
          props.provider.voices[0]?.value ||
          props.provider.voices[0],
        description: p.voice_description || "",
        language: p.voice_language || scriptLanguage(script.value),
        speed: p.speed || 1,
        instructions: p.instructions || "",
        pitch: p.pitch || 0,
        volume: p.volume ?? 1,
        reference_id: null,
      };
      savedVoice.value = JSON.stringify(voice.value);
    }
  },
  { immediate: true },
);
watch(supportsCasting, (enabled) => {
  if (!enabled) voiceTool.value = "voices";
});
watch(chapter, () => {
  segmentId.value = "";
  person.value = "";
  entity.value = "";
});
watch(segmentId, () => {
  entity.value = segment.value?.role_id || "";
});
async function refresh() {
  projects.value = await api("/projects");
  portableProfiles.value = await api("/voice-profiles");
}
async function applyPortableVoice() {
  const profile = portableProfiles.value.find(
    (p) => p.id === portableProfile.value,
  );
  if (!profile) return;
  await edit("portable_voice", {
    role_id: roleId.value,
    voice_profile_id: profile.id,
    voice_profile_version: profile.version,
    model_name: props.generation().engine.model_name,
  });
}
async function load() {
  try {
    emit("update:project", await api("/projects/" + selected.value));
    tab.value = "voices";
  } catch (e) {
    store.fail(e);
  }
}
async function imported(e: Event) {
  try {
    const file = (e.target as HTMLInputElement).files?.[0];
    if (!file) return;
    const f = await upload(file);
    emit("update:project", await send("/projects/import", { file_id: f.id }));
    tab.value = "voices";
    await refresh();
  } catch (e) {
    store.fail(e);
  }
}
async function edit(operation: string, data: any = {}) {
  pending.value = true;
  try {
    const result = await send(
      "/projects/" + props.project.id,
      { revision: props.project.revision, operation, data },
      "PATCH",
    );
    emit("update:project", result);
    await refresh();
    return result;
  } catch (e) {
    store.fail(e);
  } finally {
    pending.value = false;
  }
}
async function task(kind: import("../api").TaskRequest["kind"]) {
  try {
    if (!compatible.value)
      throw new Error("请切回项目对应的语音引擎，再操作此项目。");
    const result = await store.start({
      kind,
      generation: props.generation(),
      project_id: props.project?.id || null,
      revision: props.project?.revision ?? null,
      text: text.value,
      role_id: roleId.value || null,
      full_book: fullBook.value,
      bank_id: bank.value || null,
      language: kind.startsWith("casting_")
        ? bookLanguage.value
        : voice.value.language,
    });
    return result;
  } catch (e) {
    store.fail(e);
  }
}
async function reference(e: Event) {
  try {
    const file = (e.target as HTMLInputElement).files?.[0];
    if (file) voice.value.reference_id = (await upload(file)).id;
  } catch (e) {
    store.fail(e);
  }
}
async function castingStatus() {
  try {
    const g = props.generation();
    casting.value = await send(
      "/projects/" +
        props.project.id +
        "/casting?language=" +
        bookLanguage.value,
      {
        file_id: g.file_ids[0],
        provider: g.engine.provider,
        parser: g.parser,
      },
    );
    draft.value = casting.value.draft;
  } catch (e) {
    store.fail(e);
  }
}
async function selectBank() {
  bankInfo.value = null;
  if (!bank.value) return;
  try {
    bankInfo.value = await send("/casting/bank", {
      file_id: bank.value,
      language: bookLanguage.value,
    });
  } catch (e) {
    store.fail(e);
  }
}
async function importBank(event: Event) {
  try {
    const file = (event.target as HTMLInputElement).files?.[0];
    if (!file) return;
    const uploaded = await upload(file);
    const info = await send<any>("/casting/bank", {
      file_id: uploaded.id,
      language: bookLanguage.value,
    });
    importedBank.value = { id: uploaded.id, label: `导入 · ${uploaded.name}` };
    bank.value = uploaded.id;
    bankInfo.value = info;
  } catch (e) {
    store.fail(e);
  }
}
watch(bank, async () => {
  draft.value = null;
  await selectBank();
});
watch(bookLanguage, async () => {
  draft.value = null;
  if (casting.value && props.project && supportsCasting.value)
    await castingStatus();
  await selectBank();
});
async function saveSegment() {
  if (!segment.value) return;
  const selectedId = segmentId.value;
  const before = segments.value;
  const result = await edit("segment", {
    segment_id: selectedId,
    entity_id: entity.value,
  });
  if (result)
    segmentId.value = nextReviewSegment(
      before,
      reviewSegments(
        result.script,
        Number(chapter.value),
        person.value,
        voiceFilter.value,
        scope.value,
      ),
      selectedId,
    );
}
watch(
  () => store.lastTask?.status,
  async (status) => {
    if (status === "succeeded") {
      await refresh();
      if (store.lastTask?.project_id === props.project?.id) {
        if (store.lastTask?.result?.draft_id)
          draft.value = store.lastTask.result;
        if (store.lastTask?.kind === "casting_analyze") await castingStatus();
      }
    }
  },
);
function applyDraft() {
  const g = props.generation();
  edit("casting_apply", {
    bank_id: bank.value,
    draft_id: draft.value.draft_id,
    rows: draft.value.rows,
    language: bookLanguage.value,
    book: {
      file_id: g.file_ids[0],
      provider: g.engine.provider,
      parser: g.parser,
    },
  });
}
function saveJson() {
  try {
    edit("replace", JSON.parse(raw.value));
  } catch (e) {
    store.fail(e);
  }
}
onMounted(() => refresh().catch(store.fail));
</script>
<template>
  <div class="role-workflow section-space">
    <nav aria-label="多角色配音步骤" class="role-workflow-nav">
      <ol>
        <li v-for="(step, index) in workflowSteps" :key="step.value">
          <button
            type="button"
            :aria-label="step.label"
            :aria-current="tab === step.value ? 'step' : undefined"
            :disabled="
              (!project && step.value !== 'prepare') ||
              (splitBusy && step.value !== 'prepare')
            "
            @click="tab = step.value"
          >
            <span class="role-step-number" aria-hidden="true">{{
              index + 1
            }}</span>
            <span
              ><strong>{{ step.label }}</strong
              ><small>{{ step.hint }}</small></span
            >
          </button>
        </li>
      </ol>
    </nav>
    <div
      v-if="script?.registry_warnings?.length"
      class="notice warning"
      role="status"
    >
      <div>
        <strong
          >人物索引有 {{ script.registry_warnings.length }} 处待复核</strong
        >
        <p>
          已保留有效人物，少量无法定位的候选姓名或别名已排除。请在「段落归属」中核对。
        </p>
        <details class="role-disclosure">
          <summary>查看人物索引提示</summary>
          <ul>
            <li
              v-for="warning in script.registry_warnings"
              :key="`${warning.chapter_index}:${warning.chunk_start}`"
            >
              {{ warning.message }}
            </li>
          </ul>
        </details>
      </div>
    </div>
    <section
      v-show="tab === 'prepare'"
      class="role-stage"
      aria-labelledby="role-prepare-title"
    >
      <div class="script-prepare">
        <div>
          <h3 id="role-prepare-title">准备本次配音的剧本</h3>
          <p class="muted">
            按上方选择的章节，分析人物与段落；使用「设置」中的 DeepSeek 连接。
          </p>
        </div>
        <button
          type="button"
          class="primary script-generate"
          :class="{ 'is-preparing': splitBusy }"
          :disabled="
            store.busy || splitSubmitting || !splitReady || !compatible
          "
          :aria-busy="splitBusy"
          @click="generateScript"
        >
          <svg
            class="script-generate-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            aria-hidden="true"
          >
            <template v-if="splitBusy">
              <circle cx="12" cy="12" r="9" opacity=".25" />
              <path d="M12 3a9 9 0 0 1 9 9" stroke-linecap="round" />
            </template>
            <path
              v-else
              d="M8 4h8l4 4v12H4V4h4m8 0v5h4M8 13h8m-8 4h5"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
          <span>
            {{
              splitBusy
                ? "正在准备剧本…"
                : project
                  ? "DeepSeek 重新生成剧本"
                  : "DeepSeek 生成剧本"
            }}
          </span>
        </button>
      </div>
      <details class="role-disclosure">
        <summary>
          <span>人物索引范围</span
          ><small>{{ fullBook ? "全书" : "仅所选章节" }}</small>
        </summary>
        <Field
          label="允许建立全书人物索引"
          type="checkbox"
          v-model="fullBook"
          :disabled="store.busy || splitSubmitting"
        />
      </details>
      <p v-if="!splitReady && !splitBusy" class="muted">{{ splitHint }}</p>
      <ScriptStatus
        :task="splitTask"
        :submitting="splitSubmitting"
        :error="splitError"
      >
        <template #stop
          ><button
            type="button"
            class="danger"
            :disabled="splitTask?.status === 'stopping'"
            @click="store.stop().catch(store.fail)"
          >
            停止生成剧本
          </button></template
        >
      </ScriptStatus>
      <div v-if="project" class="role-next">
        <p class="muted">
          已有 {{ chapters.length }} 章剧本、{{ roles.length }}
          个人物，可继续配置声音。
        </p>
        <button :disabled="splitBusy" @click="tab = 'voices'">
          下一步：分配人物声音 <span aria-hidden="true">→</span>
        </button>
      </div>
      <details class="script-import role-disclosure">
        <summary>
          <span>导入剧本或载入已有项目</span><small>V1 / V2 JSON</small>
        </summary>
        <p class="muted">已有剧本时可直接导入，无需再次调用 DeepSeek。</p>
        <div class="fields-grid">
          <Field
            label="已有角色项目"
            v-model="selected"
            :options="[
              { value: '', label: '选择项目' },
              ...projects.map((p) => ({
                value: p.id,
                label: `${p.id.slice(0, 12)} · 修订 ${p.revision}`,
              })),
            ]"
          /><label class="field"
            ><span>导入 V1 / V2 剧本</span
            ><input
              type="file"
              accept=".json"
              :disabled="store.busy"
              @change="imported"
          /></label>
        </div>
        <div class="toolbar section-space">
          <button :disabled="!selected || store.busy" @click="load">
            载入项目
          </button>
        </div>
      </details>
    </section>
    <template v-if="project"
      ><div class="toolbar section-space">
        <span class="project-status"
          >修订 {{ project.revision }} ·
          {{ project.confirmed ? "已确认，可生成" : "待复核确认" }}</span
        ><span class="spacer" /><a
          class="button"
          :href="fileUrl(project.file, true)"
          >导出剧本</a
        >
      </div>
      <p v-if="!compatible" class="warning section-space">
        当前项目使用
        {{
          script.provider === "openai" ? "MiMo" : "MiniMax"
        }}。请切回对应引擎后继续；已有剧本和人物配置已保留。
      </p>
      <fieldset
        :disabled="!compatible"
        style="border: 0; padding: 0; margin: 0; min-width: 0"
      >
        <div v-if="tab !== 'prepare'" class="role-stage-heading">
          <h3>{{ workflowSteps.find((step) => step.value === tab)?.label }}</h3>
          <p class="muted">
            {{
              tab === "voices"
                ? "为每个人物选择声音，保存参数后试听。"
                : tab === "review"
                  ? "结合原文与判断依据，核对每段应由谁朗读。"
                  : "检查人物、章节与声音设置，确认后即可生成有声书。"
            }}
          </p>
        </div>
        <SegmentedControl
          v-if="tab === 'voices' && supportsCasting"
          class="role-voice-tools"
          label="声音分配方式"
          v-model="voiceTool"
          :options="[
            { value: 'voices', label: '逐人物配置' },
            { value: 'casting', label: '全书声音分配' },
          ]"
        />
        <div
          v-if="tab === 'voices' && voiceTool === 'voices'"
          class="role-layout"
        >
          <div class="role-list" aria-label="人物列表">
            <button
              v-for="r in roles"
              :key="r.id"
              :class="{ selected: roleId === r.id }"
              @click="roleId = r.id"
            >
              {{ r.display_name }}<small>{{ r.gender }}</small>
            </button>
          </div>
          <div v-if="roleId">
            <div class="fields-grid">
              <Field
                v-if="provider.id === 'openai'"
                label="声音来源"
                v-model="voice.mode"
                :options="[
                  { value: 'preset', label: '内置声音' },
                  { value: 'design', label: '描述设计' },
                  { value: 'clone', label: '参考音克隆' },
                ]"
              /><Field
                v-if="voice.mode === 'preset' || provider.id !== 'openai'"
                label="音色"
                v-model="voice.voice"
                :options="roleVoiceOptions"
              /><Field
                v-if="voice.mode === 'design'"
                label="声音描述"
                type="textarea"
                v-model="voice.description"
              /><label v-if="voice.mode === 'clone'" class="field"
                ><span>克隆参考音</span
                ><input type="file" accept=".wav" @change="reference" /><small
                  >已保存的参考音可保持不变；换声音时上传新参考。</small
                ></label
              ><Field
                label="朗读语言"
                v-model="voice.language"
                :options="[
                  { value: 'zh', label: '中文' },
                  { value: 'en', label: '英语' },
                ]"
              /><Field
                label="角色语速"
                v-model="voice.speed"
                type="number"
                :min="provider.id === 'openai' ? 0.25 : 0.5"
                :max="provider.id === 'openai' ? 4 : 2"
                :step="0.05"
              /><Field
                v-if="provider.id === 'openai'"
                label="朗读要求"
                type="textarea"
                v-model="voice.instructions"
              /><template v-else
                ><Field
                  label="音高"
                  v-model="voice.pitch"
                  type="number"
                  :min="-12"
                  :max="12" /><Field
                  label="音量"
                  v-model="voice.volume"
                  type="number"
                  :min="0"
                  :max="10"
                  :step="0.1"
              /></template>
            </div>
            <div class="toolbar section-space">
              <button
                class="primary"
                :disabled="store.busy || pending"
                @click="edit('voice', { role_id: roleId, ...voice })"
              >
                保存声音参数</button
              ><button
                :disabled="store.busy"
                @click="edit('lock', { entity_id: roleId, locked: true })"
              >
                锁定声音</button
              ><button
                :disabled="store.busy"
                @click="edit('lock', { entity_id: roleId, locked: false })"
              >
                解除锁定
              </button>
            </div>
            <div v-if="script.schema_version === 2" class="section-space">
              <Field
                label="此人物的逻辑声音卡"
                v-model="portableProfile"
                :options="[
                  { value: '', label: '选择已确认声音卡' },
                  ...portableProfiles.map((p) => ({
                    value: p.id,
                    label: p.label,
                  })),
                ]"
              />
              <button
                class="section-space"
                :disabled="
                  store.busy || pending || !portableProfile || !compatible
                "
                @click="applyPortableVoice"
              >
                应用声音卡并锁定版本
              </button>
            </div>
            <Field
              class="section-space"
              label="试听与校准文本"
              type="textarea"
              v-model="text"
            />
            <p v-if="voiceChanged" class="muted section-space">
              声音参数尚未保存，请先保存，再试听或校准。
            </p>
            <div class="toolbar section-space">
              <button
                :disabled="store.busy || voiceChanged"
                @click="task('preview')"
              >
                试听此人物</button
              ><button
                v-if="provider.id === 'openai'"
                :disabled="store.busy || voiceChanged"
                @click="task('calibrate')"
              >
                以旁白校准全体语速
              </button>
            </div>
            <button
              v-if="provider.id === 'openai' && preview"
              :disabled="store.busy || voiceChanged"
              class="section-space"
              @click="
                edit('freeze_preview', {
                  role_id: roleId,
                  task_id: preview.id,
                })
              "
            >
              将本次试听固定为此人物声音
            </button>
            <audio
              v-if="preview"
              :src="fileUrl(preview.result.audio)"
              controls
            />
            <div v-if="calibration" class="table-wrap section-space">
              <p>
                已以
                {{
                  script.roles[calibration.baseline]?.display_name ||
                  calibration.baseline
                }}
                为基准校准，请继续试听各人物。
              </p>
              <table>
                <thead>
                  <tr>
                    <th>人物</th>
                    <th>原试听时长</th>
                    <th>建议倍率</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(speed, id) in calibration.speeds" :key="id">
                    <td>{{ script.roles[id]?.display_name || id }}</td>
                    <td>
                      {{ (calibration.durations_ms[id] / 1000).toFixed(2) }} 秒
                    </td>
                    <td>{{ Number(speed).toFixed(3) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
        <div v-if="tab === 'review'">
          <SegmentedControl
            v-model="reviewMode"
            label="审阅方式"
            :options="[
              { value: 'chapter', label: '按章浏览' },
              { value: 'priority', label: '优先审阅' },
            ]"
          />
          <ResearchReview
            v-if="reviewMode === 'priority'"
            :project="project"
            :generation="generation"
            @update:project="emit('update:project', $event)"
          />
          <template v-else>
            <div class="fields-grid">
              <Field
                label="当前核对章节"
                v-model="chapter"
                :options="
                  chapters.map((c) => ({
                    value: c.chapter_index,
                    label: `${c.chapter_index} · ${c.title}`,
                  }))
                "
              /><Field
                label="显示全书人物"
                type="checkbox"
                v-model="allPeople"
              /><Field
                label="按人物检索"
                v-model="person"
                :options="[
                  { value: '', label: '全部人物' },
                  ...people.map((r) => ({
                    value: r.id,
                    label: r.display_name,
                  })),
                ]"
              /><Field
                label="按配置音色检索"
                v-model="voiceFilter"
                :options="[{ value: '', label: '全部音色' }, ...voices]"
              /><Field
                label="复核范围"
                v-model="scope"
                :options="[
                  { value: 'all', label: '全部段落' },
                  { value: 'dialogue', label: '仅对白' },
                  { value: 'pending', label: '待复核' },
                ]"
              /><Field
                label="指定本章叙述者"
                v-model="entity"
                :options="[
                  { value: '', label: '选择人物' },
                  ...people.map((r) => ({
                    value: r.id,
                    label: r.display_name,
                  })),
                ]"
              />
            </div>
            <button
              class="section-space"
              :disabled="!entity || store.busy"
              @click="
                edit('narrator', {
                  chapter_index: Number(chapter),
                  entity_id: entity,
                })
              "
            >
              应用到本章叙述段
            </button>
            <div class="table-wrap section-space">
              <table>
                <thead>
                  <tr>
                    <th>人物</th>
                    <th>原文</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="s in segments" :key="s.segment_id">
                    <td>{{ script.roles[s.role_id]?.display_name }}</td>
                    <td>
                      <button class="quiet" @click="segmentId = s.segment_id">
                        {{ s.text.slice(0, 100) }}
                      </button>
                    </td>
                    <td>{{ s.speaker?.status || "已导入" }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <template v-if="segment"
              ><h3>当前完整原文</h3>
              <p class="muted">
                段落类型：{{ textKindLabel(segment.text_kind) }} · 配置音色：{{
                  voiceLabel(
                    script.roles[segment.role_id]?.provider_params || {},
                  )
                }}
              </p>
              <p class="segment-text">{{ segment.text }}</p>
              <p class="section-space">
                <strong>判断依据：</strong
                >{{
                  segment.speaker?.evidence
                    ?.map((e: any) => `${e.kind}：${e.quote}`)
                    .join("；") || "暂无明确原文证据，请结合上下文判断。"
                }}
              </p>
              <details>
                <summary>展开前后文</summary>
                <p class="context">
                  {{ context.before || "（本章开头）" }}
                </p>
                <p class="context">
                  {{ context.after || "（本章结尾）" }}
                </p>
              </details>
              <Field
                label="本段朗读人物"
                v-model="entity"
                :options="
                  people.map((r) => ({ value: r.id, label: r.display_name }))
                "
              /><button
                :disabled="!entity || store.busy"
                class="section-space"
                @click="saveSegment"
              >
                保存本段归属，继续下一段
              </button></template
            >
            <details>
              <summary>合并重复人物（作用于全书已保存章节）</summary>
              <div class="fields-grid">
                <Field
                  label="来源人物"
                  v-model="mergeSource"
                  :options="
                    people
                      .filter((r) => r.id !== 'narrator')
                      .map((r) => ({ value: r.id, label: r.display_name }))
                  "
                /><Field
                  label="目标人物"
                  v-model="mergeTarget"
                  :options="
                    people
                      .filter((r) => r.id !== 'narrator')
                      .map((r) => ({ value: r.id, label: r.display_name }))
                  "
                />
              </div>
              <p class="muted section-space">
                {{ script.roles[mergeSource]?.display_name || "来源人物" }} →
                {{
                  script.roles[mergeTarget]?.display_name || "目标人物"
                }}：将全书已保存章节中的
                {{ mergeCount }}
                段并入目标人物，保留目标人物声音。只有确认为同一人时才合并。
              </p>
              <button
                class="section-space"
                :disabled="
                  !mergeSource ||
                  !mergeTarget ||
                  mergeSource === mergeTarget ||
                  store.busy
                "
                @click="
                  edit('merge', {
                    source_id: mergeSource,
                    target_id: mergeTarget,
                  })
                "
              >
                确认合并人物
              </button>
            </details>
          </template>
        </div>
        <div
          v-if="tab === 'voices' && voiceTool === 'casting' && supportsCasting"
        >
          <p class="muted">
            先核对全书正文覆盖，再使用已核验声音库分配声音。方案应用后仍需统一确认。
          </p>
          <div class="toolbar section-space">
            <button @click="castingStatus">读取覆盖与声音库</button
            ><button :disabled="store.busy" @click="task('casting_analyze')">
              分析全书（可续做）
            </button>
          </div>
          <div class="fields-grid section-space">
            <Field
              label="本书语言"
              v-model="bookLanguage"
              :options="[
                { value: 'zh', label: '中文' },
                { value: 'en', label: '英语' },
              ]"
            />
            <label class="field"
              ><span>导入已核验声音探针库</span
              ><input
                type="file"
                accept=".json"
                :disabled="store.busy"
                @change="importBank"
              /><small>需包含至少两条共同探针；不自动付费建库。</small></label
            >
          </div>
          <template v-if="casting"
            ><p>
              全书 {{ casting.coverage.total }} 章，已覆盖
              {{ casting.coverage.complete.length }} 章
            </p>
            <Field
              label="已核验声音库"
              v-model="bank"
              :options="[
                { value: '', label: '选择声音库' },
                ...casting.banks.map((b: any) => ({
                  value: b.id,
                  label: b.label,
                })),
                ...(importedBank
                  ? [{ value: importedBank.id, label: importedBank.label }]
                  : []),
              ]"
            />
            <p v-if="bankInfo" class="muted section-space">
              {{ bankInfo.summary }}
            </p>
            <div v-if="casting.usage" class="table-wrap section-space">
              <table>
                <thead>
                  <tr>
                    <th>人物</th>
                    <th>朗读字／词数</th>
                    <th>预计分钟</th>
                    <th>出场章数</th>
                    <th>最长缺席章数</th>
                    <th>待核对段数</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="r in usageRows" :key="r.id">
                    <td>{{ r.display_name }}</td>
                    <td>{{ r.reading_count }}</td>
                    <td>{{ (r.estimated_seconds / 60).toFixed(2) }}</td>
                    <td>{{ r.active_chapters }}</td>
                    <td>{{ r.max_absent_chapters }}</td>
                    <td>{{ r.pending_segments }}</td>
                  </tr>
                  <tr v-if="casting.usage.unassigned?.segments">
                    <td>未知归属（不参与人物排名）</td>
                    <td>{{ casting.usage.unassigned.reading_count }}</td>
                    <td colspan="4">
                      {{ casting.usage.unassigned.segments }} 段
                    </td>
                  </tr>
                </tbody>
              </table>
              <p class="muted">
                时长为估算；出场统计包括人物对白和第一人称自述。
              </p>
            </div>
            <button
              class="section-space"
              :disabled="!bank || store.busy || !casting.coverage.full_book"
              @click="task('casting_draft')"
            >
              生成声音方案
            </button></template
          ><template v-if="draft"
            ><div class="table-wrap section-space">
              <table>
                <thead>
                  <tr>
                    <th>人物 ID</th>
                    <th>人物</th>
                    <th>来源</th>
                    <th>声音</th>
                    <th>声音描述</th>
                    <th>朗读要求</th>
                    <th>依据</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in draft.rows">
                    <td v-for="(cell, i) in row">
                      <textarea
                        v-if="i === 4 || i === 5"
                        v-model="row[i]"
                        :aria-label="i === 4 ? '声音描述' : '朗读要求'"
                      /><span v-else>{{ cell }}</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <button
              class="primary section-space"
              :disabled="store.busy || !bank"
              @click="applyDraft"
            >
              应用声音方案
            </button></template
          >
        </div>
        <div v-if="tab === 'confirm'">
          <p v-if="project.research_enabled" role="status" class="muted">
            研究审阅剩余
            {{
              project.research_pending
            }}
            项尚未逐项核对。确认表示接受当前配置，不会把这些条目标为已审。
          </p>
          <p>
            共 {{ roles.length }} 个人物，{{ chapters.length }}
            个已保存章节。请确认人物、正文归属和声音参数。
          </p>
          <button
            class="primary"
            :disabled="store.busy || pending"
            @click="edit('confirm')"
          >
            确认剧本与角色参数
          </button>
          <details>
            <summary>完整剧本 JSON 编辑</summary>
            <p class="muted">保存前会验证完整剧本；修改后需要重新确认。</p>
            <textarea
              v-model="raw"
              aria-label="完整剧本 JSON"
              style="min-height: 360px"
            /><button :disabled="store.busy" @click="saveJson">
              校验并保存完整剧本
            </button>
          </details>
        </div>
        <div v-if="tab === 'voices' || tab === 'review'" class="role-next">
          <p class="muted">
            {{
              tab === "voices"
                ? "声音配置完成后，继续核对段落与人物。"
                : "确认每段的朗读人物后，完成最后复核。"
            }}
          </p>
          <button @click="tab = tab === 'voices' ? 'review' : 'confirm'">
            {{
              tab === "voices" ? "下一步：核对段落归属" : "下一步：复核与确认"
            }}
            <span aria-hidden="true">→</span>
          </button>
        </div>
      </fieldset></template
    >
  </div>
</template>
