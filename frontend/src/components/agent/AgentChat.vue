<script setup>
import {computed, onMounted, reactive, ref} from 'vue'
import {Bot, RotateCcw} from 'lucide-vue-next'
import {fetchAgents} from '../../api/chat'
import {useAgentChat} from '../../composables/useAgentChat'
import CitationDrawer from './CitationDrawer.vue'
import MentionInput from './MentionInput.vue'
import MessageList from './MessageList.vue'
import RetrievalPanel from './RetrievalPanel.vue'
import TraceLink from './TraceLink.vue'

const props = defineProps({
  agentCode: {type: String, required: true},
  context: {type: Object, default: null},
  title: {type: String, default: ''},
  quickQuestions: {type: Array, default: () => []},
  compact: {type: Boolean, default: false}
})

const isDev = import.meta.env.DEV

const input = ref('')
const agents = ref([])
const devOpen = ref(false)

const {
  messages,
  streaming,
  route,
  send,
  stop,
  retry,
  reset,
  canSend
} = useAgentChat({
  agentCode: props.agentCode,
  context: props.context
})

const agentName = computed(() => {
  const match = agents.value.find((agent) => (agent.code || agent.agent_code) === props.agentCode)
  return match ? match.name : ''
})

const displayTitle = computed(() => props.title || agentName.value || props.agentCode || 'Agent 对话')

const emptyText = computed(() => `你好，我是 ${displayTitle.value}，有什么可以帮你？`)

const lastAssistant = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i -= 1) {
    if (messages.value[i].role === 'assistant') return messages.value[i]
  }
  return null
})

const routeText = computed(() => {
  const current = route.value
  if (!current || !Array.isArray(current.agents)) return ''
  const names = current.agents
      .map((agent) => agent.name || agent.code)
      .filter(Boolean)
  return names.length > 0 ? `路由：${names.join(' · ')}` : ''
})

const debugInfo = computed(() => {
  const message = lastAssistant.value
  if (!message) return null
  return {
    conversation_id: message.conversationId,
    message_id: message.messageId,
    route: route.value,
    tools: message.tools,
    usage: message.usage,
    guardrail: message.guardrail,
    handoff: message.handoff,
    replayed: message.replayed
  }
})

const citationState = reactive({
  show: false,
  citations: [],
  activeIndex: null
})

const openCitation = (message, index) => {
  citationState.citations = Array.isArray(message.citations) ? message.citations : []
  citationState.activeIndex = index
  citationState.show = true
}

const handleSubmit = ({text, mentions}) => {
  send(text, {mentions})
}

const askQuick = (question) => {
  if (!canSend.value) return
  send(question)
}

const handleReset = () => {
  reset()
  input.value = ''
  devOpen.value = false
}

onMounted(async () => {
  try {
    agents.value = await fetchAgents()
  } catch (e) {
    // 候选列表拉不到只是 @ 能力降级，不影响正常对话
  }
})
</script>

<template>
  <div class="agent-chat" :class="{ compact }">
    <div class="chat-header">
      <div class="header-main">
        <div class="header-avatar">
          <Bot :size="17" color="#fff"/>
        </div>
        <div class="header-text">
          <h3>{{ displayTitle }}</h3>
          <p v-if="isDev && routeText" class="route-line">{{ routeText }}</p>
          <p v-else class="route-line">基于知识库与多 Agent 协作回答</p>
        </div>
      </div>

      <div class="header-actions">
        <span v-if="streaming" class="streaming-flag">
          <span class="pulse"></span>
          生成中
        </span>
        <button type="button" class="icon-btn" title="新会话" @click="handleReset">
          <RotateCcw :size="15"/>
        </button>
      </div>
    </div>

    <MessageList
        :messages="messages"
        :empty-text="emptyText"
        @cite="openCitation"
        @retry="retry"
    />

    <div v-if="isDev && lastAssistant" class="dev-area">
      <div class="dev-bar">
        <span class="dev-tag">DEV</span>
        <span class="dev-meta">{{ (lastAssistant.retrieval || []).length }} 检索</span>
        <span class="dev-meta">{{ (lastAssistant.tools || []).length }} 工具</span>
        <TraceLink :trace-id="lastAssistant.traceId || ''"/>
        <button type="button" class="dev-toggle" @click="devOpen = !devOpen">
          {{ devOpen ? '收起' : '调试信息' }}
        </button>
      </div>
      <div v-if="devOpen" class="dev-body">
        <RetrievalPanel :retrievals="lastAssistant.retrieval || []"/>
        <pre v-if="debugInfo" class="dev-json">{{ JSON.stringify(debugInfo, null, 2) }}</pre>
      </div>
    </div>

    <div v-if="quickQuestions.length > 0 && messages.length === 0" class="quick-questions">
      <button
          v-for="question in quickQuestions"
          :key="question"
          type="button"
          class="quick-chip"
          :disabled="streaming"
          @click="askQuick(question)"
      >
        {{ question }}
      </button>
    </div>

    <div class="composer">
      <MentionInput
          v-model="input"
          :agents="agents"
          :disabled="streaming"
          :streaming="streaming"
          placeholder="输入问题，@ 可召唤其他 Agent…"
          @submit="handleSubmit"
          @stop="stop"
      />
    </div>

    <CitationDrawer
        v-model="citationState.show"
        :citations="citationState.citations"
        :active-index="citationState.activeIndex"
    />
  </div>
</template>

<style scoped lang="scss">
.agent-chat {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 12px;
  border: 1px solid #f3f4f6;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  overflow: hidden;

  &.compact {
    flex: none;
    max-height: 560px;
    height: 520px;
  }

  .chat-header {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 12px 16px;
    border-bottom: 1px solid #f3f4f6;
    background: #fff;

    .header-main {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }

    .header-avatar {
      width: 34px;
      height: 34px;
      flex-shrink: 0;
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: linear-gradient(135deg, #ef4444, #b91c1c);
    }

    .header-text {
      min-width: 0;

      h3 {
        font-size: 15px;
        font-weight: 600;
        color: #111827;
        line-height: 1.4;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .route-line {
        margin-top: 1px;
        font-size: 11px;
        color: #9ca3af;
        line-height: 1.5;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;

      .streaming-flag {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 1px 8px;
        border-radius: 8px;
        background: #fef2f2;
        color: #ef4444;
        font-size: 11px;
        line-height: 18px;

        .pulse {
          width: 5px;
          height: 5px;
          border-radius: 50%;
          background: #ef4444;
          animation: chat-pulse 1s ease-in-out infinite;
        }
      }

      .icon-btn {
        width: 30px;
        height: 30px;
        display: flex;
        align-items: center;
        justify-content: center;
        border: none;
        border-radius: 50%;
        background: #f9fafb;
        color: #6b7280;
        cursor: pointer;
        transition: background-color 0.15s ease, color 0.15s ease;

        &:hover {
          background: #fef2f2;
          color: #ef4444;
        }
      }
    }
  }

  .dev-area {
    flex-shrink: 0;
    padding: 0 16px 8px;

    .dev-bar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      padding: 8px 10px;
      border-radius: 10px;
      background: #f9fafb;
      border: 1px dashed #e5e7eb;

      .dev-tag {
        padding: 0 6px;
        border-radius: 6px;
        background: #111827;
        color: #fff;
        font-size: 10px;
        font-weight: 700;
        line-height: 16px;
        letter-spacing: 0.5px;
      }

      .dev-meta {
        font-size: 11px;
        color: #6b7280;
      }

      .dev-toggle {
        margin-left: auto;
        padding: 0;
        border: none;
        background: transparent;
        color: #ef4444;
        font-size: 11px;
        cursor: pointer;
      }
    }

    .dev-body {
      display: flex;
      flex-direction: column;
      gap: 8px;
      max-height: 220px;
      overflow-y: auto;
      padding-top: 8px;
    }

    .dev-json {
      margin: 0;
      padding: 10px 12px;
      border-radius: 8px;
      background: #0f172a;
      color: #e2e8f0;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 11px;
      line-height: 1.6;
      white-space: pre-wrap;
      word-break: break-word;
    }
  }

  .quick-questions {
    flex-shrink: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    padding: 10px 16px 0;

    .quick-chip {
      padding: 5px 12px;
      border-radius: 999px;
      border: 1px solid #fecaca;
      background: #fff7f7;
      color: #b91c1c;
      font-size: 12px;
      line-height: 1.4;
      cursor: pointer;
      transition: background-color 0.15s ease;

      &:hover {
        background: #fee2e2;
      }

      &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }
    }
  }

  .composer {
    flex-shrink: 0;
    padding: 10px 16px 12px;
    border-top: 1px solid #f3f4f6;
    background: #fff;
  }

  @media (max-width: 768px) {
    border-radius: 10px;

    .chat-header {
      padding: 10px 12px;
    }

    .dev-area {
      padding: 0 12px 6px;
    }

    .quick-questions,
    .composer {
      padding-left: 12px;
      padding-right: 12px;
    }

    &.compact {
      height: 460px;
    }
  }
}

@keyframes chat-pulse {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }

  50% {
    opacity: 0.4;
    transform: scale(0.8);
  }
}
</style>
