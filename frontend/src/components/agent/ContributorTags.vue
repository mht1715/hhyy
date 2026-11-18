<script setup>
import {computed} from 'vue'

const props = defineProps({
  contributors: {type: Array, default: () => []}
})

const list = computed(() => (Array.isArray(props.contributors) ? props.contributors : [])
  .filter((item) => item && (item.name || item.code)))
</script>

<template>
  <div v-if="list.length" class="contributor-tags">
    <span
        v-for="contributor in list"
        :key="contributor.code || contributor.name"
        class="contributor-chip"
        :title="contributor.summary || ''"
    >
      <span class="dot"></span>
      @{{ contributor.name || contributor.code }} 提供
    </span>
  </div>
</template>

<style scoped lang="scss">
.contributor-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;

  .contributor-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    max-width: 100%;
    padding: 1px 8px;
    border-radius: 999px;
    background: #fff;
    border: 1px solid #f3f4f6;
    color: #6b7280;
    font-size: 11px;
    line-height: 1.7;
    white-space: nowrap;

    .dot {
      width: 5px;
      height: 5px;
      border-radius: 50%;
      background: #ef4444;
      flex-shrink: 0;
    }
  }
}
</style>
