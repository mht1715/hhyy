<script setup>
/**
 * 客服工作台（契约 §5.3 / §6 / §7.3，路由 /support，仅 support / admin）。
 *
 * 左：待接入队列（5s 轮询，等待时长按 created_at 每秒递增）
 * 右：会话详情（历史消息 + 交接摘要）+ 接管 / 结束 / 回复（接管后走 WS）
 *
 * 后端没起或接口 404/403 时都只是空态 + toast，不白屏。
 */
import {computed, nextTick, onBeforeUnmount, onMounted, ref, watch} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import {CheckCircle2, ChevronRight, Clock, Headphones, RefreshCw, Send, ShieldAlert, ShieldCheck, Timer, Users} from 'lucide-vue-next'
import dayjs from 'dayjs'
import {showToast} from 'vant'
import Navbar from '../components/Navbar.vue'
import PageBar from '../components/common/PageBar.vue'
import {
  acceptTicket,
  createWsTicket,
  fetchConversation,
  fetchTickets,
  resolveTicket,
  sendAgentMessage
} from '../api/support'
import {fetchSupportStats} from '../api/workbench'
import {useSupportSocket} from '../composables/useSupportSocket'

const router = useRouter()
const route = useRoute()

const TRIGGER_LABELS = {
  explicit: '用户主动转人工',
  agent_tool: 'AI 建议转人工',
  sensitive: '敏感风险',
  refusal: '连续拒答',
  emotion: '负面情绪'
}

const TICKET_STATUS_LABELS = {
  queued: '排队中',
  assigned: '已接管',
  resolved: '已结束',
  offline: '已留言'
}

const CONVERSATION_STATUS_LABELS = {
  bot_active: 'AI 接待中',
  handoff_pending: '等待转接',
  human_active: '人工客服已接入',
  closed: '已结束'
}

const forbidden = ref(false)
const tickets = ref([])
const queueLoading = ref(false)
const queueError = ref('')
const now = ref(Date.now())

// M5：工作台顶部要能一眼看到「今天接待了多少、平均等多久」。
// 这个聚合接口独立于工单列表：工单列表只返回未结的，统计要的是 24h 窗口。
const stats = ref(null)
const statsLoading = ref(false)

const selectedTicketId = ref('')
const detail = ref(null)
const detailLoading = ref(false)
const detailError = ref('')

const acting = ref('')
const draft = ref('')
const sending = ref(false)

let pollTimer = null
let clockTimer = null

/* ------------------------------------------------------------------ *
 * WebSocket（接管后用）
 * ------------------------------------------------------------------ */

const socket = useSupportSocket({
  conversationId: () => (detail.value ? detail.value.id : ''),
  wsTicket: async () => {
    const data = await createWsTicket()
    return (data && data.ws_ticket) || ''
  }
})

// 解构后模板里自动解包
const {connected: socketConnected, status: socketStatus, messages: socketMessages, error: socketError} = socket

const messageAreaRef = ref(null)

const scrollToBottom = () => {
  nextTick(() => {
    const el = messageAreaRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

const appendSocketMessage = (raw) => {
  if (!raw || !detail.value) return
  const id = raw.id || raw.message_id
  if (!id) return
  // 广播帧的 role 一定带全（user / human_agent / assistant），这里再兜一层：
  // 认不出的角色按 AI 处理，绝不会把客服说的话标成「用户」
  const role = ['user', 'assistant', 'human_agent', 'system'].includes(raw.role)
    ? raw.role
    : 'assistant'
  const clientId = raw.client_message_id || ''
  const messages = detail.value.messages
  if (clientId && messages.some((item) => item.client_message_id === clientId)) return
  if (messages.some((item) => item.id === id)) return
  messages.push({
    ...raw,
    id,
    role,
    content: raw.content !== undefined ? raw.content : '',
    created_at: raw.created_at || new Date().toISOString()
  })
  scrollToBottom()
}

watch(() => socketMessages.value.length, () => {
  socketMessages.value.forEach(appendSocketMessage)
})

watch(() => socketStatus.value, (value) => {
  if (!value || !detail.value) return
  const changed = detail.value.status !== value
  detail.value.status = value
  const ticket = currentTicket.value
  if (ticket) {
    if (value === 'human_active') ticket.status = 'assigned'
    // 会话被结束（可能由另一端触发）：工单同步收尾，避免「结束会话」按钮还挂着
    if (value === 'closed' && ticket.status === 'assigned') ticket.status = 'resolved'
  }
  // ready 帧也会带一次状态：只有「真的变了」才提示，不然每次重连都弹一次
  if (!changed) return
  if (value === 'human_active') showToast('会话已接管，可以开始回复')
  if (value === 'closed') showToast('会话已结束')
})

watch(() => socketError.value, (value) => {
  if (value) showToast({type: 'fail', message: value})
})

/* ------------------------------------------------------------------ *
 * 队列
 * ------------------------------------------------------------------ */

const sortedTickets = computed(() => {
  const rank = (ticket) => (ticket.status === 'queued' ? 0 : 1)
  return [...tickets.value].sort((a, b) => {
    const diff = rank(a) - rank(b)
    if (diff !== 0) return diff
    const left = a.created_at ? dayjs(a.created_at).valueOf() : 0
    const right = b.created_at ? dayjs(b.created_at).valueOf() : 0
    return left - right
  })
})

const currentTicket = computed(() => (
  sortedTickets.value.find((ticket) => ticket.ticket_id === selectedTicketId.value) || null
))

const queueTitle = computed(() => {
  const queued = tickets.value.filter((ticket) => ticket.status === 'queued').length
  return queued > 0 ? `待接入 ${queued}` : '待接入队列'
})

const startPolling = () => {
  stopPolling()
  pollTimer = setInterval(() => {
    loadTickets()
  }, 5000)
}

const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const startClock = () => {
  if (clockTimer) return
  clockTimer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
}

const stopClock = () => {
  if (clockTimer) {
    clearInterval(clockTimer)
    clockTimer = null
  }
}

const loadTickets = async ({silent = false} = {}) => {
  if (forbidden.value) return
  if (!silent && tickets.value.length === 0) queueLoading.value = true
  try {
    // 不传 status：契约里默认就是 queued,assigned（避免自行拼多值状态的格式分歧）
    const data = await fetchTickets()
    tickets.value = Array.isArray(data) ? data : []
    queueError.value = ''
  } catch (e) {
    if (e && (e.status === 403 || e.status === 401)) {
      forbidden.value = true
      stopPolling()
    } else {
      queueError.value = (e && e.message) || '队列加载失败，稍后自动重试'
    }
  } finally {
    if (!silent) queueLoading.value = false
  }
}

/* ------------------------------------------------------------------ *
 * 会话详情
 * ------------------------------------------------------------------ */

const loadDetail = async (conversationId, {silent = false} = {}) => {
  if (!conversationId) {
    detail.value = null
    detailError.value = '这个工单没有关联会话'
    return
  }
  if (!silent) {
    detailLoading.value = true
    detailError.value = ''
  }
  try {
    const data = await fetchConversation(conversationId)
    detail.value = data
      ? {...data, messages: Array.isArray(data.messages) ? data.messages : []}
      : null
    detailError.value = ''
    scrollToBottom()
  } catch (e) {
    // 静默刷新失败不清空已有内容：正在看的会话不能因为一次网络抖动变成白屏
    if (!silent) {
      detail.value = null
      detailError.value = (e && e.message) || '会话详情加载失败'
    }
  } finally {
    if (!silent) detailLoading.value = false
  }
}

const selectTicket = async (ticket) => {
  if (!ticket) return
  const previousConversationId = detail.value ? detail.value.id : ''
  const nextConversationId = ticket.conversation_id || ''
  // 切到别的会话：先断开旧会话的 WS，避免消息串台
  if (previousConversationId && previousConversationId !== nextConversationId) {
    socket.close()
  }
  selectedTicketId.value = ticket.ticket_id
  // 地址栏记住选中的工单：刷新工作台还能回到这个会话
  if (String(route.query.ticket || '') !== ticket.ticket_id) {
    router.replace({query: {...route.query, ticket: ticket.ticket_id}}).catch(() => {})
  }
  await loadDetail(nextConversationId)
  // 只要选中了会话就连实时通道：排队阶段也要能看到用户新说的话、以及 AI 补完的回答
  if (detail.value && nextConversationId) {
    socket.connect()
    startDetailPolling()
  }
}

/* ------------------------------------------------------------------ *
 * 详情软刷新（3s）
 *
 * 两个必须轮询的理由：
 * 1. 敏感场景在生成**之前**就建单，坐席点进来时 AI 那条消息可能还没写完；
 * 2. 工单状态也可能被另一端改（另一个坐席接管 / 用户取消）。
 * WS 负责「即时」，轮询负责「兜底」，两者都不贵。
 * ------------------------------------------------------------------ */

let detailTimer = null

const startDetailPolling = () => {
  stopDetailPolling()
  detailTimer = setInterval(() => {
    const cid = detail.value ? detail.value.id : ''
    if (!cid) return
    // 只刷详情；队列有自己的 5s 轮询，别把同一份数据拉两遍
    loadDetail(cid, {silent: true})
  }, 3000)
}

const stopDetailPolling = () => {
  if (detailTimer) {
    clearInterval(detailTimer)
    detailTimer = null
  }
}

const detailTicket = computed(() => (detail.value && detail.value.ticket) || null)

const summary = computed(() => {
  const ticket = detailTicket.value
  return (ticket && ticket.summary) || {}
})

const riskFlags = computed(() => {
  const ticket = detailTicket.value
  const fromTicket = ticket && Array.isArray(ticket.risk_flags) ? ticket.risk_flags : []
  const fromSummary = summary.value && Array.isArray(summary.value.risk_flags) ? summary.value.risk_flags : []
  return [...new Set([...fromTicket, ...fromSummary])]
})

const triedSteps = computed(() => (
  summary.value && Array.isArray(summary.value.tried_steps) ? summary.value.tried_steps : []
))

const conversationStatus = computed(() => {
  if (!detail.value) return ''
  return detail.value.status || ''
})

const conversationStatusText = computed(() => (
  CONVERSATION_STATUS_LABELS[conversationStatus.value] || conversationStatus.value || ''
))

const canReply = computed(() => {
  const ticket = currentTicket.value
  if (!ticket) return false
  if (ticket.status !== 'assigned') return false
  return conversationStatus.value !== 'closed'
})

const replyHint = computed(() => {
  if (!currentTicket.value) return '选择一个会话后可以接管并回复'
  if (conversationStatus.value === 'closed') return '本次会话已结束'
  if (currentTicket.value.status === 'queued') return '先「接管」才能回复用户'
  return 'Enter 发送，Shift + Enter 换行'
})

const triggerText = (trigger) => TRIGGER_LABELS[trigger] || trigger || '未知触发'

const ticketStatusText = (status) => TICKET_STATUS_LABELS[status] || status || ''

const waitSeconds = (ticket) => {
  if (!ticket) return 0
  const created = ticket.created_at ? dayjs(ticket.created_at) : null
  if (created && created.isValid()) {
    return Math.max(0, Math.floor((now.value - created.valueOf()) / 1000))
  }
  return Math.max(0, Number(ticket.wait_seconds) || 0)
}

const formatWait = (seconds) => {
  const value = Math.max(0, Math.floor(Number(seconds) || 0))
  const hours = Math.floor(value / 3600)
  const minutes = Math.floor((value % 3600) / 60)
  const rest = value % 60
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`
  }
  return `${minutes}:${String(rest).padStart(2, '0')}`
}

const formatTime = (value) => {
  if (!value) return ''
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('MM-DD HH:mm') : ''
}

const roleLabel = (message) => {
  if (!message) return ''
  if (message.role === 'user') return '用户'
  if (message.role === 'human_agent') return message.actor_name || '客服'
  if (message.role === 'system') return '系统'
  return 'AI 助手'
}

const roleClass = (message) => {
  const value = message && message.role
  return ['user', 'assistant', 'human_agent', 'system'].includes(value) ? `role-${value}` : 'role-assistant'
}

/* ------------------------------------------------------------------ *
 * 操作
 * ------------------------------------------------------------------ */

const handleAccept = async () => {
  const ticket = currentTicket.value
  if (!ticket || acting.value) return
  acting.value = 'accept'
  try {
    const data = await acceptTicket(ticket.ticket_id)
    ticket.status = 'assigned'
    ticket.assigned_to = ticket.assigned_to || '我'

    const conversationId = (data && data.conversation_id) || ticket.conversation_id
    if (conversationId && (!detail.value || detail.value.id !== conversationId)) {
      await loadDetail(conversationId)
    }
    if (detail.value) {
      detail.value.status = (data && data.status_of_conversation) || 'human_active'
      if (detail.value.ticket) detail.value.ticket.status = 'assigned'
    }
    // 队列立刻刷新：这条从「排队中」变「已接管」，不用等下一次轮询
    await loadTickets({silent: true})
    startPolling()
    startDetailPolling()
    await socket.connect()
    showToast('已接管会话')
  } catch (e) {
    showToast({type: 'fail', message: (e && e.message) || '接管失败，请稍后重试'})
  } finally {
    acting.value = ''
  }
}

const handleResolve = async () => {
  const ticket = currentTicket.value
  if (!ticket || acting.value) return
  acting.value = 'resolve'
  try {
    await resolveTicket(ticket.ticket_id)
    ticket.status = 'resolved'
    socket.close()
    stopDetailPolling()
    // 结束就离开这条会话：右侧留着一条已关闭的详情只会让人以为还能回
    selectedTicketId.value = ''
    detail.value = null
    if (route.query.ticket) {
      const query = {...route.query}
      delete query.ticket
      router.replace({query}).catch(() => {})
    }
    await loadTickets({silent: true})
    startPolling()
    showToast('会话已结束，AI 已接回该用户')
  } catch (e) {
    showToast({type: 'fail', message: (e && e.message) || '结束会话失败，请稍后重试'})
  } finally {
    acting.value = ''
  }
}

const handleSend = async () => {
  const content = draft.value.trim()
  if (!content || sending.value) return
  if (!canReply.value) {
    showToast('请先接管会话再回复')
    return
  }

  sending.value = true
  try {
    if (socketConnected.value && socket.send(content)) {
      draft.value = ''
      return
    }
    // WS 不可用：退化为 HTTP 发消息（契约 §5.3），并重新拉一次详情
    await sendAgentMessage(currentTicket.value.ticket_id, content)
    draft.value = ''
    if (detail.value) await loadDetail(detail.value.id)
    showToast('消息已发送')
  } catch (e) {
    showToast({type: 'fail', message: (e && e.message) || '消息发送失败'})
  } finally {
    sending.value = false
  }
}

const handleComposerKeydown = (event) => {
  if (event.key !== 'Enter' || event.shiftKey) return
  event.preventDefault()
  handleSend()
}

const loadStats = async () => {
  statsLoading.value = true
  try {
    stats.value = await fetchSupportStats()
  } catch (e) {
    // 统计是辅助信息：拿不到就不显示数字，不能因此让队列也进错误态
    stats.value = null
  } finally {
    statsLoading.value = false
  }
}

const formatSeconds = (value) => {
  const total = Number(value || 0)
  if (!total) return '—'
  const minutes = Math.floor(total / 60)
  const seconds = Math.round(total % 60)
  return minutes ? `${minutes}m${seconds}s` : `${seconds}s`
}

const refreshQueue = async () => {
  forbidden.value = false
  await Promise.allSettled([loadTickets(), loadStats()])
  startPolling()
}

onMounted(async () => {
  startClock()
  await Promise.allSettled([loadTickets(), loadStats()])
  startPolling()
  // 刷新后回到刚才那条工单（?ticket=）
  const tid = route.query.ticket ? String(route.query.ticket) : ''
  if (!tid) return
  const match = tickets.value.find((item) => item.ticket_id === tid)
  if (match) await selectTicket(match)
})

onBeforeUnmount(() => {
  stopPolling()
  stopDetailPolling()
  stopClock()
  socket.close()
})
</script>

<template>
  <div class="support-page">
    <Navbar/>

    <main class="support-body">
      <!-- 之前这个页面完全没有返回入口：不管从药品详情、Agent 广场还是工作台进来，
           想回去只能按浏览器后退。PageBar 走 history.back()，
           真的没有来源（直接打开链接）才落到首页。 -->
      <PageBar
          title="客服工作台"
          subtitle="待接入队列 · 实时消息"
          back-to="/"
          back-label="返回"
          sticky
      />

      <section v-if="forbidden" class="forbidden-card">
        <ShieldAlert :size="30" color="#ef4444"/>
        <h2>仅客服与管理员可用</h2>
        <p>当前账号没有访问客服工作台的权限（需要 support 或 admin 角色）。</p>
        <button type="button" class="ghost-btn" @click="router.push('/')">返回首页</button>
      </section>

      <template v-else>
        <!-- M5：坐席的「今日战况」。数字来自 /api/support/stats（24h 窗口），
             拿不到就整条隐藏，不占位也不影响队列。 -->
        <div v-if="stats" class="support-stats">
          <div class="stat-pill">
            <Clock :size="13"/>
            <div>
              <b>{{ stats.queued }}</b>
              <small>排队待接管</small>
            </div>
          </div>
          <div class="stat-pill">
            <Users :size="13"/>
            <div>
              <b>{{ stats.accepted }}</b>
              <small>24h 已接管</small>
            </div>
          </div>
          <div class="stat-pill">
            <CheckCircle2 :size="13"/>
            <div>
              <b>{{ stats.resolved }}</b>
              <small>24h 已结束</small>
            </div>
          </div>
          <div class="stat-pill">
            <Timer :size="13"/>
            <div>
              <b>{{ formatSeconds(stats.avg_wait_seconds) }}</b>
              <small>平均等待</small>
            </div>
          </div>
          <button type="button" class="stat-refresh" :disabled="statsLoading" @click="loadStats">
            <RefreshCw :size="12" :class="{ spinning: statsLoading }"/>
          </button>
        </div>

        <div class="support-cols">
          <!-- 左：待接入队列 -->
        <aside class="queue-panel">
          <header class="panel-head">
            <div class="panel-title">
              <Headphones :size="15" color="#ef4444"/>
              <span>{{ queueTitle }}</span>
            </div>
            <button type="button" class="icon-btn" title="刷新队列" @click="refreshQueue">
              <RefreshCw :size="14"/>
            </button>
          </header>

          <div class="queue-body">
            <div v-if="queueLoading" class="queue-state">正在加载队列…</div>
            <div v-else-if="queueError" class="queue-state is-error">
              <p>{{ queueError }}</p>
              <button type="button" class="ghost-btn" @click="refreshQueue">重试</button>
            </div>
            <div v-else-if="sortedTickets.length === 0" class="queue-state">
              <ShieldCheck :size="20" color="#10b981"/>
              <p>暂无待接入会话，休息一下</p>
            </div>

            <ul v-else class="ticket-list">
              <li
                  v-for="ticket in sortedTickets"
                  :key="ticket.ticket_id"
                  class="ticket-card"
                  :class="{ active: ticket.ticket_id === selectedTicketId, 'is-assigned': ticket.status === 'assigned' }"
                  @click="selectTicket(ticket)"
              >
                <div class="card-top">
                  <span class="user-label" :title="ticket.user_label || ''">
                    {{ ticket.user_label || '匿名用户' }}
                  </span>
                  <span class="status-chip" :class="`status-${ticket.status}`">
                    {{ ticketStatusText(ticket.status) }}
                  </span>
                </div>

                <div class="card-meta">
                  <span class="wait-time">
                    <Clock :size="11"/>
                    等待 {{ formatWait(waitSeconds(ticket)) }}
                  </span>
                  <span class="trigger-chip">{{ triggerText(ticket.trigger) }}</span>
                </div>

                <div v-if="ticket.risk_flags && ticket.risk_flags.length" class="risk-row">
                  <span v-for="flag in ticket.risk_flags" :key="flag" class="risk-tag">{{ flag }}</span>
                </div>

                <p v-if="ticket.summary && ticket.summary.intent" class="card-intent">
                  诉求：{{ ticket.summary.intent }}
                </p>
                <p v-if="ticket.summary && ticket.summary.suggested_reply" class="card-reply">
                  建议：{{ ticket.summary.suggested_reply }}
                </p>

                <div class="card-foot">
                  <span class="conversation-title">{{ ticket.conversation_title || '未命名会话' }}</span>
                  <span class="created-at">{{ formatTime(ticket.created_at) }}</span>
                  <!-- 卡片整块可点，但只有 hover 不够明显，给一个常驻右箭头 -->
                  <ChevronRight :size="13" class="card-arrow"/>
                </div>
              </li>
            </ul>
          </div>
        </aside>

        <!-- 右：会话详情 -->
        <section class="detail-panel">
          <div v-if="!selectedTicketId" class="detail-empty">
            <Headphones :size="26" color="#ef4444"/>
            <p>从左侧选择一条待接入会话</p>
            <span>接管后即可与用户实时对话</span>
          </div>

          <div v-else-if="detailLoading" class="detail-empty">
            <p>正在加载会话详情…</p>
          </div>

          <div v-else-if="detailError" class="detail-empty is-error">
            <ShieldAlert :size="22" color="#ef4444"/>
            <p>{{ detailError }}</p>
            <button
                type="button"
                class="ghost-btn"
                @click="loadDetail(currentTicket && currentTicket.conversation_id)"
            >
              重试
            </button>
          </div>

          <template v-else-if="detail">
            <header class="detail-head">
              <div class="head-main">
                <h3>{{ detail.title || (currentTicket && currentTicket.conversation_title) || '会话详情' }}</h3>
                <div class="head-meta">
                  <span class="status-chip" :class="`status-${conversationStatus}`">
                    {{ conversationStatusText }}
                  </span>
                  <span v-if="currentTicket && currentTicket.user_label" class="meta-text">
                    {{ currentTicket.user_label }}
                  </span>
                  <span v-if="currentTicket" class="meta-text">
                    等待 {{ formatWait(waitSeconds(currentTicket)) }}
                  </span>
                </div>
              </div>

              <div class="head-actions">
                <span v-if="socketConnected" class="live-dot">实时连接</span>
                <button
                    v-if="currentTicket && currentTicket.status === 'queued'"
                    type="button"
                    class="primary-btn"
                    :disabled="acting === 'accept'"
                    @click="handleAccept"
                >
                  <Headphones :size="13"/>
                  <span>{{ acting === 'accept' ? '接管中…' : '接管' }}</span>
                </button>
                <button
                    v-if="currentTicket && currentTicket.status === 'assigned'"
                    type="button"
                    class="ghost-btn"
                    :disabled="acting === 'resolve'"
                    @click="handleResolve"
                >
                  <CheckCircle2 :size="13"/>
                  <span>{{ acting === 'resolve' ? '结束中…' : '结束会话' }}</span>
                </button>
              </div>
            </header>

            <div class="summary-block">
              <div class="summary-row">
                <span class="summary-label">诉求</span>
                <span class="summary-value">{{ summary.intent || currentTicket?.reason || '未提供' }}</span>
              </div>
              <div class="summary-row">
                <span class="summary-label">已尝试</span>
                <span class="summary-value">
                  {{ triedSteps.length > 0 ? triedSteps.join(' / ') : '暂无' }}
                </span>
              </div>
              <div class="summary-row">
                <span class="summary-label">未解决</span>
                <span class="summary-value">{{ summary.unresolved || '未说明' }}</span>
              </div>
              <div class="summary-row">
                <span class="summary-label">风险</span>
                <span class="summary-value">
                  <template v-if="riskFlags.length">
                    <span v-for="flag in riskFlags" :key="flag" class="risk-tag">{{ flag }}</span>
                  </template>
                  <template v-else>无</template>
                </span>
              </div>
              <div class="summary-row">
                <span class="summary-label">建议话术</span>
                <span class="summary-value">{{ summary.suggested_reply || '暂无' }}</span>
              </div>
            </div>

            <div ref="messageAreaRef" class="message-area">
              <div v-if="detail.messages.length === 0" class="detail-empty is-inline">
                <p>暂无历史消息</p>
              </div>
              <div
                  v-for="message in detail.messages"
                  :key="message.id"
                  class="support-message"
                  :class="roleClass(message)"
              >
                <div class="message-head">
                  <span class="role-name">{{ roleLabel(message) }}</span>
                  <span v-if="message.role === 'human_agent'" class="human-badge">客服</span>
                  <span class="message-time">{{ formatTime(message.created_at) }}</span>
                </div>
                <div class="message-body">{{ message.content }}</div>
              </div>
            </div>

            <div class="composer">
              <textarea
                  v-model="draft"
                  class="composer-input"
                  rows="2"
                  :placeholder="canReply ? '回复用户…' : replyHint"
                  :disabled="!canReply"
                  @keydown="handleComposerKeydown"
              ></textarea>
              <div class="composer-foot">
                <span class="composer-hint">{{ replyHint }}</span>
                <button
                    type="button"
                    class="primary-btn"
                    :disabled="!canReply || sending || !draft.trim()"
                    @click="handleSend"
                >
                  <Send :size="13"/>
                  <span>{{ sending ? '发送中…' : '发送' }}</span>
                </button>
              </div>
            </div>
          </template>
        </section>
        </div>
      </template>
    </main>
  </div>
</template>

<style scoped lang="scss">
.support-page {
  min-height: 100vh;
  background: #f3f4f6;
  padding-top: 64px;

  .support-body {
    width: 100%;
    max-width: 1180px;
    height: calc(100vh - 64px);
    margin: 0 auto;
    padding: 12px 16px 16px;
    display: flex;
    /* M5：顶部多了一条统计栏，所以整体改成「竖向：统计 + 双栏」 */
    flex-direction: column;
    gap: 10px;
    min-height: 0;
  }

  .support-stats {
    flex-shrink: 0;
    display: flex;
    align-items: stretch;
    gap: 8px;
    overflow-x: auto;
    scrollbar-width: none;

    &::-webkit-scrollbar {
      display: none;
    }

    .stat-pill {
      flex: 1 0 auto;
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 128px;
      padding: 8px 12px;
      background: #fff;
      border: 1px solid #f3f4f6;
      border-radius: 10px;
      color: #b91c1c;

      div {
        display: flex;
        flex-direction: column;
        line-height: 1.2;
      }

      b {
        font-size: 15px;
        color: #111827;
      }

      small {
        font-size: 10.5px;
        color: #9ca3af;
        white-space: nowrap;
      }
    }

    .stat-refresh {
      flex-shrink: 0;
      display: grid;
      place-items: center;
      width: 32px;
      border: 1px solid #f3f4f6;
      border-radius: 10px;
      background: #fff;
      color: #6b7280;
      cursor: pointer;

      .spinning {
        animation: support-spin 0.9s linear infinite;
      }
    }
  }

  .support-cols {
    flex: 1;
    display: flex;
    gap: 12px;
    min-height: 0;
  }

  .forbidden-card {
    flex: 1;
    align-self: center;
    max-width: 420px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    padding: 36px 24px;
    background: #fff;
    border: 1px solid #f3f4f6;
    border-radius: 12px;
    text-align: center;

    h2 {
      font-size: 16px;
      font-weight: 600;
      color: #111827;
    }

    p {
      font-size: 12.5px;
      line-height: 1.7;
      color: #6b7280;
    }
  }

  .panel-head {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 12px 14px;
    border-bottom: 1px solid #f3f4f6;

    .panel-title {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 14px;
      font-weight: 600;
      color: #111827;
      min-width: 0;
    }

    .icon-btn {
      width: 28px;
      height: 28px;
      flex-shrink: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      border: none;
      border-radius: 50%;
      background: #f9fafb;
      color: #6b7280;
      cursor: pointer;

      &:hover {
        background: #fef2f2;
        color: #ef4444;
      }
    }
  }

  .queue-panel,
  .detail-panel {
    display: flex;
    flex-direction: column;
    min-height: 0;
    background: #fff;
    border: 1px solid #f3f4f6;
    border-radius: 12px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
    overflow: hidden;
  }

  .queue-panel {
    width: 336px;
    flex-shrink: 0;
  }

  .detail-panel {
    flex: 1;
    min-width: 0;
  }

  .queue-body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 10px;
  }

  .queue-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 32px 12px;
    text-align: center;
    font-size: 12.5px;
    line-height: 1.7;
    color: #9ca3af;

    &.is-error {
      color: #b91c1c;
    }
  }

  .ticket-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .ticket-card {
    padding: 10px;
    border: 1px solid #f3f4f6;
    border-radius: 10px;
    background: #fcfcfd;
    cursor: pointer;
    transition: border-color 0.15s ease, background-color 0.15s ease;

    &:hover {
      border-color: #fecaca;
      background: #fff7f7;
    }

    &.active {
      border-color: #fecaca;
      background: #fff7f7;
      box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.08);
    }

    &.is-assigned {
      background: #f0fdf4;
      border-color: #bbf7d0;
    }

    .card-top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;

      .user-label {
        flex: 1;
        min-width: 0;
        font-size: 12.5px;
        font-weight: 600;
        color: #111827;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
    }

    .card-meta {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      margin-top: 6px;

      .wait-time {
        display: inline-flex;
        align-items: center;
        gap: 3px;
        font-size: 11px;
        color: #6b7280;
        font-variant-numeric: tabular-nums;
      }

      .trigger-chip {
        padding: 0 6px;
        border-radius: 6px;
        background: #f3f4f6;
        color: #6b7280;
        font-size: 10.5px;
        line-height: 17px;
      }
    }

    .risk-row {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      margin-top: 6px;
    }

    .card-intent,
    .card-reply {
      margin-top: 6px;
      font-size: 11.5px;
      line-height: 1.6;
      color: #4b5563;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }

    .card-reply {
      color: #9ca3af;
    }

    .card-foot {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-top: 8px;
      font-size: 10.5px;
      color: #9ca3af;

      .conversation-title {
        flex: 1;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .created-at {
        flex-shrink: 0;
      }

      /* 右箭头是「这张卡能点开」的常驻信号，不依赖 hover（手机没有 hover） */
      .card-arrow {
        flex-shrink: 0;
        color: #d1d5db;
        transition: color 0.16s, transform 0.16s;
      }
    }

    &:hover .card-foot .card-arrow {
      color: #dc2626;
      transform: translateX(2px);
    }
  }

  .status-chip {
    flex-shrink: 0;
    padding: 0 6px;
    border-radius: 6px;
    background: #f3f4f6;
    color: #6b7280;
    font-size: 10.5px;
    line-height: 17px;
    white-space: nowrap;

    &.status-queued {
      background: #fef2f2;
      color: #b91c1c;
    }

    &.status-assigned,
    &.status-human_active {
      background: #ecfdf5;
      color: #047857;
    }

    &.status-closed,
    &.status-resolved {
      background: #f3f4f6;
      color: #6b7280;
    }

    &.status-handoff_pending {
      background: #fff7ed;
      color: #c2410c;
    }
  }

  .risk-tag {
    display: inline-block;
    margin-right: 4px;
    padding: 0 6px;
    border-radius: 6px;
    background: #fef2f2;
    border: 1px solid #fecaca;
    color: #b91c1c;
    font-size: 10.5px;
    line-height: 16px;
  }

  .detail-head {
    flex-shrink: 0;
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 10px;
    padding: 12px 14px;
    border-bottom: 1px solid #f3f4f6;

    .head-main {
      min-width: 0;

      h3 {
        font-size: 14.5px;
        font-weight: 600;
        color: #111827;
        line-height: 1.5;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
    }

    .head-meta {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      margin-top: 5px;
      font-size: 11px;
      color: #9ca3af;
    }

    .head-actions {
      flex-shrink: 0;
      display: flex;
      align-items: center;
      gap: 8px;

      .live-dot {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        font-size: 11px;
        color: #047857;

        &::before {
          content: '';
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: #10b981;
        }
      }
    }
  }

  .summary-block {
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 10px 14px;
    background: #fcfcfd;
    border-bottom: 1px solid #f3f4f6;

    .summary-row {
      display: flex;
      gap: 8px;
      font-size: 11.5px;
      line-height: 1.65;

      .summary-label {
        flex-shrink: 0;
        width: 52px;
        color: #9ca3af;
      }

      .summary-value {
        flex: 1;
        min-width: 0;
        color: #374151;
        word-break: break-word;
      }
    }
  }

  .message-area {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 12px 14px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    background: #fff;
  }

  .support-message {
    max-width: 86%;

    .message-head {
      display: flex;
      align-items: center;
      gap: 6px;
      margin-bottom: 3px;
      font-size: 10.5px;
      color: #9ca3af;
    }

    .role-name {
      font-weight: 600;
      color: #6b7280;
    }

    .human-badge {
      padding: 0 5px;
      border-radius: 5px;
      background: #dbeafe;
      color: #1d4ed8;
      font-size: 10px;
      line-height: 15px;
    }

    .message-body {
      padding: 8px 12px;
      border-radius: 10px;
      font-size: 13px;
      line-height: 1.7;
      white-space: pre-wrap;
      word-break: break-word;
    }

    &.role-user {
      align-self: flex-start;

      .message-body {
        background: #f3f4f6;
        color: #374151;
      }
    }

    &.role-assistant,
    &.role-system {
      align-self: flex-start;

      .message-body {
        background: #fff;
        border: 1px solid #f3f4f6;
        color: #374151;
      }
    }

    &.role-human_agent {
      align-self: flex-end;

      .message-head {
        justify-content: flex-end;
      }

      .role-name {
        color: #1d4ed8;
      }

      .message-body {
        background: #eff6ff;
        border: 1px solid #bfdbfe;
        color: #1e3a8a;
      }
    }
  }

  .detail-empty {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 32px 16px;
    text-align: center;
    color: #9ca3af;

    p {
      font-size: 13px;
      line-height: 1.7;
      color: #6b7280;
    }

    span {
      font-size: 11.5px;
    }

    &.is-error {
      color: #b91c1c;

      p {
        color: #b91c1c;
      }
    }

    &.is-inline {
      padding: 16px;
      flex: none;
    }
  }

  .composer {
    flex-shrink: 0;
    padding: 10px 14px 12px;
    border-top: 1px solid #f3f4f6;
    background: #fff;

    .composer-input {
      width: 100%;
      min-height: 44px;
      max-height: 96px;
      padding: 8px 10px;
      border: 1px solid #f3f4f6;
      border-radius: 10px;
      background: #f9fafb;
      color: #374151;
      font-family: inherit;
      font-size: 13px;
      line-height: 1.6;
      resize: none;
      outline: none;

      &:focus {
        border-color: #fca5a5;
        background: #fff;
      }

      &:disabled {
        color: #9ca3af;
        cursor: not-allowed;
      }

      &::placeholder {
        color: #9ca3af;
      }
    }

    .composer-foot {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-top: 6px;

      .composer-hint {
        flex: 1;
        min-width: 0;
        font-size: 11px;
        color: #9ca3af;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
    }
  }

  .primary-btn {
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
    height: 28px;
    padding: 0 12px;
    border: none;
    border-radius: 8px;
    background: linear-gradient(135deg, #ef4444, #b91c1c);
    color: #fff;
    font-size: 12px;
    font-weight: 600;
    white-space: nowrap;
    cursor: pointer;

    &:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }
  }

  .ghost-btn {
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
    height: 28px;
    padding: 0 10px;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    background: #fff;
    color: #6b7280;
    font-size: 12px;
    white-space: nowrap;
    cursor: pointer;

    &:hover:not(:disabled) {
      border-color: #fecaca;
      color: #b91c1c;
    }

    &:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }
  }

  @media (max-width: 900px) {
    .support-body {
      height: calc(100vh - 64px);
      padding: 8px;
      gap: 8px;
    }

    /* 手机上队列和会话不再并排：队列压到上面，会话占满剩下的高度 */
    .support-cols {
      flex-direction: column;
      gap: 8px;
    }

    .support-stats {
      .stat-pill {
        min-width: 110px;
        padding: 6px 10px;
      }
    }

    .queue-panel {
      width: 100%;
      max-height: 34vh;
      flex-shrink: 0;
    }

    .detail-panel {
      flex: 1;
      min-height: 0;
    }

    .support-message {
      max-width: 94%;
    }
  }
}

@keyframes support-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
