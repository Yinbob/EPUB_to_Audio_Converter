<script setup lang="ts">
defineProps<{ modelValue: boolean; disabled?: boolean }>();
const emit = defineEmits<{ "update:modelValue": [value: boolean] }>();
</script>

<template>
  <label
    class="role-mode-switch"
    :class="{ 'is-on': modelValue, 'is-disabled': disabled }"
  >
    <input
      type="checkbox"
      aria-label="启用多角色配音"
      :checked="modelValue"
      :disabled="disabled"
      @change="
        emit('update:modelValue', ($event.target as HTMLInputElement).checked)
      "
    />
    <span class="role-mode-symbol" aria-hidden="true">
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.7"
        stroke-linecap="round"
      >
        <circle cx="9" cy="8" r="3" />
        <path
          d="M3 20v-2a6 6 0 0 1 12 0v2M16 5a3 3 0 0 1 0 6m2 3a5 5 0 0 1 3 4v2"
        />
      </svg>
    </span>
    <span class="role-mode-copy">
      <strong>启用多角色配音</strong>
      <small>{{
        disabled
          ? "当前引擎暂不支持"
          : modelValue
            ? "已开启，为旁白和人物分配声音"
            : "让旁白与人物拥有各自的声音"
      }}</small>
    </span>
    <span class="role-mode-track" aria-hidden="true">
      <span class="role-mode-state">{{ modelValue ? "开启" : "关闭" }}</span>
      <span class="role-mode-thumb"
        ><svg
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="m4 8 3 3 5-6" /></svg
      ></span>
    </span>
  </label>
</template>
