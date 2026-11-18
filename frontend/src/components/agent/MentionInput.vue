<script setup>
import {computed, nextTick, onMounted, ref, watch} from 'vue'
import {AtSign, Send, Square} from 'lucide-vue-next'
import {collectMentions, detectMention, filterCandidates, insertMention} from '../../composables/useMention'

const props = defineProps({
  modelValue: {type: String, default: ''},
  agents: {type: Array, default: () => []},
  placeholder: {type: String, default: '输入消息，@ 可召唤其他 Agent…'},
  disabled: {type: Boolean, default: false},
  // 与 disabled 分开：流式中仍需要露出「停止」按钮
  streaming: {type: Boolean, default: false}
})

const emit = defineEmits(['update:modelValue', 'submit', 'stop'])

const textareaRef = ref(null)
const panelRef = ref(null)
const innerValue = ref(props.modelValue || '')
const mentions = ref([])
const mentioning = ref({active: false, keyword: '', start: -1})
const activeIndex = ref(0)
const composing = ref(false)

const candidates = computed(() => {
  if (!mentioning.value.active) return []
  return filterCandidates(props.agents, mentioning.value.keyword).slice(0, 8)
})

const panelOpen = computed(() => (
  mentioning.value.active
  && candidates.value.length > 0
  && !composing.value
  && !props.disabled
))

watch(() => props.modelValue, (value) => {
  const next = value || ''
  if (next === innerValue.value) return
  innerValue.value = next
  mentions.value = collectMentions(next, mentions.value)
  nextTick(autoResize)
  if (!next) closePanel()
})

watch(candidates, () => {
  if (activeIndex.value >= candidates.value.length) activeIndex.value = 0
}, {flush: 'sync'})

watch(activeIndex, async () => {
  await nextTick()
  const active = panelRef.value && panelRef.value.querySelector('.mention-item.active')
  if (active) active.scrollIntoView({block: 'nearest'})
})

const firstChar = (name) => {
  const text = String(name || 'A').trim()
  return text ? text.charAt(0) : 'A'
}

const agentCode = (agent) => agent.code || agent.agent_code || ''

const closePanel = () => {
  mentioning.value = {active: false, keyword: '', start: -1}
  activeIndex.value = 0
}

const autoResize = () => {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight || 24, 120)}px`
}

const refreshMention = () => {
  const el = textareaRef.value
  if (!el || composing.value || props.disabled) {
    closePanel()
    return
  }

  const caret = typeof el.selectionStart === 'number' ? el.selectionStart : innerValue.value.length
  const result = detectMention(innerValue.value, caret)
  if (!result.active) {
    closePanel()
    return
  }

  mentioning.value = result
  if (activeIndex.value >= candidates.value.length) activeIndex.value = 0
}

const handleInput = (event) => {
  const value = event.target.value
  innerValue.value = value
  mentions.value = collectMentions(value, mentions.value)
  emit('update:modelValue', value)
  autoResize()

  // 输入法组合期间只更新文本，不弹面板、不确认
  if (composing.value) {
    closePanel()
    return
  }
  nextTick(refreshMention)
}

const handleCompositionStart = () => {
  composing.value = true
  closePanel()
}

const handleCompositionEnd = () => {
  composing.value = false
  nextTick(refreshMention)
}

const chooseCandidate = (agent) => {
  if (!agent || props.disabled) return
  const el = textareaRef.value
  const caret = el && typeof el.selectionStart === 'number'
    ? el.selectionStart
    : innerValue.value.length

  const result = insertMention(innerValue.value, caret, agent)
  innerValue.value = result.text
  emit('update:modelValue', result.text)

  const duplicated = mentions.value.some((mention) => (
    mention.agent_code === result.mention.agent_code && mention.offset === result.mention.offset
  ))
  if (!duplicated) mentions.value.push(result.mention)

  closePanel()
  nextTick(() => {
    if (!el) return
    el.focus()
    el.setSelectionRange(result.caret, result.caret)
    autoResize()
  })
}

const submit = () => {
  if (props.disabled || props.streaming || composing.value) return
  const text = innerValue.value
  if (!text.trim()) return

  const validMentions = collectMentions(text, mentions.value)
  mentions.value = validMentions
  emit('submit', {text, mentions: validMentions.slice()})

  innerValue.value = ''
  emit('update:modelValue', '')
  closePanel()
  nextTick(autoResize)
}

const handleKeydown = (event) => {
  // compositionstart ~ compositionend 之间一律不处理，交给输入法
  if (composing.value || event.isComposing || event.keyCode === 229) return

  if (event.key === 'Escape') {
    if (panelOpen.value) {
      event.preventDefault()
      closePanel()
    }
    return
  }

  if (panelOpen.value) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      activeIndex.value = (activeIndex.value + 1) % candidates.value.length
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      activeIndex.value = (activeIndex.value - 1 + candidates.value.length) % candidates.value.length
      return
    }
    if (event.key === 'Tab' || (event.key === 'Enter' && !event.shiftKey)) {
      event.preventDefault()
      chooseCandidate(candidates.value[activeIndex.value])
      return
    }
  }

  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    submit()
  }
}

onMounted(() => {
  nextTick(autoResize)
})
</script>

<template>
  <div class="mention-input">
    <transition name="mention-fade">
      <div v-if="panelOpen" ref="panelRef" class="mention-panel">
        <div class="panel-head">
          <AtSign :size="12"/>
          <span>选择 Agent</span>
          <span v-if="mentioning.keyword" class="panel-keyword">“{{ mentioning.keyword }}”</span>
        </div>

        <button
            v-for="(agent, index) in candidates"
            :key="agentCode(agent) || index"
            type="button"
            class="mention-item"
            :class="{ active: index === activeIndex }"
            @mousedown.prevent="chooseCandidate(agent)"
        >
          <span class="mention-avatar">
            <img v-if="agent.avatar" :src="agent.avatar" :alt="agent.name || agentCode(agent)"/>
            <template v-else>{{ firstChar(agent.name || agentCode(agent)) }}</template>
          </span>
          <span class="mention-info">
            <span class="mention-name">{{ agent.name || agentCode(agent) }}</span>
            <span class="mention-desc">{{ agent.description || agentCode(agent) }}</span>
          </span>
          <span class="mention-key">@</span>
        </button>
      </div>
    </transition>

    <div class="input-row">
      <textarea
          ref="textareaRef"
          class="mention-textarea"
          :value="innerValue"
          :placeholder="placeholder"
          :disabled="disabled"
          rows="1"
          @input="handleInput"
          @keydown="handleKeydown"
          @click="refreshMention"
          @focus="refreshMention"
          @compositionstart="handleCompositionStart"
          @compositionend="handleCompositionEnd"
      ></textarea>

      <van-button
          v-if="streaming"
          class="action-btn stop-btn"
          @click="emit('stop')"
      >
        <template #icon>
          <Square :size="12" fill="currentColor"/>
        </template>
        停止
      </van-button>
      <van-button
          v-else
          type="danger"
          class="action-btn send-btn"
          :disabled="disabled"
          @click="submit"
      >
        <template #icon>
          <Send :size="16"/>
        </template>
        发送
      </van-button>
    </div>

    <p class="input-hint">
      输入 <span class="kbd">@</span> 可召唤其他 Agent，Enter 发送，Shift + Enter 换行
    </p>
  </div>
</template>

<style scoped lang="scss">
.mention-input {
  position: relative;
  width: 100%;
  min-width: 0;

  .mention-panel {
    position: absolute;
    left: 0;
    right: 0;
    bottom: calc(100% + 8px);
    z-index: 40;
    max-height: 280px;
    overflow-y: auto;
    background: #fff;
    border: 1px solid #f3f4f6;
    border-radius: 12px;
    box-shadow: 0 12px 30px rgba(17, 24, 39, 0.14);
    padding: 6px;

    .panel-head {
      display: flex;
      align-items: center;
      gap: 4px;
      font-size: 11px;
      color: #9ca3af;
      padding: 4px 8px 6px;

      .panel-keyword {
        color: #ef4444;
        font-weight: 600;
        max-width: 140px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
    }

    .mention-item {
      width: 100%;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 8px;
      border: none;
      border-radius: 10px;
      background: transparent;
      text-align: left;
      cursor: pointer;
      transition: background-color 0.15s ease;

      &.active,
      &:hover {
        background: #fef2f2;
      }

      .mention-avatar {
        width: 30px;
        height: 30px;
        flex-shrink: 0;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        overflow: hidden;
        background: linear-gradient(135deg, #ef4444, #b91c1c);
        color: #fff;
        font-size: 13px;
        font-weight: 600;

        img {
          width: 100%;
          height: 100%;
          object-fit: cover;
        }
      }

      .mention-info {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 1px;

        .mention-name {
          font-size: 13px;
          font-weight: 600;
          color: #111827;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .mention-desc {
          font-size: 11px;
          color: #9ca3af;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
      }

      .mention-key {
        color: #fca5a5;
        font-size: 13px;
        font-weight: 700;
        flex-shrink: 0;
      }
    }
  }

  .input-row {
    display: flex;
    align-items: flex-end;
    gap: 8px;
  }

  .mention-textarea {
    flex: 1;
    min-width: 0;
    min-height: 24px;
    max-height: 120px;
    padding: 5px 0;
    border: none;
    outline: none;
    resize: none;
    background: transparent;
    color: #374151;
    font-family: inherit;
    font-size: 14px;
    line-height: 1.6;
    overflow-y: auto;

    &::placeholder {
      color: #9ca3af;
    }

    &:disabled {
      color: #9ca3af;
      cursor: not-allowed;
    }
  }

  .action-btn {
    flex-shrink: 0;
    height: 32px;
    padding: 0 16px;
    border-radius: 6px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
    font-size: 14px;
  }

  .stop-btn {
    background: #fef2f2;
    border: 1px solid #fecaca;
    color: #b91c1c;

    &:active {
      background: #fee2e2;
    }
  }

  .input-hint {
    margin-top: 4px;
    font-size: 11px;
    line-height: 1.5;
    color: #9ca3af;

    .kbd {
      display: inline-block;
      min-width: 14px;
      padding: 0 4px;
      border-radius: 4px;
      background: #fef2f2;
      border: 1px solid #fecaca;
      color: #b91c1c;
      font-weight: 600;
      text-align: center;
    }
  }
}

.mention-fade-enter-active,
.mention-fade-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.mention-fade-enter-from,
.mention-fade-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

@media (max-width: 480px) {
  .mention-input {
    .action-btn {
      padding: 0 12px;
      font-size: 13px;
    }

    .input-hint {
      font-size: 10px;
    }
  }
}
</style>
