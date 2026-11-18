<script setup>
import {computed} from 'vue'
import {ArrowUpRight} from 'lucide-vue-next'

const props = defineProps({
  agent: {type: Object, required: true}
})

const emit = defineEmits(['select'])

const name = computed(() => props.agent.name || props.agent.code || 'Agent')
const code = computed(() => props.agent.code || props.agent.agent_code || '')
const initial = computed(() => {
  const text = name.value.trim()
  return text ? text.charAt(0) : 'A'
})

const capabilities = computed(() => {
  const list = Array.isArray(props.agent.capabilities) ? props.agent.capabilities : []
  if (list.length > 0) return list.slice(0, 4)
  const tools = Array.isArray(props.agent.tools) ? props.agent.tools : []
  return tools.slice(0, 4).map((tool) => `工具：${tool}`)
})

const go = () => emit('select', props.agent)
</script>

<template>
  <div
      class="agent-card"
      role="button"
      tabindex="0"
      @click="go"
      @keydown.enter.prevent="go"
      @keydown.space.prevent="go"
  >
    <div class="card-head">
      <div class="avatar">
        <img v-if="agent.avatar" :src="agent.avatar" :alt="name"/>
        <span v-else>{{ initial }}</span>
      </div>
      <div class="head-info">
        <h3 class="name">{{ name }}</h3>
        <span class="code">{{ code }}</span>
      </div>
      <ArrowUpRight :size="16" class="arrow"/>
    </div>

    <p class="description">{{ agent.description || '这个 Agent 还没有填写描述。' }}</p>

    <div v-if="capabilities.length" class="capabilities">
      <span v-for="capability in capabilities" :key="capability" class="cap-tag">
        {{ capability }}
      </span>
    </div>

    <div class="card-foot">
      <span class="entry">进入对话</span>
      <span class="entry-arrow">→</span>
    </div>
  </div>
</template>

<style scoped lang="scss">
.agent-card {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 18px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid #f3f4f6;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;

  &:hover,
  &:focus-visible {
    transform: translateY(-2px);
    border-color: #fecaca;
    box-shadow: 0 10px 24px rgba(239, 68, 68, 0.1);
    outline: none;
  }

  .card-head {
    display: flex;
    align-items: center;
    gap: 12px;

    .avatar {
      width: 44px;
      height: 44px;
      flex-shrink: 0;
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      background: linear-gradient(135deg, #ef4444, #b91c1c);
      color: #fff;
      font-size: 18px;
      font-weight: 700;

      img {
        width: 100%;
        height: 100%;
        object-fit: cover;
      }
    }

    .head-info {
      flex: 1;
      min-width: 0;

      .name {
        font-size: 16px;
        font-weight: 600;
        color: #111827;
        line-height: 1.4;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .code {
        display: block;
        margin-top: 1px;
        font-size: 11px;
        color: #9ca3af;
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
    }

    .arrow {
      flex-shrink: 0;
      color: #d1d5db;
      transition: color 0.2s ease, transform 0.2s ease;
    }
  }

  &:hover .arrow {
    color: #ef4444;
    transform: translate(1px, -1px);
  }

  .description {
    margin-top: 12px;
    font-size: 13px;
    line-height: 1.7;
    color: #6b7280;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    overflow: hidden;
  }

  .capabilities {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 12px;

    .cap-tag {
      padding: 1px 8px;
      border-radius: 8px;
      background: #fef2f2;
      color: #b91c1c;
      font-size: 11px;
      line-height: 1.7;
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }

  .card-foot {
    display: flex;
    align-items: center;
    gap: 4px;
    margin-top: auto;
    padding-top: 14px;
    font-size: 12px;
    font-weight: 600;
    color: #ef4444;

    .entry-arrow {
      transition: transform 0.2s ease;
    }
  }

  &:hover .entry-arrow {
    transform: translateX(2px);
  }
}
</style>
