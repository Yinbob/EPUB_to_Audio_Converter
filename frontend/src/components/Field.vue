<script setup lang="ts">
import { useId } from "vue";
const props = defineProps<{
  label: string;
  modelValue?: any;
  type?: string;
  options?: any[];
  allowCustom?: boolean;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
  hint?: string;
}>();
const optionsId = useId();
const emit = defineEmits(["update:modelValue"]);
function update(event: Event, type?: string) {
  const t = event.target as HTMLInputElement;
  const option = props.options?.find(
    (o) => String(typeof o === "object" ? o.value : o) === t.value,
  );
  if (props.options) {
    emit(
      "update:modelValue",
      option === undefined
        ? t.value
        : typeof option === "object"
          ? option.value
          : option,
    );
    return;
  }
  emit(
    "update:modelValue",
    type === "checkbox"
      ? t.checked
      : type === "number" || type === "range"
        ? Number(t.value)
        : t.value,
  );
}
</script>
<template>
  <label class="field" :class="{ 'switch-field': type === 'checkbox' }"
    ><span
      >{{ label }}
      <output v-if="type === 'range'">{{ modelValue }}</output></span
    ><select
      v-if="options && !allowCustom"
      :aria-label="label"
      :value="modelValue"
      :disabled="disabled"
      @change="update($event)"
    >
      <option
        v-for="o in options"
        :key="typeof o === 'object' ? o.value : o"
        :value="typeof o === 'object' ? o.value : o"
      >
        {{ typeof o === "object" ? o.label : o }}
      </option></select
    ><textarea
      v-else-if="type === 'textarea'"
      :aria-label="label"
      :value="modelValue"
      :disabled="disabled"
      @input="update($event)"
    /><input
      v-else
      :aria-label="label"
      :type="type || 'text'"
      :value="type === 'checkbox' ? undefined : modelValue"
      :checked="type === 'checkbox' ? modelValue : undefined"
      :min="min"
      :max="max"
      :step="step"
      :list="allowCustom && options ? optionsId : undefined"
      :disabled="disabled"
      @input="update($event, type)"
    /><datalist v-if="allowCustom && options" :id="optionsId">
      <option
        v-for="o in options"
        :key="typeof o === 'object' ? o.value : o"
        :value="typeof o === 'object' ? o.value : o"
        :label="typeof o === 'object' ? o.label : o"
      /></datalist
    ><small v-if="hint">{{ hint }}</small></label
  >
</template>
