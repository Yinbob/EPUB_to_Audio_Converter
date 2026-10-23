<script setup lang="ts">
import { computed, watch } from "vue";
import Field from "./Field.vue";
import { upload } from "../api";
import { useStudio } from "../stores/studio";
const props = defineProps<{ engine: any; capability: any }>();
const store = useStudio();
const fields = computed(() => props.capability.fields as Record<string, any>);
const labels: Record<string, string> = {
  model_name: "模型",
  voice_name: "音色",
  output_format: "输出格式",
  language: "朗读语言",
  speed: "语速",
  instructions: "朗读要求",
  stream: "流式合成",
  device: "设备",
  reference_audio: "参考音频",
  exaggeration: "语气夸张程度",
  cfg_weight: "CFG 引导权重",
  mode: "声音模式",
  voice: "预设音色",
  voice_dir: "服务端音色目录",
  voice_description: "声音描述",
  regenerate_voice: "重新生成预设参考",
  reference_text: "参考音频原文",
  auto_transcribe: "自动转写参考音频",
  denoise: "参考音频降噪",
  normalize: "文本规范化",
  cfg_value: "CFG 引导强度",
  inference_timesteps: "推理步数",
  chunk_chars: "每块字符数",
  optimize: "CUDA Graphs 优化",
  proxy: "代理地址",
  voice_rate: "语速变化（%）",
  voice_volume: "音量变化（%）",
  voice_pitch: "音高变化（Hz）",
  break_duration: "段落停顿（毫秒）",
};
function choices(key: string, field: any) {
  if (key === "voice_name" || key === "voice")
    return props.engine.provider === "edge"
      ? props.capability.voices.filter((v: { value: string }) =>
          v.value.startsWith(props.engine.language + "-"),
        )
      : props.capability.voices;
  if (key === "model_name")
    return props.capability.models.length ? props.capability.models : undefined;
  if (key === "output_format") return props.capability.formats;
  if (key === "language") return props.capability.languages;
  if (key === "device") return props.capability.devices;
  return field.enum;
}
watch(
  () => props.engine.language,
  () => {
    if (
      props.engine.provider === "edge" &&
      !props.engine.voice_name.startsWith(props.engine.language + "-")
    )
      props.engine.voice_name =
        props.capability.voices.find((v: { value: string }) =>
          v.value.startsWith(props.engine.language + "-"),
        )?.value || props.engine.voice_name;
  },
);
function kind(field: any, key: string) {
  return field.type === "boolean"
    ? "checkbox"
    : field.type === "number" || field.type === "integer"
      ? "number"
      : ["instructions", "voice_description", "reference_text"].includes(key)
        ? "textarea"
        : "text";
}
async function reference(e: Event) {
  try {
    const f = (e.target as HTMLInputElement).files?.[0];
    if (f) props.engine.reference_audio = (await upload(f)).id;
  } catch (e) {
    store.fail(e);
  }
}
</script>
<template>
  <div class="fields-grid">
    <template v-for="(field, key) in fields" :key="key"
      ><label v-if="key === 'reference_audio'" class="field"
        ><span>参考音频</span
        ><input type="file" accept="audio/*" @change="reference" /><small>{{
          engine.reference_audio ? "已上传参考音频" : "用于克隆或高保真模式"
        }}</small></label
      ><Field
        v-else-if="key !== 'provider'"
        :label="labels[key] || key"
        v-model="engine[key]"
        :type="kind(field, key)"
        :options="choices(key, field)"
        :allow-custom="capability.custom_fields?.includes(key)"
        :hint="
          key === 'device' && engine.provider === 'voxcpm'
            ? '多卡可填写 cuda:0、cuda:1'
            : undefined
        "
        :min="field.minimum"
        :max="field.maximum"
        :step="field.type === 'integer' ? 1 : 0.05"
    /></template>
  </div>
</template>
