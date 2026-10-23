<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "../api";
import Field from "./Field.vue";
import { useStudio } from "../stores/studio";
const props = defineProps<{ generation: any; disabled?: boolean }>();
const profiles = ref<any[]>([]),
  selected = ref(props.generation.voice_profile_id || ""),
  store = useStudio();
async function refresh() {
  try {
    profiles.value = await api("/voice-profiles");
  } catch (e) {
    store.fail(e);
  }
}
function choose(value: any) {
  selected.value = String(value);
  const profile = profiles.value.find((p) => p.id === selected.value);
  props.generation.voice_profile_id = profile?.id || null;
  props.generation.voice_profile_version = profile?.version || null;
}
onMounted(refresh);
</script>
<template>
  <div
    v-if="['openai', 'minimax'].includes(generation.engine.provider)"
    class="section-space"
  >
    <Field
      label="逻辑声音卡"
      :disabled="disabled"
      hint="用于单声音朗读；多角色模式请在下方逐个人物分配声音。"
      :model-value="selected"
      @update:model-value="choose"
      :options="[
        { value: '', label: '使用上方引擎参数' },
        ...profiles.map((p) => ({ value: p.id, label: p.label })),
      ]"
    />
    <p v-if="selected" class="muted">
      已固定版本
      {{
        generation.voice_profile_version?.slice(0, 12)
      }}。声音卡参数用于整本朗读；当前模型须有已试听确认的绑定。角色模式请逐个人物应用声音卡。
    </p>
    <button type="button" class="quiet" @click="refresh">刷新声音卡</button>
  </div>
</template>
