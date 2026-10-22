<script setup lang="ts">
import { ref, computed, watch, onMounted } from "vue";
import Field from "./Field.vue";
import SegmentedControl from "./SegmentedControl.vue";
import { api, send, upload, fileUrl } from "../api";
import { useStudio } from "../stores/studio";
const props = defineProps<{
  project: any;
  generation: () => any;
  provider: any;
}>();
const emit = defineEmits(["update:project"]);
const store = useStudio();
const projects = ref<any[]>([]),
  selected = ref(""),
  roleId = ref(""),
  tab = ref("voices"),
  chapter = ref(1),
  allPeople = ref(false),
  person = ref(""),
  voiceFilter = ref(""),
  scope = ref("all"),
  segment = ref<any>(null),
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
const casting = ref<any>(null),
  bank = ref(""),
  draft = ref<any>(null),
  raw = ref(""),
  pending = ref(false);
const script = computed(() => props.project?.script);
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
  chapterSegments.value.filter(
    (s) =>
      (!person.value || s.role_id === person.value) &&
      (!voiceFilter.value ||
        JSON.stringify(script.value.roles[s.role_id]?.provider_params) ===
          voiceFilter.value) &&
      (scope.value !== "pending" || s.speaker?.status !== "confirmed"),
  ),
);
const voices = computed(() =>
  Array.from(
    new Set(roles.value.map((r) => JSON.stringify(r.provider_params))),
  ).map((v) => ({
    value: v,
    label:
      JSON.parse(v).voice ||
      JSON.parse(v).voice_id ||
      JSON.parse(v).voice_description ||
      "参考音克隆",
  })),
);
watch(
  () => props.project,
  (p) => {
    if (p) {
      selected.value = p.id;
      raw.value = JSON.stringify(p.script, null, 2);
      if (!p.script.roles[roleId.value])
        roleId.value = Object.keys(p.script.roles)[0] || "";
    }
  },
  { immediate: true },
);
watch([roleId, () => props.project?.revision], () => {
  const r = script.value?.roles[roleId.value];
  if (r) {
    const p = r.provider_params;
    voice.value = {
      mode: p.voice_mode || "preset",
      voice: p.voice || p.voice_id || props.provider.voices[0],
      description: p.voice_description || "",
      language: p.voice_language || "zh",
      speed: p.speed || 1,
      instructions: p.instructions || "",
      pitch: p.pitch || 0,
      volume: p.volume ?? 1,
      reference_id: null,
    };
  }
});
watch(chapter, () => {
  segment.value = null;
  person.value = "";
  entity.value = "";
});
async function refresh() {
  projects.value = await api("/projects");
}
async function load() {
  try {
    emit("update:project", await api("/projects/" + selected.value));
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
  } catch (e) {
    store.fail(e);
  } finally {
    pending.value = false;
  }
}
async function task(kind: import("../api").TaskRequest["kind"]) {
  try {
    const result = await store.start({
      kind,
      generation: props.generation(),
      project_id: props.project?.id || null,
      revision: props.project?.revision ?? null,
      text: text.value,
      role_id: roleId.value || null,
      full_book: fullBook.value,
      bank_id: bank.value || null,
      language: voice.value.language,
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
    casting.value = await send("/projects/" + props.project.id + "/casting", {
      file_id: g.file_ids[0],
      provider: g.engine.provider,
      parser: g.parser,
    });
    draft.value = casting.value.draft;
  } catch (e) {
    store.fail(e);
  }
}
watch(
  () => store.lastTask?.status,
  async (status) => {
    if (status === "succeeded") {
      await refresh();
      if (store.lastTask?.result?.draft_id) draft.value = store.lastTask.result;
    }
  },
);
function applyDraft() {
  const g = props.generation();
  edit("casting_apply", {
    bank_id: bank.value,
    draft_id: draft.value.draft_id,
    rows: draft.value.rows,
    language: voice.value.language,
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
  <div class="section-space">
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
      <button :disabled="!selected" @click="load">载入项目</button
      ><button :disabled="store.busy" @click="task('split')">
        生成所选章节剧本</button
      ><Field label="允许建立全书人物索引" type="checkbox" v-model="fullBook" />
    </div>
    <p class="muted section-space">
      自动拆分使用设置中的 DeepSeek 配置，生成后需要复核并确认。
    </p>
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
      <SegmentedControl
        class="section-space"
        label="角色工作台"
        v-model="tab"
        :options="[
          { value: 'voices', label: '人物声音' },
          { value: 'review', label: '段落归属' },
          { value: 'casting', label: '全书声音分配' },
          { value: 'confirm', label: '复核与确认' },
        ]"
      />
      <div v-if="tab === 'voices'" class="role-layout">
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
              :options="provider.voices"
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
          <Field
            class="section-space"
            label="试听与校准文本"
            type="textarea"
            v-model="text"
          />
          <div class="toolbar section-space">
            <button :disabled="store.busy" @click="task('preview')">
              试听此人物</button
            ><button
              v-if="provider.id === 'openai'"
              :disabled="store.busy"
              @click="task('calibrate')"
            >
              以旁白校准全体语速
            </button>
          </div>
          <button
            v-if="provider.id === 'openai' && store.lastTask?.result?.audio"
            :disabled="store.busy"
            class="section-space"
            @click="
              edit('voice', {
                role_id: roleId,
                ...voice,
                mode: 'clone',
                reference_id: store.lastTask.result.audio.id,
              })
            "
          >
            将本次试听固定为此人物声音
          </button>
          <audio
            v-if="store.lastTask?.result?.audio"
            :src="fileUrl(store.lastTask.result.audio)"
            controls
          />
        </div>
      </div>
      <div v-if="tab === 'review'">
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
              ...people.map((r) => ({ value: r.id, label: r.display_name })),
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
              { value: 'pending', label: '待复核' },
            ]"
          /><Field
            label="指定本章叙述者"
            v-model="entity"
            :options="[
              { value: '', label: '选择人物' },
              ...people.map((r) => ({ value: r.id, label: r.display_name })),
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
                  <button class="quiet" @click="segment = s">
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
          <p class="segment-text">{{ segment.text }}</p>
          <details>
            <summary>展开前后文</summary>
            <p class="context">
              {{
                chapterSegments
                  .slice(
                    Math.max(0, chapterSegments.indexOf(segment) - 1),
                    chapterSegments.indexOf(segment),
                  )
                  .map((s) => s.text)
                  .join("")
                  .slice(-300)
              }}
            </p>
            <p class="context">
              {{
                chapterSegments
                  .slice(
                    chapterSegments.indexOf(segment) + 1,
                    chapterSegments.indexOf(segment) + 2,
                  )
                  .map((s) => s.text)
                  .join("")
                  .slice(0, 300)
              }}
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
            @click="
              edit('segment', {
                segment_id: segment.segment_id,
                entity_id: entity,
              })
            "
          >
            保存本段归属
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
            来源人物的段落将全部使用目标人物声音。
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
              edit('merge', { source_id: mergeSource, target_id: mergeTarget })
            "
          >
            确认合并人物
          </button>
        </details>
      </div>
      <div v-if="tab === 'casting'">
        <p class="muted">
          先核对全书正文覆盖，再使用已核验声音库分配声音。方案应用后仍需统一确认。
        </p>
        <div class="toolbar section-space">
          <button @click="castingStatus">读取覆盖与声音库</button
          ><button :disabled="store.busy" @click="task('casting_analyze')">
            分析全书（可续做）
          </button>
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
            ]"
          /><button
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
      </div></template
    >
  </div>
</template>
