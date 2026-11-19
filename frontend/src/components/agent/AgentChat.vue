<script setup>
import {computed, onMounted, reactive, ref, watch} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import {Bot, RotateCcw, Sparkles} from 'lucide-vue-next'
import {showToast} from 'vant'
import {fetchAgents} from '../../api/chat'
import {createWsTicket, fetchConversation, requestHandoff} from '../../api/support'
import {quickStarters, sectionsForAgent} from '../../data/quickPrompts'
import {useAgentChat} from '../../composables/useAgentChat'
import {useSupportSocket} from '../../composables/useSupportSocket'
import {useAuthStore} from '../../store/auth'
import CitationDrawer from './CitationDrawer.vue'
import HandoffBar from './HandoffBar.vue'
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
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const input = ref('')
// M5：支持从工作台「快捷提问」带问题进来（?q=）。只预填、不自动发送——
// 自动发送会让用户来不及看清当前是哪个 Agent，也容易一进页面就撞限流。
if (route.query.q) input.value = String(route.query.q)
const agents = ref([])
const devOpen = ref(false)

const {
  messages,
  streaming,
  route: routeState,
  hydrate,
  send,
  stop,
  retry,
  reset,
  canSend,
  conversationId,
  status,
  ticket,
  memoryState,
  applySupportState
} = useAgentChat({
  agentCode: props.agentCode,
  context: props.context
})

/* ------------------------------------------------------------------ *
 * M3 转人工 / 人工通道
 * ------------------------------------------------------------------ */

const humanActive = computed(() => status.value === 'human_active')
const conversationClosed = computed(() => status.value === 'closed')
// 有活跃工单就要挂实时通道：排队阶段也得能收到「客服已接入」。
// 只在 human_active 时连会形成死锁——前端永远等不到那个状态。
const needSocket = computed(() => (
  !!conversationId.value && ['handoff_pending', 'human_active'].includes(status.value)
))
// 未登录时不能建单，按钮改成登录引导
const canHandoff = computed(() => !!auth.token)

/* ------------------------------------------------------------------ *
 * 演示提问（面试官不用自己想问题）
 * ------------------------------------------------------------------ */

const panelOpen = ref(false)

// 传了 quickQuestions 就以调用方为准，否则按 agent code 用内置演示脚本
const quickSections = computed(() => {
  if (props.quickQuestions.length > 0) {
    return [{title: '快捷提问', note: '', items: props.quickQuestions.map((text) => ({text}))}]
  }
  return sectionsForAgent(props.agentCode)
})

// 空态直接铺三条：让页面一进来就有「点一下就能跑」的入口
const starterPrompts = computed(() => (
  props.quickQuestions.length > 0
    ? props.quickQuestions.map((text) => ({text}))
    : quickStarters(props.agentCode)
))

// 人工接管后消息是发给客服的，AI 的演示提问就该收起来
const showPrompts = computed(() => !humanActive.value && !conversationClosed.value)

watch(showPrompts, (value) => {
  if (!value) panelOpen.value = false
})

const socket = useSupportSocket({
  conversationId: () => conversationId.value,
  // 每次（重）连都换一张新的短期票据：JWT 不进 query string
  wsTicket: async () => {
    const data = await createWsTicket()
    return (data && data.ws_ticket) || ''
  }
})

// 解构出来的 ref 在模板里会自动解包，模板里就不用写 .value
const {agentName: supportAgentName, error: socketError} = socket

const SOCKET_ROLES = new Set(['user', 'human_agent'])

const appendSocketMessage = (raw) => {
  if (!raw) return
  const id = raw.id || raw.message_id
  if (!id) return
  const clientId = raw.client_message_id || ''

  // 自己发的消息会经广播回显：用 client_message_id 认领本地乐观气泡，避免显示两遍
  if (clientId) {
    const local = messages.value.find((message) => message.clientMessageId === clientId)
    if (local) {
      if (local.id !== id) local.id = id
      local.messageId = id
      local.status = 'done'
      if (raw.content) local.content = raw.content
      return
    }
  }
  if (messages.value.some((message) => message.id === id)) return

  const role = SOCKET_ROLES.has(raw.role) ? raw.role : 'assistant'
  messages.value.push({
    id,
    role,
    content: raw.content || '',
    actor_name: raw.actor_name || '',
    status: 'done',
    clientMessageId: clientId,
    createdAt: raw.created_at || null,
    mentions: [],
    agentsRunning: [],
    contributors: [],
    retrieval: [],
    tools: [],
    citations: [],
    handoff: null,
    memory: null,
    silenced: false,
    stopped: false,
    error: null,
    conversationId: conversationId.value,
    messageId: id,
    traceId: null,
    latencyMs: null
  })
}

// 排队中就连上：否则「客服已接管」的状态帧永远收不到
watch(needSocket, (need) => {
  if (need) socket.connect()
  else socket.close()
}, {immediate: true})

// WS 帧回写：坐席发来的消息、会话状态变化、工单变化
// 同一个 tick 可能到多帧，所以整表合并（appendSocketMessage 内部按 id 去重）
watch(() => socket.messages.value.length, () => {
  socket.messages.value.forEach(appendSocketMessage)
})

watch(() => socket.status.value, (value) => {
  if (!value) return
  // 只有「和我们当前认知不同」才算状态变化：重复帧不该反复弹 toast
  const changed = value !== status.value
  if (!changed) return
  applySupportState({status: value})
  if (value === 'human_active') showToast('客服已接入，接下来由人工为你服务')
  if (value === 'closed') showToast('本次客服会话已结束')
})

watch(() => socket.ticket.value, (value) => {
  if (value) applySupportState({ticket: value})
})

// 坐席结束会话后会话回到 bot_active：AI 重新接管，输入框恢复可用
let wasHumanActive = false
watch(status, (value) => {
  if (value === 'human_active') {
    wasHumanActive = true
    return
  }
  if (value === 'bot_active' && wasHumanActive) {
    wasHumanActive = false
    showToast('客服已结束，AI 已接回对话')
  }
})

watch(() => socketError.value, (value) => {
  if (value) showToast({type: 'fail', message: value})
})

/* ------------------------------------------------------------------ *
 * 会话恢复（刷新 / 从「我的会话」跳回来）
 * ------------------------------------------------------------------ */

const syncUrl = (cid) => {
  const current = route.query.c ? String(route.query.c) : ''
  const next = cid ? String(cid) : ''
  if (current === next) return
  const query = {...route.query}
  if (next) query.c = next
  else delete query.c
  router.replace({query}).catch(() => {})
}

watch(conversationId, (value) => syncUrl(value))

// 地址栏的 c 变了（例如从「我的会话」点了另一条）：接回那段对话。
// 自己写 URL 时 c 和当前会话一致，会在这里被挡掉，不会自激重载。
watch(() => route.query.c, (value) => {
  const cid = value ? String(value) : ''
  if (!cid || cid === conversationId.value) return
  restoreConversation(cid)
})

const restoreConversation = async (cid) => {
  try {
    const data = await fetchConversation(cid)
    if (!data) return false
    hydrate(data)
    return true
  } catch (e) {
    // 会话不存在 / 不是自己的：清掉地址栏参数，从空白会话重新开始
    syncUrl('')
    if (e && (e.status === 404 || e.status === 403)) showToast('会话不存在或无权访问')
    return false
  }
}

const lastAssistantSilenced = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i -= 1) {
    if (messages.value[i].role === 'assistant') return !!messages.value[i].silenced
  }
  return false
})

const showStreamingFlag = computed(() => streaming.value && !humanActive.value && !lastAssistantSilenced.value)

// 「已参考 N 条记忆」徽标：以 done.memory_used 为准（meta.memory.count 只是记忆总数）；
// memory.enabled=false（用户关过记忆）时一律不展示
const memoryBadge = computed(() => {
  const state = memoryState.value
  if (state && typeof state === 'object' && state.enabled === false) return 0
  const message = lastAssistant.value
  if (!message) return 0
  const used = Number(message.memoryUsed)
  return Number.isFinite(used) && used > 0 ? used : 0
})

const handleHandoff = async () => {
  if (!conversationId.value) {
    showToast('请先和 AI 说一句话，再转人工')
    return
  }
  try {
    const data = await requestHandoff(conversationId.value, '用户点击转人工')
    // 契约 §5.1：返回 ticket_id / queue_position / queue_expires_in。
    // 幂等命中「已被接管」的旧工单时服务端会给 assigned，别把状态写回排队
    const nextStatus = data && data.status === 'assigned' ? 'human_active' : 'handoff_pending'
    applySupportState({status: nextStatus, ticket: data || null})
    const position = Number(data && data.queue_position)
    showToast(position > 0 ? `已为你排队，当前第 ${position} 位` : '已提交转人工申请')
  } catch (e) {
    showToast({type: 'fail', message: (e && e.message) || '转人工失败，请稍后重试'})
  }
}

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
  const current = routeState.value
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
    route: routeState.value,
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

const pushLocalUserMessage = (text, clientMessageId) => {
  messages.value.push({
    id: clientMessageId,
    role: 'user',
    content: text,
    clientMessageId,
    status: 'done',
    createdAt: new Date().toISOString(),
    mentions: [],
    agentsRunning: [],
    contributors: [],
    retrieval: [],
    tools: [],
    citations: [],
    handoff: null,
    memory: null,
    silenced: false,
    stopped: false,
    error: null,
    conversationId: conversationId.value,
    messageId: null,
    traceId: null,
    latencyMs: null
  })
}

const composerPlaceholder = computed(() => {
  if (conversationClosed.value) return '会话已结束，点右上角「新会话」重新开始'
  if (humanActive.value) return '给客服发消息…'
  return '输入问题，@ 可召唤其他 Agent…'
})

const composerHint = computed(() => {
  if (conversationClosed.value) return '本次会话已结束'
  if (humanActive.value) return '人工客服受理中，Enter 发送，Shift + Enter 换行'
  return ''
})

const handleSubmit = ({text, mentions}) => {
  if (conversationClosed.value) {
    showToast('本次会话已结束，点右上角「新会话」重新开始')
    return
  }
  if (humanActive.value) {
    // 人工接管后消息走 WS：服务端落库并广播给坐席。
    // client_message_id 由服务端原样回带，用来认领这条本地气泡。
    const clientMessageId = `ws-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
    if (socket.send(text, {clientMessageId})) {
      pushLocalUserMessage(text, clientMessageId)
      return
    }
    // 客服通道没连上：退回普通通道（契约 §2.5，后端仍会落库并推给坐席）
    showToast('客服通道连接中，消息已通过会话发送')
    send(text, {mentions: []})
    return
  }
  send(text, {mentions})
}

const askQuick = (item) => {
  if (!canSend.value) return
  const prompt = typeof item === 'string' ? {text: item} : (item || {})
  const text = String(prompt.text || '')
  if (!text.trim()) return
  panelOpen.value = false
  // 数据里带的 mentions 合并进本次请求：文本里的 @ 只是给人看的，
  // 后端是按结构化 mentions 路由的
  send(text, {mentions: Array.isArray(prompt.mentions) ? prompt.mentions : []})
}

const handleReset = () => {
  socket.close()
  reset()
  input.value = ''
  devOpen.value = false
}

const handleRestart = () => {
  handleReset()
  showToast('已开始新会话')
}

onMounted(async () => {
  try {
    agents.value = await fetchAgents()
  } catch (e) {
    // 候选列表拉不到只是 @ 能力降级，不影响正常对话
  }
  // ?c=<conversation_id>：刷新页面 / 从「我的会话」点回来时把整段对话接回去
  const cid = route.query.c ? String(route.query.c) : ''
  if (cid) await restoreConversation(cid)
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
          <p v-if="humanActive" class="route-line is-human">人工客服已接入，AI 已静默</p>
          <p v-else-if="isDev && routeText" class="route-line">{{ routeText }}</p>
          <p v-else class="route-line">基于知识库与多 Agent 协作回答</p>
        </div>
      </div>

      <div class="header-actions">
        <span v-if="showStreamingFlag" class="streaming-flag">
          <span class="pulse"></span>
          生成中
        </span>
        <span
            v-if="memoryBadge > 0"
            class="memory-flag"
            :title="`本轮参考了 ${memoryBadge} 条记忆`"
        >
          记忆 {{ memoryBadge }}
        </span>
        <button
            v-if="showPrompts"
            type="button"
            class="icon-btn"
            :class="{ 'is-on': panelOpen }"
            title="演示提问：点开挑一个，不用自己想问题"
            @click="panelOpen = !panelOpen"
        >
          <Sparkles :size="15"/>
        </button>
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

    <HandoffBar
        :conversation-id="conversationId || ''"
        :status="status"
        :ticket="ticket"
        :can-handoff="canHandoff"
        :user-name="auth.username || ''"
        :agent-name="supportAgentName || ''"
        @handoff="handleHandoff"
        @cancelled="() => {}"
        @restart="handleRestart"
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

    <div v-if="showPrompts && messages.length === 0 && starterPrompts.length" class="quick-questions">
      <button
          v-for="item in starterPrompts"
          :key="item.text"
          type="button"
          class="quick-chip"
          :disabled="streaming"
          @click="askQuick(item)"
      >
        {{ item.text }}
      </button>
      <button type="button" class="quick-chip is-more" @click="panelOpen = true">
        全部演示提问
      </button>
    </div>

    <!-- 演示提问面板：按「能演示什么」分组，副标题写清楚会看到什么 -->
    <div v-if="panelOpen && showPrompts" class="prompt-panel">
      <header class="panel-head">
        <span class="panel-title">
          <Sparkles :size="13"/>
          演示提问
        </span>
        <span class="panel-hint">点一下直接发送；灰色小字是「这一问能看到什么」</span>
        <button type="button" class="panel-close" @click="panelOpen = false">×</button>
      </header>
      <div class="panel-body">
        <section v-for="section in quickSections" :key="section.title" class="prompt-group">
          <h4>
            {{ section.title }}
            <span v-if="section.note" class="group-note">{{ section.note }}</span>
          </h4>
          <button
              v-for="item in section.items"
              :key="item.text"
              type="button"
              class="prompt-item"
              :disabled="streaming"
              @click="askQuick(item)"
          >
            <span class="prompt-text">{{ item.text }}</span>
            <span v-if="item.expect" class="prompt-expect">{{ item.expect }}</span>
          </button>
        </section>
      </div>
    </div>

    <div class="composer">
      <MentionInput
          v-model="input"
          :agents="humanActive ? [] : agents"
          :disabled="streaming || conversationClosed"
          :streaming="streaming"
          :placeholder="composerPlaceholder"
          :hint="composerHint"
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

        &.is-human {
          color: #047857;
        }
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

      .memory-flag {
        display: inline-flex;
        align-items: center;
        padding: 1px 8px;
        border-radius: 8px;
        border: 1px solid #fecaca;
        background: #fff7f7;
        color: #b91c1c;
        font-size: 11px;
        line-height: 18px;
        white-space: nowrap;
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

        &.is-on {
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

      &.is-more {
        border-style: dashed;
        border-color: #e5e7eb;
        background: #fff;
        color: #6b7280;

        &:hover {
          border-color: #fecaca;
          color: #b91c1c;
          background: #fff;
        }
      }
    }
  }

  .prompt-panel {
    flex-shrink: 0;
    max-height: 44vh;
    overflow-y: auto;
    padding: 10px 16px 2px;
    border-top: 1px solid #f3f4f6;
    background: #fcfcfd;

    .panel-head {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;

      .panel-title {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        font-size: 12px;
        font-weight: 600;
        color: #b91c1c;
        white-space: nowrap;
      }

      .panel-hint {
        flex: 1;
        min-width: 0;
        font-size: 11px;
        color: #9ca3af;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .panel-close {
        flex-shrink: 0;
        padding: 0 2px;
        border: none;
        background: transparent;
        color: #9ca3af;
        font-size: 16px;
        line-height: 1;
        cursor: pointer;
      }
    }

    .prompt-group {
      margin-bottom: 10px;

      h4 {
        display: flex;
        flex-wrap: wrap;
        align-items: baseline;
        gap: 6px;
        margin: 0 0 6px;
        font-size: 12px;
        font-weight: 600;
        color: #374151;
      }

      .group-note {
        font-size: 11px;
        font-weight: 400;
        color: #9ca3af;
      }

      .prompt-item {
        display: flex;
        flex-direction: column;
        gap: 1px;
        width: 100%;
        margin-bottom: 6px;
        padding: 7px 10px;
        border: 1px solid #f1e3e3;
        border-radius: 9px;
        background: #fff;
        text-align: left;
        cursor: pointer;

        &:hover:not(:disabled) {
          border-color: #fecaca;
          background: #fff7f7;
        }

        &:disabled {
          opacity: 0.55;
          cursor: not-allowed;
        }

        .prompt-text {
          font-size: 12.5px;
          color: #111827;
          word-break: break-word;
        }

        .prompt-expect {
          font-size: 11px;
          color: #9ca3af;
        }
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
