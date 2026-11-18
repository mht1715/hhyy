<script setup>
import {computed} from 'vue'
import {ExternalLink} from 'lucide-vue-next'

const props = defineProps({
  traceId: {type: String, default: ''}
})

const host = String(import.meta.env.VITE_LANGFUSE_HOST || '').replace(/\/+$/, '')

const url = computed(() => (
  props.traceId && host ? `${host}/trace/${props.traceId}` : ''
))

const shortId = computed(() => {
  const id = String(props.traceId || '')
  return id.length > 10 ? `${id.slice(0, 10)}…` : id
})
</script>

<template>
  <a
      v-if="url"
      :href="url"
      target="_blank"
      rel="noopener noreferrer"
      class="trace-link"
      title="在 Langfuse 中查看完整链路"
  >
    <ExternalLink :size="11"/>
    <span>Trace {{ shortId }}</span>
  </a>
</template>

<style scoped lang="scss">
.trace-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 8px;
  border-radius: 8px;
  border: 1px solid #fef2f2;
  background: #fff;
  color: #b91c1c;
  font-size: 11px;
  line-height: 18px;
  text-decoration: none;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;

  &:hover {
    background: #fef2f2;
  }
}
</style>
