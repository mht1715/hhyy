<script setup>
import {nextTick, onMounted, ref, watch} from 'vue'
import {AlertCircle, Bot} from 'lucide-vue-next'
import MessageBubble from './MessageBubble.vue'

const props = defineProps({
  messages: {type: Array, default: () => []},
  emptyText: {type: String, default: '有什么可以帮你？'}
})

const emit = defineEmits(['cite', 'retry'])

const listRef = ref(null)

const scrollToBottom = () => {
  const el = listRef.value
  if (el) el.scrollTop = el.scrollHeight
}

watch(
    () => props.messages,
    () => nextTick(scrollToBottom),
    {deep: true}
)

onMounted(scrollToBottom)

const shouldRenderBubble = (message) => (
  !(message.role === 'assistant' && message.status === 'error' && !message.content)
)

const errorText = (message) => (
  (message.error && message.error.message) || '生成失败，请稍后重试'
)
</script>

<template>
  <div ref="listRef" class="message-list">
    <div v-if="messages.length === 0" class="empty-state">
      <div class="empty-avatar">
        <Bot :size="26" color="#fff"/>
      </div>
      <p class="empty-text">{{ emptyText }}</p>
      <p class="empty-hint">
        输入 <span class="at">@</span> 可以召唤其他 Agent 一起回答
      </p>
    </div>

    <template v-else>
      <div
          v-for="(message, index) in messages"
          :key="message.id"
          class="message-item"
      >
        <MessageBubble
            v-if="shouldRenderBubble(message)"
            :message="message"
            @cite="(citeIndex) => emit('cite', message, citeIndex)"
        />

        <div v-if="message.status === 'error'" class="error-bubble">
          <AlertCircle :size="16" class="error-icon"/>
          <div class="error-body">
            <p class="error-text">{{ errorText(message) }}</p>
            <button
                v-if="index === messages.length - 1"
                type="button"
                class="retry-btn"
                @click="emit('retry')"
            >
              重试
            </button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped lang="scss">
.message-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;

  .empty-state {
    flex: 1;
    min-height: 220px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;

    .empty-avatar {
      width: 52px;
      height: 52px;
      border-radius: 16px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: linear-gradient(135deg, #ef4444, #b91c1c);
      box-shadow: 0 8px 18px rgba(239, 68, 68, 0.22);
      margin-bottom: 2px;
    }

    .empty-text {
      max-width: 260px;
      text-align: center;
      font-size: 14px;
      line-height: 1.7;
      color: #4b5563;
    }

    .empty-hint {
      font-size: 12px;
      color: #9ca3af;

      .at {
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

  .message-item {
    display: flex;
    flex-direction: column;
  }

  .error-bubble {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    align-self: flex-start;
    max-width: 82%;
    margin-top: 8px;
    padding: 10px 12px;
    border-radius: 10px;
    background: #fef2f2;
    border: 1px solid #fecaca;
    color: #b91c1c;

    .error-icon {
      flex-shrink: 0;
      margin-top: 1px;
    }

    .error-body {
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 6px;
    }

    .error-text {
      font-size: 13px;
      line-height: 1.6;
      word-break: break-word;
    }

    .retry-btn {
      padding: 2px 12px;
      border-radius: 6px;
      border: 1px solid #fecaca;
      background: #fff;
      color: #b91c1c;
      font-size: 12px;
      line-height: 1.7;
      cursor: pointer;
      transition: background-color 0.15s ease;

      &:hover {
        background: #fee2e2;
      }
    }
  }

  @media (max-width: 768px) {
    padding: 12px;
    gap: 14px;

    .error-bubble {
      max-width: 92%;
    }
  }
}
</style>
