<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api, fileUrl, send, upload } from "../api";
import { useStudio } from "../stores/studio";
import GlassCard from "./GlassCard.vue";
import Field from "./Field.vue";
import EngineFields from "./EngineFields.vue";
const store = useStudio(),
  profiles = ref<any[]>([]),
  selected = ref(""),
  id = ref("narrator"),
  label = ref("旁白"),
  language = ref("zh"),
  confirmed = ref(false);
const provider = ref("openai"),
  engine = ref<any>({
    ...store.bootstrap.providers.find((p: any) => p.id === "openai").defaults,
  });
const capability = computed(() =>
  store.bootstrap.providers.find((p: any) => p.id === provider.value),
);
const text = ref("每一本好书，都值得被认真倾听。这是本次声音配置的固定试听。"),
  reference = ref(""),
  voiceId = ref(""),
  submitting = ref(false),
  localTaskId = ref("");
const task = computed(() =>
  store.lastTask?.id === localTaskId.value ? store.lastTask : null,
);
const current = computed(() =>
  profiles.value.find((p) => p.id === selected.value),
);
function switchProvider(value: any) {
  provider.value = String(value);
  engine.value = { ...capability.value.defaults };
}
async function refresh() {
  profiles.value = await api("/voice-profiles");
}
async function attach(e: Event) {
  try {
    const f = (e.target as HTMLInputElement).files?.[0];
    if (f) reference.value = (await upload(f)).id;
  } catch (e) {
    store.fail(e);
  }
}
async function start(clone = false) {
  submitting.value = true;
  confirmed.value = false;
  try {
    const value = await store.start({
      kind: clone ? "voice_clone" : "preview",
      generation: { engine: engine.value, file_ids: [] },
      text: text.value,
      ...(clone
        ? { reference_id: reference.value, clone_voice_id: voiceId.value }
        : {}),
    });
    localTaskId.value = value.id;
  } catch (e) {
    store.fail(e);
  } finally {
    submitting.value = false;
  }
}
async function save() {
  try {
    await send("/voice-profiles", {
      task_id: localTaskId.value,
      id: current.value?.id || id.value,
      label: current.value?.label || label.value,
      language: current.value?.language || language.value,
      confirmed: confirmed.value,
      previous_version: current.value?.version || null,
    });
    await refresh();
    store.notice = "声音绑定已保存，历史版本仍然保留。";
  } catch (e) {
    store.fail(e);
  }
}
async function importCard(e: Event) {
  try {
    const f = (e.target as HTMLInputElement).files?.[0];
    if (f) {
      const file = await upload(f);
      await send("/voice-profiles/import", { file_id: file.id });
      await refresh();
      store.notice = "声音卡及参考音已导入。";
    }
  } catch (e) {
    store.fail(e);
  }
}
onMounted(() => refresh().catch(store.fail));
</script>
<template>
  <GlassCard
    title="可迁移声音卡"
    description="同一个逻辑声音可分别绑定 MiMo 和 MiniMax。声音卡 ZIP 包含固定版本、参考音与已确认试听；同名音色不代表同一声音。"
  >
    <div class="fields-grid">
      <Field
        label="逻辑声音"
        v-model="selected"
        :options="[
          { value: '', label: '新建声音卡' },
          ...profiles.map((p) => ({ value: p.id, label: p.label })),
        ]"
      />
      <template v-if="!current"
        ><Field label="逻辑 ID（字母数字 _ -）" v-model="id" /><Field
          label="声音名称"
          v-model="label" /><Field
          label="语言"
          v-model="language"
          :options="[
            { value: 'zh', label: '中文' },
            { value: 'en', label: '英语' },
          ]"
      /></template>
      <Field
        label="本次绑定的引擎"
        :model-value="provider"
        @update:model-value="switchProvider"
        :options="[
          { value: 'openai', label: 'MiMo' },
          { value: 'minimax', label: 'MiniMax' },
        ]"
      />
    </div>
    <EngineFields
      class="section-space"
      :engine="engine"
      :capability="capability"
    />
    <Field
      class="section-space"
      label="声音卡试听文本"
      type="textarea"
      v-model="text"
    />
    <details v-if="provider === 'minimax'" class="section-space">
      <summary>上传参考音并创建 MiniMax 克隆音色</summary>
      <p class="muted">
        使用 10 秒～5 分钟、20 MB 以内的 WAV/MP3/M4A。克隆上传和合成会调用当前
        MiniMax 账号；声音 ID 保存在该账号下。
      </p>
      <label class="field"
        ><span>MiniMax 克隆参考音</span
        ><input type="file" accept=".wav,.mp3,.m4a" @change="attach"
      /></label>
      <Field label="新 MiniMax 音色 ID" v-model="voiceId" />
      <button
        :disabled="store.busy || submitting || !reference || !voiceId"
        @click="start(true)"
      >
        上传、克隆并试听
      </button>
      <p
        v-if="task?.kind === 'voice_clone' && task?.status === 'succeeded'"
        class="muted"
      >
        克隆已完成，可确认保存本次声音卡绑定。后续也可将该 ID 填入引擎音色。
      </p>
    </details>
    <div class="toolbar section-space">
      <button :disabled="store.busy || submitting" @click="start()">
        生成声音卡试听</button
      ><button v-if="store.busy && task" class="danger" @click="store.stop">
        停止声音卡任务
      </button>
    </div>
    <audio
      v-if="task?.result?.audio"
      class="section-space"
      controls
      :src="fileUrl(task.result.audio)"
    />
    <a v-if="task?.result?.audio" :href="fileUrl(task.result.audio, true)"
      >下载本次试听</a
    >
    <Field
      class="section-space"
      label="已听完本次试听，确认作为此引擎的声音绑定"
      type="checkbox"
      v-model="confirmed"
    />
    <button
      :disabled="store.busy || !confirmed || task?.status !== 'succeeded'"
      @click="save"
    >
      保存本次绑定
    </button>
    <div v-if="current" class="section-space">
      <p>固定版本 {{ current.version.slice(0, 12) }}</p>
      <ul>
        <li
          v-for="b in current.bindings"
          :key="b.provider + b.model + b.endpoint"
        >
          {{ b.provider }} · {{ b.model }} · {{ b.endpoint }}
        </li>
      </ul>
      <a
        :href="`/api/v1/voice-profiles/${current.id}/${current.version}/export`"
        >导出声音卡 ZIP</a
      >
    </div>
    <label class="field section-space"
      ><span>导入声音卡 ZIP</span
      ><input
        type="file"
        accept=".zip"
        :disabled="store.busy"
        @change="importCard"
    /></label>
  </GlassCard>
</template>
