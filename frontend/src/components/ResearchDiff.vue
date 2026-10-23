<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { applicableChanges } from "../researchReview";
const props = defineProps<{ proposal: any; state: any; busy: boolean }>();
const emit = defineEmits<{ apply: [ids: string[]] }>();
const selected = ref<string[]>([]);
const available = computed(() =>
  applicableChanges(props.proposal, props.state.decisions),
);
watch(
  () => props.proposal,
  () => {
    selected.value = [...available.value];
  },
  { immediate: true },
);
const names = (id: string) =>
  props.state.script.entities[id]?.canonical_name || "无法判断";
const rows = computed(() =>
  Object.fromEntries(
    props.state.script.chapters.flatMap((c: any) =>
      c.segments.map((s: any) => [s.segment_id, s]),
    ),
  ),
);
</script>

<template>
  <section aria-label="重新分析差异" class="research-diff">
    <h4>重新分析差异</h4>
    <p class="muted">
      草稿尚未改变剧本。逐项选择后应用；已人工确认的片段保留。
    </p>
    <p v-if="proposal.status === 'stale'" role="status">
      此草稿已过期，请重新分析。
    </p>
    <div v-else class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>应用</th>
            <th>原文片段</th>
            <th>当前人物</th>
            <th>建议人物</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="change in proposal.changes" :key="change.segment_id">
            <td>
              <input
                v-model="selected"
                type="checkbox"
                :value="change.segment_id"
                :disabled="!available.includes(change.segment_id) || busy"
                :aria-label="`应用片段 ${change.segment_id}`"
              />
            </td>
            <td>
              {{ change.segment_id }}
              <span
                v-if="state.decisions[change.segment_id]?.status === 'human'"
                >（人工确认）</span
              >
              <details>
                <summary>原文与建议依据</summary>
                <p>{{ rows[change.segment_id]?.text }}</p>
                <blockquote
                  v-for="(e, i) in change.decision.evidence"
                  :key="`support-${i}`"
                >
                  支持：{{ e.quote }}
                </blockquote>
                <blockquote
                  v-for="(e, i) in change.decision.against"
                  :key="`against-${i}`"
                >
                  反对：{{ e.quote }}
                </blockquote>
              </details>
            </td>
            <td>{{ names(state.decisions[change.segment_id]?.entity_id) }}</td>
            <td>{{ names(change.decision.entity_id) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="proposal.conflicts.length" role="status">
      草稿带有 {{ proposal.conflicts.length }} 项冲突线索，请结合原文处理。
    </p>
    <ul v-if="proposal.conflicts.length">
      <li v-for="c in proposal.conflicts" :key="c.id">
        涉及 {{ c.refs.join("、") }}
        <blockquote v-for="(e, i) in c.evidence" :key="i">
          {{ e.quote }}
        </blockquote>
      </li>
    </ul>
    <button
      v-if="proposal.status === 'ready' || proposal.status === 'partial'"
      :disabled="busy || !selected.length"
      @click="emit('apply', selected)"
    >
      应用选中的 {{ selected.length }} 个建议
    </button>
  </section>
</template>
