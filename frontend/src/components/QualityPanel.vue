<script setup lang="ts">
import { ref, onMounted, watch } from "vue";
import GlassCard from "./GlassCard.vue";
import Field from "./Field.vue";
import { api, upload, fileUrl } from "../api";
import { useStudio } from "../stores/studio";
const props = defineProps<{ form: any; supported: boolean }>();
const store = useStudio();
const reports = ref<any[]>([]),
  selected = ref(""),
  report = ref<any>(null),
  preview = ref("");
async function refresh() {
  try {
    reports.value = await api("/quality/reports");
  } catch (e) {
    store.fail(e);
  }
}
async function load() {
  try {
    report.value = await api("/quality/reports/" + selected.value);
    preview.value = "";
  } catch (e) {
    store.fail(e);
  }
}
async function attach(e: Event, key: string) {
  try {
    const file = (e.target as HTMLInputElement).files?.[0];
    if (file) props.form[key] = (await upload(file)).id;
  } catch (e) {
    store.fail(e);
  }
}
watch(
  () => store.lastTask?.status,
  (status) => {
    if (status === "succeeded") refresh();
  },
);
onMounted(refresh);
</script>
<template>
  <GlassCard
    title="音频检查与修复"
    description="核对内容、拼接和角色声音，查看报告并试听问题片段。"
    ><div class="fields-grid">
      <Field
        label="检查生成的音频"
        type="checkbox"
        v-model="form.audio_core_enabled"
        :disabled="!supported"
      /><Field
        label="自动修复问题片段"
        type="checkbox"
        v-model="form.audio_core_repair"
        :disabled="!supported || !form.audio_core_enabled"
      />
    </div>
    <p class="muted section-space">
      {{
        supported
          ? "自动修复会增加合成请求，受次数与时限约束。"
          : "统一质量核心当前仅支持 MiMo。"
      }}
    </p>
    <details>
      <summary>高级设置文件</summary>
      <div class="fields-grid">
        <label class="field"
          ><span>质量设置 JSON</span
          ><input
            type="file"
            accept=".json"
            @change="attach($event, 'audio_core_settings_file')" /></label
        ><label class="field"
          ><span>声音分配 JSON</span
          ><input
            type="file"
            accept=".json"
            @change="attach($event, 'audio_core_casting_file')"
        /></label>
      </div>
    </details>
    <details>
      <summary>质量报告与试听</summary>
      <div class="toolbar">
        <select aria-label="质量报告" v-model="selected" @change="load">
          <option value="">选择报告</option>
          <option v-for="r in reports" :value="r.id">
            {{ r.name }} · {{ r.id.slice(0, 8) }}
          </option></select
        ><button @click="refresh">刷新报告</button
        ><a v-if="selected" class="button" :href="fileUrl(selected, true)"
          >下载报告</a
        >
      </div>
      <template v-if="report"
        ><p class="muted section-space">
          生成状态：{{
            report.summary.generation_status || report.summary.schema_version
          }}
        </p>
        <p class="muted">{{ report.message }}</p>
        <div class="table-wrap section-space">
          <table>
            <thead>
              <tr>
                <th>范围</th>
                <th>检查项</th>
                <th>问题</th>
                <th>判定</th>
                <th>时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, i) in report.rows" :key="i">
                <td v-for="(cell, j) in row" :key="j">{{ cell }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <Field
          label="问题片段试听"
          v-model="preview"
          :options="[
            { value: '', label: '选择片段' },
            ...report.previews.map((p: any) => ({
              value: p.id,
              label: p.label,
            })),
          ]" /><audio v-if="preview" :src="fileUrl(preview)" controls
      /></template>
      <p v-else-if="!reports.length" class="empty">
        尚无质量报告，完成检查后在这里查看。
      </p>
    </details></GlassCard
  >
</template>
