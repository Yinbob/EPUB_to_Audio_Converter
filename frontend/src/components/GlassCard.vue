<script setup lang="ts">
defineProps<{ title?: string; description?: string }>();
</script>
<template>
  <section class="app-card">
    <header v-if="title" class="card-heading">
      <h2>{{ title }}</h2>
      <p v-if="description">{{ description }}</p>
    </header>
    <slot />
  </section>
</template>
