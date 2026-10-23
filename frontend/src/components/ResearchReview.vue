<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { api, send, fileUrl } from "../api";
import { useStudio } from "../stores/studio";
import { activeSeconds } from "../researchReview";
import ResearchDiff from "./ResearchDiff.vue";
import type { components } from "../generated/api";
type View = components["schemas"]["ResearchView"];
type State = Omit<View["state"], "script"> & { script: any };
const props = defineProps<{ project: any; generation: () => any }>();
const emit = defineEmits(["update:project"]);
const store = useStudio();
type ReviewTask = components["schemas"]["ReviewTask"];
const view = ref<View | null>(null),
  queue = ref<ReviewTask[]>([]),
  current = ref<ReviewTask | null>(null),
  session = ref<any>(null);
const loading = ref(false),
  error = ref(""),
  paused = ref(false),
  chosen = ref("");
const preview = ref<any>(null),
  pendingDecision = ref<any>(null),
  selectedProposal = ref("");
const mergeSource = ref(""),
  mergeTarget = ref(""),
  newName = ref(""),
  baseline = ref("");
const historical = ref<any[]>([]),
  download = ref<any>(null),
  offset = ref(0),
  total = ref(0);
const renderPreview = ref<components["schemas"]["RenderPreview"] | null>(null);
const createSegments = ref<string[]>([]);
let tick = performance.now(),
  shown = "";
let timerRunning = false;
let pending = 0;
const seconds = ref(0);
const operations = new Map<string, string>();
const state = computed(() => view.value?.state as State | undefined);
const people = computed(() =>
  Object.entries(state.value?.script.entities || {}).map(([id, e]: any) => ({
    id,
    name: e.canonical_name,
  })),
);
const busy = computed(() => loading.value || store.busy);
const remaining = computed(() =>
  Math.max(
    0,
    (session.value?.budget_seconds || 600) -
      (session.value?.elapsed_seconds || 0) -
      seconds.value,
  ),
);
const proposal = computed(() => state.value?.proposals[selectedProposal.value]);
const currentRows = computed(() => {
  const ids = new Set(current.value?.segment_ids || []);
  return (state.value?.script.chapters || [])
    .flatMap((c: any) => c.segments)
    .filter((s: any) => ids.has(s.segment_id));
});
const support = computed(() =>
  current.value?.kind === "segment"
    ? state.value?.decisions[current.value.id]?.evidence || []
    : state.value?.claims[current.value?.id || ""]?.evidence || [],
);
const opposition = computed(() =>
  (current.value?.kind === "segment"
    ? state.value?.decisions[current.value.id]?.against || []
    : []
  ).concat(
    state.value?.conflicts
      .filter(
        (c) =>
          c.status === "open" &&
          (c.refs.includes(current.value?.id || "") ||
            c.refs.some((id) => current.value?.segment_ids.includes(id))),
      )
      .flatMap((c) => c.evidence) || [],
  ),
);
const name = (id: string) =>
  state.value?.script.entities[id]?.canonical_name || "无法判断";
const relationName = (kind: string) =>
  ({
    same_entity: "同一人物",
    distinct_entity: "不同人物",
    mention_entity: "提及身份",
    narrator_entity: "叙述身份",
  })[kind] || kind;
const statusName = (status: string) =>
  ({
    accepted: "已确认",
    proposed: "待核对",
    rejected: "已否定",
    revoked: "已撤销",
  })[status] || status;
const subjectName = (id: string) => state.value?.mentions[id]?.text || name(id);
function write(key: string, extra: any = {}) {
  if (!operations.has(key)) operations.set(key, crypto.randomUUID());
  return {
    revision: state.value?.revision || props.project.revision,
    operation_id: operations.get(key),
    ...extra,
  };
}
async function mutate(path: string, extra: any = {}) {
  const key = path + JSON.stringify(extra);
  const result = await send<any>(
    `/projects/${props.project.id}/research${path}`,
    write(key, extra),
  );
  operations.delete(key);
  return result;
}
function adopt(value: View) {
  view.value = value;
  emit("update:project", value.project);
}
async function attempt(fn: () => Promise<void>) {
  pending += 1;
  loading.value = true;
  error.value = "";
  try {
    await fn();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    pending -= 1;
    loading.value = pending > 0;
  }
}
async function readQueue() {
  const path =
    `/projects/${props.project.id}/research/queue?offset=${offset.value}&limit=20` +
    (session.value ? `&session_id=${session.value.id}` : "");
  const value = await api<components["schemas"]["ReviewQueue"]>(path);
  if (value.revision !== state.value?.revision) return;
  const previous = current.value?.id;
  queue.value = value.items;
  total.value = value.total;
  current.value =
    value.recommendation ||
    queue.value.find((q) => q.id === current.value?.id) ||
    queue.value[0] ||
    null;
  if (current.value?.id !== previous || !chosen.value)
    chosen.value = currentRows.value[0]?.role_id || "";
}
async function refresh() {
  const value = await api<View>(`/projects/${props.project.id}/research`);
  if (value.state.revision < (state.value?.revision || props.project.revision))
    return;
  adopt(value);
  const sessions = Object.values(value.state.sessions);
  session.value = sessions.at(-1) || null;
  paused.value = Boolean(session.value?.paused);
  const proposals = Object.values(value.state.proposals);
  if (!selectedProposal.value || !value.state.proposals[selectedProposal.value])
    selectedProposal.value = proposals.at(-1)?.id || "";
  historical.value = (await api<any[]>("/tasks")).filter(
    (t) => t.project_id === props.project.id && t.render_snapshot,
  );
  if (!baseline.value) baseline.value = historical.value[0]?.id || "";
  await readQueue();
}
async function enable() {
  await attempt(async () => {
    adopt(await mutate("/enable"));
    await refresh();
  });
}
async function begin() {
  await attempt(async () => {
    session.value = await mutate("/sessions", {});
    seconds.value = 0;
    paused.value = false;
    await readQueue();
  });
}
async function event(
  kind: string,
  elapsed = 0,
  taskId = current.value?.id || "",
) {
  if (!session.value || !state.value) return;
  session.value = await mutate(`/sessions/${session.value.id}/events`, {
    event: { kind, task_id: taskId, elapsed_seconds: elapsed },
  });
}
async function flush(kind = "elapsed") {
  const elapsed = seconds.value;
  if (!session.value || !state.value) return;
  await event(kind, elapsed);
  seconds.value = Math.max(0, seconds.value - elapsed);
}
async function prepare(decision: any) {
  await attempt(async () => {
    preview.value = await mutate("/preview", { decision });
    pendingDecision.value = decision;
  });
}
async function commit() {
  await attempt(async () => {
    const taskId = current.value?.id || "";
    await flush();
    adopt(await mutate("/decisions", { decision: pendingDecision.value }));
    await event("answered", 0, taskId);
    preview.value = null;
    pendingDecision.value = null;
    await refresh();
  });
}
async function analyze(kind: "research_analyze" | "research_reanalyze") {
  await attempt(async () => {
    await store.start({
      kind,
      generation: props.generation(),
      project_id: props.project.id,
      revision: state.value!.revision,
    });
  });
}
async function apply(ids: string[]) {
  await attempt(async () => {
    adopt(
      await mutate(`/proposals/${selectedProposal.value}/apply`, {
        segment_ids: ids,
      }),
    );
    await refresh();
  });
}
async function skip() {
  await attempt(async () => {
    await flush("skip");
    await readQueue();
  });
}
async function togglePause() {
  await attempt(async () => {
    const next = !paused.value;
    await flush(next ? "pause" : "continue");
    paused.value = next;
    tick = performance.now();
  });
}
async function extend() {
  await attempt(async () => {
    await event("resume");
    paused.value = false;
    tick = performance.now();
    await readQueue();
  });
}
async function regenerate() {
  await attempt(async () => {
    await store.start({
      kind: "research_regenerate",
      generation: props.generation(),
      project_id: props.project.id,
      revision: state.value!.revision,
      baseline_task_id: baseline.value,
    });
  });
}
async function compareAudio() {
  await attempt(async () => {
    renderPreview.value = await mutate("/render-preview", {
      generation: props.generation(),
      baseline_task_id: baseline.value,
    });
  });
}
watch(
  [() => props.project?.id, () => props.project?.revision],
  async ([id], old) => {
    if (id !== old?.[0]) {
      view.value = null;
      session.value = null;
      preview.value = null;
      seconds.value = 0;
      selectedProposal.value = "";
    }
    if (props.project?.research_enabled) await attempt(refresh);
  },
  { immediate: true },
);
watch(
  () => `${store.lastTask?.id}:${store.lastTask?.status}`,
  async () => {
    const task = store.lastTask;
    if (
      state.value &&
      task &&
      task.project_id === props.project.id &&
      ["succeeded", "failed", "stopped"].includes(task.status)
    )
      await attempt(refresh);
  },
);
watch(
  () => current.value?.id,
  () => {
    preview.value = null;
    pendingDecision.value = null;
    createSegments.value = [];
  },
);
watch(
  [
    () => props.project?.revision,
    baseline,
    () => JSON.stringify(props.generation()),
  ],
  () => {
    renderPreview.value = null;
  },
);
const timer = setInterval(async () => {
  const now = performance.now();
  seconds.value += Math.min(
    remaining.value,
    activeSeconds(
      tick,
      now,
      document.visibilityState === "visible",
      paused.value ||
        busy.value ||
        !session.value ||
        session.value?.ended ||
        !current.value ||
        remaining.value <= 0,
    ),
  );
  tick = now;
  if (!state.value || busy.value || timerRunning) return;
  timerRunning = true;
  try {
    const identity = `${session.value?.id}:${state.value.revision}:${current.value?.id}`;
    if (
      session.value &&
      current.value &&
      !session.value.ended &&
      identity !== shown &&
      remaining.value > 0
    ) {
      shown = identity;
      await event("shown");
    }
    if (seconds.value >= 15 || (seconds.value > 0 && remaining.value <= 0)) {
      await flush();
      if (remaining.value <= 0) await readQueue();
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    timerRunning = false;
  }
}, 1000);
function visibilityChanged() {
  // 浏览器会节流后台计时器；切换时重置起点，避免回到前台后补算整段后台时间。
  tick = performance.now();
  if (document.visibilityState !== "visible" && !busy.value)
    void flush().catch(() => {});
}
document.addEventListener("visibilitychange", visibilityChanged);
onBeforeUnmount(() => {
  clearInterval(timer);
  document.removeEventListener("visibilitychange", visibilityChanged);
  void flush("pause").catch(() => {});
});
</script>

<template>
  <section aria-label="研究优先审阅" class="research-review">
    <div class="role-stage-heading">
      <div>
        <h3>优先审阅</h3>
        <p class="muted">
          先检查影响范围大的身份疑点，保留每次修改和原文依据。
        </p>
      </div>
      <button v-if="!state" :disabled="busy" @click="enable">
        启用研究审阅
      </button>
      <button v-else class="quiet" :disabled="busy" @click="attempt(refresh)">
        刷新审阅
      </button>
    </div>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <template v-if="state">
      <p v-if="state.history_incomplete" class="muted">
        启用前的合并历史不完整，已有结果保留。后续关系修改可以撤销。
      </p>
      <p role="status">
        待审 {{ view?.summary.pending }} 项 · 过期 {{ view?.summary.stale }} 段
        · 冲突 {{ view?.summary.conflicts }} 项
      </p>
      <div class="research-actions">
        <button :disabled="busy" @click="analyze('research_analyze')">
          分析人物依据
        </button>
        <button
          :disabled="
            busy || (!view?.summary.stale && !view?.summary.context_checks)
          "
          @click="analyze('research_reanalyze')"
        >
          重新分析受影响片段
        </button>
        <button
          v-if="!session || session.ended"
          :disabled="busy"
          @click="begin"
        >
          开始 10 分钟审阅
        </button>
        <template v-else
          ><span class="muted">剩余 {{ Math.ceil(remaining / 60) }} 分钟</span
          ><button :disabled="busy" @click="togglePause">
            {{ paused ? "继续计时" : "暂停计时" }}</button
          ><button
            :disabled="busy"
            @click="
              attempt(async () => {
                await flush('end');
              })
            "
          >
            结束审阅
          </button></template
        >
      </div>
      <p v-if="session && remaining <= 0" role="status">
        本次预算已用完，剩余条目尚未确认。<button
          :disabled="busy"
          @click="extend"
        >
          再审阅 10 分钟
        </button>
      </p>
      <div
        v-if="current && (!session || remaining > 0)"
        class="research-question"
      >
        <h4>
          {{
            current.kind === "segment" ? "核对片段说话人" : "核对人物身份关系"
          }}
        </h4>
        <p>
          {{ current.reason }}；可能影响
          {{ current.segment_ids.length }} 段，涉及第
          {{ current.chapters.join("、") }} 章。预计
          {{ Math.ceil(current.estimated_seconds) }} 秒。
        </p>
        <p v-if="current.audit" class="muted">本条为随机抽查。</p>
        <p v-if="!support.length && !opposition.length" class="muted">
          尚未记录可核对的引文，请展开原文检查。
        </p>
        <template v-if="support.length"
          ><h5>支持依据</h5>
          <blockquote v-for="(e, i) in support" :key="i">
            {{ e.quote }}
          </blockquote></template
        >
        <template v-if="opposition.length"
          ><h5>反对依据与冲突线索</h5>
          <blockquote v-for="(e, i) in opposition" :key="i">
            {{ e.quote }}
          </blockquote></template
        >
        <details>
          <summary>展开相关完整原文</summary>
          <p v-for="s in currentRows" :key="s.segment_id" class="segment-text">
            {{ s.text }}
          </p>
        </details>
        <template v-if="current.kind === 'segment'">
          <label class="research-field"
            >说话人<select v-model="chosen" :disabled="busy">
              <option v-for="p in people" :key="p.id" :value="p.id">
                {{ p.name }}
              </option>
            </select></label
          >
          <button
            :disabled="busy || !chosen"
            @click="
              prepare({
                action: 'segment',
                segment_id: current.id,
                entity_id: chosen,
              })
            "
          >
            预览归属修改
          </button>
        </template>
        <template v-else>
          <p>
            {{ relationName(state.claims[current.id]?.kind || "") }}：{{
              subjectName(state.claims[current.id]?.subject || "")
            }}
            → {{ name(state.claims[current.id]?.entity_id || "") }}
          </p>
          <div class="research-actions">
            <button
              :disabled="busy"
              @click="prepare({ action: 'accept', claim_id: current.id })"
            >
              确认这项关系</button
            ><button
              :disabled="busy"
              @click="prepare({ action: 'reject', claim_id: current.id })"
            >
              否定这项关系
            </button>
          </div>
        </template>
        <button class="quiet" :disabled="busy || !session" @click="skip">
          暂时无法判断，稍后处理
        </button>
      </div>
      <p v-else-if="!current" class="muted">
        当前没有可推荐条目。可按章检查，或补充人物分析。
      </p>
      <div v-if="preview" role="status" class="research-preview">
        <p>
          这次操作会改变 {{ preview.changes.length }} 段的当前人物，并重新检查
          {{ preview.affected_segments.length }} 段依赖判断。作用范围：第
          {{ preview.chapters.join("、") || "当前选择" }} 章。
        </p>
        <details v-if="preview.changes.length">
          <summary>查看人物变化</summary>
          <ul>
            <li v-for="c in preview.changes" :key="c.segment_id">
              {{ c.segment_id }}：{{ name(c.before) }} → {{ name(c.after) }}
            </li>
          </ul>
        </details>
        <button :disabled="busy" @click="commit">确认应用本次修改</button
        ><button class="quiet" @click="preview = null">保留原状</button>
      </div>
      <details class="role-disclosure">
        <summary>浏览审阅列表（共 {{ total }} 项）</summary>
        <ol class="research-list">
          <li v-for="item in queue" :key="item.id">
            <button
              class="quiet"
              @click="
                current = item;
                chosen = currentRows[0]?.role_id || '';
              "
            >
              {{ item.id }} · {{ item.reason }} ·
              {{ item.segment_ids.length }} 段
            </button>
          </li>
        </ol>
        <div class="research-actions">
          <button
            :disabled="offset === 0 || busy"
            @click="
              offset = Math.max(0, offset - 20);
              attempt(readQueue);
            "
          >
            上一页</button
          ><button
            :disabled="offset + 20 >= total || busy"
            @click="
              offset += 20;
              attempt(readQueue);
            "
          >
            下一页
          </button>
        </div>
      </details>
      <details class="role-disclosure">
        <summary>人物关系与撤销</summary>
        <div class="fields-grid">
          <label class="research-field"
            >来源人物<select v-model="mergeSource">
              <option value="">请选择</option>
              <option
                v-for="p in people.filter((p) => p.id !== 'narrator')"
                :key="p.id"
                :value="p.id"
              >
                {{ p.name }}
              </option>
            </select></label
          ><label class="research-field"
            >合并到人物<select v-model="mergeTarget">
              <option value="">请选择</option>
              <option
                v-for="p in people.filter((p) => p.id !== 'narrator')"
                :key="p.id"
                :value="p.id"
              >
                {{ p.name }}
              </option>
            </select></label
          >
        </div>
        <div class="research-actions">
          <button
            :disabled="
              busy ||
              !mergeSource ||
              !mergeTarget ||
              mergeSource === mergeTarget
            "
            @click="
              prepare({
                action: 'merge',
                source_id: mergeSource,
                target_id: mergeTarget,
              })
            "
          >
            预览全书身份合并</button
          ><button
            :disabled="
              busy ||
              !mergeSource ||
              !mergeTarget ||
              mergeSource === mergeTarget
            "
            @click="
              prepare({
                action: 'distinct',
                source_id: mergeSource,
                target_id: mergeTarget,
              })
            "
          >
            保持为不同人物
          </button>
        </div>
        <p class="muted">
          确认人物关系后，相关对白仍需单独审阅。候选别名状态保持原样。
        </p>
        <ul class="research-list">
          <li v-for="claim in state.claims" :key="claim.id">
            {{ relationName(claim.kind) }}：{{ subjectName(claim.subject) }} →
            {{ name(claim.entity_id) }} · {{ statusName(claim.status) }}
            <button
              v-if="claim.status === 'accepted'"
              class="quiet"
              :disabled="busy"
              @click="prepare({ action: 'revoke', claim_id: claim.id })"
            >
              预览撤销
            </button>
          </li>
        </ul>
        <label class="research-field"
          >缺失人物名称<input v-model="newName"
        /></label>
        <fieldset v-if="currentRows.length">
          <legend>选择要归给新人物的片段</legend>
          <label v-for="s in currentRows" :key="s.segment_id" class="check-row"
            ><input
              type="checkbox"
              v-model="createSegments"
              :value="s.segment_id"
            />{{ s.text }}</label
          >
        </fieldset>
        <button
          :disabled="busy || !newName.trim() || !createSegments.length"
          @click="
            prepare({
              action: 'create_entity',
              name: newName,
              segment_ids: createSegments,
            })
          "
        >
          为选中的 {{ createSegments.length }} 段创建人物
        </button>
      </details>
      <label v-if="Object.keys(state.proposals).length" class="research-field"
        >分析草稿<select v-model="selectedProposal">
          <option v-for="p in state.proposals" :key="p.id" :value="p.id">
            {{ p.id }} · {{ p.status }}
          </option>
        </select></label
      >
      <ResearchDiff
        v-if="proposal"
        :proposal="proposal"
        :state="state"
        :busy="busy"
        @apply="apply"
      />
      <details class="role-disclosure">
        <summary>更新音频与导出研究记录</summary>
        <p class="muted">
          剧本重新确认后，可按历史批次更新变化章节；旧音频保留。修订章节在资源库下载。
        </p>
        <label class="research-field"
          >历史生成批次<select v-model="baseline">
            <option value="">请选择</option>
            <option v-for="t in historical" :key="t.id" :value="t.id">
              {{ t.id.slice(0, 8) }} · 修订 {{ t.revision }} · {{ t.status }}
            </option>
          </select></label
        >
        <button :disabled="busy || !baseline" @click="compareAudio">
          比较当前合成计划
        </button>
        <p v-if="renderPreview" role="status">
          {{
            renderPreview.audio_current
              ? "所选批次的目标章节与当前配置一致。"
              : `所选批次有 ${renderPreview.changed_chapters.length} 章音频已过期或未完成：第 ${renderPreview.changed_chapters.join("、")} 章。`
          }}
        </p>
        <button
          :disabled="
            busy ||
            !baseline ||
            !project.confirmed ||
            !renderPreview ||
            renderPreview.audio_current
          "
          @click="regenerate"
        >
          重新生成变化章节
        </button>
        <div class="research-actions">
          <button
            :disabled="busy"
            @click="
              attempt(async () => {
                download = await mutate('/export', { mode: 'snapshot' });
              })
            "
          >
            导出研究快照</button
          ><button
            :disabled="busy"
            @click="
              attempt(async () => {
                download = await mutate('/export', { mode: 'events' });
              })
            "
          >
            导出审阅记录</button
          ><a v-if="download" :href="fileUrl(download, true)"
            >下载 {{ download.name }}</a
          >
        </div>
      </details>
    </template>
  </section>
</template>

<style scoped>
.research-review {
  margin-block: 20px 28px;
  padding-block: 20px;
  border-block: 1px solid var(--apple-border);
}
.research-review h4 {
  margin-block: 20px 8px;
}
.research-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-block: 14px;
}
.research-field {
  display: grid;
  gap: 8px;
  margin-block: 14px;
  min-width: 0;
}
.research-field select,
.research-field input {
  width: 100%;
  min-width: 0;
}
.research-question,
.research-preview {
  margin-block: 20px;
}
.research-list {
  padding-inline-start: 22px;
}
.research-list li {
  padding-block: 6px;
  overflow-wrap: anywhere;
}
blockquote {
  margin: 14px 0;
  padding: 0 16px;
  border-inline-start: 1px solid var(--apple-border);
}
</style>
