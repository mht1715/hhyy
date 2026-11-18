<script setup>
import {computed, nextTick, onMounted, ref, watch} from 'vue'
import {Sparkles} from 'lucide-vue-next'
import {fetchAgents} from '../../api/chat'
import {useAgentChat} from '../../composables/useAgentChat'
import CitationDrawer from '../agent/CitationDrawer.vue'
import MentionInput from '../agent/MentionInput.vue'
import MessageBubble from '../agent/MessageBubble.vue'

const props = defineProps({
  productId: {type: String, required: true},
  productName: {type: String, default: '该药品'}
})

const quickQuestions = [
  '这个药怎么吃？',
  '孕妇可以用吗？',
  '有什么副作用？',
  '和其他药能一起吃吗？'
]

const greeting = `您好，我是您的专属AI药师。关于【${props.productName}】的用法、禁忌或适用人群，您可以随时问我。`

const {
  messages,
  streaming,
  send,
  stop,
  retry
} = useAgentChat({
  agentCode: 'drug_consult',
  context: {product_id: props.productId},
  initialMessages: [{role: 'assistant', content: greeting}]
})

const input = ref('')
const agents = ref([])
const chatAreaRef = ref(null)

const citationShow = ref(false)
const citationList = ref([])
const citationIndex = ref(null)

const lastAssistant = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i -= 1) {
    if (messages.value[i].role === 'assistant') return messages.value[i]
  }
  return null
})

// 流式占位（或空错误气泡）不单独渲染，改用原有的 loading / 错误条
const visibleMessages = computed(() => {
  const list = messages.value
  const last = list[list.length - 1]
  const isPlaceholder = last
    && last.role === 'assistant'
    && !last.content
    && (last.status === 'streaming' || last.status === 'error')
  return isPlaceholder ? list.slice(0, -1) : list
})

const showLoadingBubble = computed(() => (
  streaming.value
  && lastAssistant.value
  && lastAssistant.value.status === 'streaming'
  && !lastAssistant.value.content
))

const errorText = computed(() => {
  const last = lastAssistant.value
  if (!last || last.status !== 'error') return ''
  return (last.error && last.error.message) || '抱歉，药师现在有点忙，请稍后再试。'
})

watch(
    [messages, streaming],
    () => {
      nextTick(() => {
        if (chatAreaRef.value) {
          chatAreaRef.value.scrollTop = chatAreaRef.value.scrollHeight
        }
      })
    },
    {deep: true}
)

onMounted(async () => {
  try {
    agents.value = await fetchAgents()
  } catch (e) {
    // 候选列表不影响药品咨询本身
  }
})

const handleSubmit = ({text, mentions}) => {
  if (streaming.value) return
  send(text, {mentions})
}

const askQuick = (question) => {
  if (streaming.value) return
  send(question)
}

const openCitation = (message, index) => {
  citationList.value = Array.isArray(message.citations) ? message.citations : []
  citationIndex.value = index
  citationShow.value = true
}
</script>

<template>
  <div class="ai-assistant-card">
    <div class="ai-header">
      <Sparkles :size="18" color="#ef4444"/>
      <span>AI 药师在线咨询</span>
    </div>

    <!-- 聊天记录区 -->
    <div class="chat-area" ref="chatAreaRef">
      <div
          v-for="msg in visibleMessages"
          :key="msg.id"
          :class="['msg-wrap', msg.role === 'user' ? 'user' : 'ai']"
      >
        <div class="avatar" v-if="msg.role !== 'user'">
          <Sparkles :size="14" color="#fff"/>
        </div>
        <div class="msg-bubble">
          <MessageBubble
              :message="msg"
              @cite="(index) => openCitation(msg, index)"
          />
        </div>
      </div>

      <div v-if="showLoadingBubble" class="msg-wrap ai">
        <div class="avatar">
          <Sparkles :size="14" color="#fff"/>
        </div>
        <div class="msg-bubble loading-bubble">
          <van-loading type="dots" size="20px" color="#ef4444"/>
          <span>正在查阅说明书...</span>
        </div>
      </div>

      <div v-if="errorText" class="msg-wrap ai">
        <div class="avatar">
          <Sparkles :size="14" color="#fff"/>
        </div>
        <div class="msg-bubble error-bubble">
          <span>{{ errorText }}</span>
          <button type="button" class="retry-btn" @click="retry">重试</button>
        </div>
      </div>
    </div>

    <!-- 快捷提问区 -->
    <div class="quick-questions">
      <van-tag
          v-for="(q, index) in quickQuestions"
          :key="index"
          plain
          type="danger"
          size="medium"
          :class="['q-tag', { disabled: streaming }]"
          @click="askQuick(q)"
      >
        {{ q }}
      </van-tag>
    </div>

    <!-- 输入区 -->
    <div class="input-area">
      <MentionInput
          v-model="input"
          :agents="agents"
          :disabled="streaming"
          :streaming="streaming"
          placeholder="输入您想咨询的问题..."
          class="chat-input-wrap"
          @submit="handleSubmit"
          @stop="stop"
      />
    </div>

    <CitationDrawer
        v-model="citationShow"
        :citations="citationList"
        :active-index="citationIndex"
    />
  </div>
</template>

<style scoped lang="scss">
.ai-assistant-card {
  background: #fff;
  margin: 12px 0;
  padding: 16px;
  border-top: 1px solid #f3f4f6;
  border-bottom: 1px solid #f3f4f6;

  .ai-header {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 600;
    color: #b91c1c;
    margin-bottom: 16px;
  }

  .chat-area {
    max-height: 300px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 16px;
    margin-bottom: 16px;
    padding-right: 4px;

    .msg-wrap {
      display: flex;
      align-items: flex-start;
      gap: 8px;
      max-width: 90%;

      &.user {
        align-self: flex-end;
        flex-direction: row-reverse;

        .msg-bubble {
          background: #ef4444;
          color: white;
          border-radius: 12px 0 12px 12px;
        }
      }

      &.ai {
        align-self: flex-start;

        .msg-bubble {
          background: #f9fafb;
          color: #374151;
          border-radius: 0 12px 12px 12px;
        }
      }

      .avatar {
        width: 24px;
        height: 24px;
        background: #ef4444;
        border-radius: 50%;
        display: flex;
        justify-content: center;
        align-items: center;
        flex-shrink: 0;
        margin-top: 4px;
      }

      .msg-bubble {
        padding: 10px 14px;
        font-size: 14px;
        line-height: 1.6;
        word-break: break-all;
        min-width: 0;
      }

      /* MessageBubble 自带气泡壳，这里只保留父级原有的气泡外观 */
      .msg-bubble :deep(.message-bubble) {
        max-width: 100%;
        align-self: stretch;

        .bubble {
          padding: 0;
          background: transparent;
          border-radius: 0;
          color: inherit;
        }
      }
    }

    .loading-bubble {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      color: #9ca3af;
    }

    .msg-wrap.ai .msg-bubble.error-bubble {
      display: flex;
      align-items: center;
      gap: 8px;
      background: #fef2f2;
      border: 1px solid #fecaca;
      color: #b91c1c;
      font-size: 13px;

      .retry-btn {
        flex-shrink: 0;
        padding: 2px 10px;
        border-radius: 6px;
        border: 1px solid #fecaca;
        background: #fff;
        color: #b91c1c;
        font-size: 12px;
        line-height: 1.7;
        cursor: pointer;

        &:hover {
          background: #fee2e2;
        }
      }
    }
  }

  /* 深度定制 Markdown 渲染后的样式 */
  :deep(.markdown-body) {
    p {
      margin-bottom: 8px;

      &:last-child {
        margin-bottom: 0;
      }
    }

    strong {
      font-weight: bold;
      color: #b91c1c;
    }

    ul, ol {
      padding-left: 20px;
      margin-bottom: 8px;
    }

    li {
      margin-bottom: 4px;
    }

    br {
      display: block;
      content: "";
      margin-top: 4px;
    }
  }

  .quick-questions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 12px;

    .q-tag {
      cursor: pointer;
      transition: all 0.2s;
      padding: 6px 12px;
      border-radius: 16px;
      background: #fef2f2;

      &:hover {
        background: #fee2e2;
        transform: translateY(-1px);
      }

      &.disabled {
        opacity: 0.5;
        pointer-events: none;
      }
    }
  }

  .input-area {
    display: flex;
    gap: 8px;
    align-items: center;
    background: #f9fafb;
    padding: 6px 12px;
    border-radius: 8px;
    border: 1px solid #e5e7eb;

    .chat-input-wrap {
      flex: 1;
      min-width: 0;
    }

    :deep(.input-hint) {
      display: none;
    }

    :deep(.mention-textarea) {
      padding: 4px 0;
      font-size: 14px;
      line-height: 1.6;
      max-height: 88px;
    }

    :deep(.action-btn) {
      height: 32px;
      padding: 0 16px;
      border-radius: 6px;
    }
  }
}
</style>
