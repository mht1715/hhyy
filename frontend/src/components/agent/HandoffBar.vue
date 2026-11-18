<script setup>
/**
 * 转人工状态条（契约 §7.1）。
 *
 * 5 个状态：
 *   idle          未转人工，展示「转人工」按钮（未登录改展示登录引导）
 *   queued        排队中，倒计时用服务端下发的 queue_expires_in 递减，归零切 offline
 *   human_active  坐席已接入（输入框继续可用，消息走 WS）
 *   offline       留言表单（姓名 / 联系方式 / 诉求）
 *   closed        会话结束 + 重新开始
 *
 * 服务端状态（props.status）是唯一真相；本地只在「倒计时归零」和「用户取消」时
 * 用 localMode 做一次临时覆盖，状态一变就重新让位给 props。
 */
import {computed, onBeforeUnmount, reactive, ref, watch} from 'vue'
import {showToast} from 'vant'
import {useRoute} from 'vue-router'
import {CheckCircle2, Headphones} from 'lucide-vue-next'
import {useAuthStore} from '../../store/auth'
import {submitOfflineMessage} from '../../api/support'

const props = defineProps({
  conversationId: {type: String, default: ''},
  // bot_active / handoff_pending / human_active / closed（'' 视为 bot_active）
  status: {type: String, default: ''},
  // 活跃工单：{ticket_id, status, queue_position, queue_expires_in, assigned_to, ...}
  ticket: {type: Object, default: null},
  canHandoff: {type: Boolean, default: true},
  userName: {type: String, default: ''},
  // 可选：WS ready/status 帧带回来的坐席名
  agentName: {type: String, default: ''}
})

const emit = defineEmits(['handoff', 'offline-submitted', 'cancelled', 'restart'])

const auth = useAuthStore()
const route = useRoute()

const STATUS_VALUES = ['bot_active', 'handoff_pending', 'human_active', 'closed']

const localMode = ref('')
const remaining = ref(0)
const submitting = ref(false)
const submitted = ref(false)
const form = reactive({name: props.userName || '', contact: '', demand: ''})

let ticker = null
let ticketKey = ''

const normalizeStatus = (value) => (STATUS_VALUES.includes(value) ? value : 'bot_active')

const viewMode = computed(() => {
  if (localMode.value) return localMode.value
  const base = normalizeStatus(props.status)
  return base === 'bot_active' ? 'idle' : base
})

const queuePosition = computed(() => {
  const value = Number(props.ticket && props.ticket.queue_position)
  return Number.isFinite(value) && value > 0 ? value : 0
})

const agentLabel = computed(() => {
  const assigned = props.ticket && props.ticket.assigned_to
  return assigned || props.agentName || '客服'
})

const countdownText = computed(() => {
  const seconds = Math.max(0, Number(remaining.value) || 0)
  const mm = Math.floor(seconds / 60)
  const ss = seconds % 60
  return `${mm}:${String(ss).padStart(2, '0')}`
})

const canSubmit = computed(() => (
  !submitting.value
  && !submitted.value
  && form.contact.trim().length > 0
  && form.demand.trim().length > 0
))

const stopTicker = () => {
  if (ticker) {
    clearInterval(ticker)
    ticker = null
  }
}

const startTicker = () => {
  stopTicker()
  if (viewMode.value !== 'queued') return
  ticker = setInterval(() => {
    if (remaining.value <= 0) {
      stopTicker()
      return
    }
    remaining.value -= 1
    if (remaining.value <= 0) {
      remaining.value = 0
      stopTicker()
      // 契约：90s 没人接管，前端自动展开留言表单
      localMode.value = 'offline'
    }
  }, 1000)
}

const syncState = () => {
  const base = normalizeStatus(props.status)
  const currentTicket = props.ticket || null
  const nextKey = currentTicket
    ? `${currentTicket.ticket_id || ''}:${currentTicket.queue_expires_in ?? ''}:${currentTicket.status || ''}`
    : ''

  // 新工单（或工单信息变了）→ 清掉本地覆盖，重新开始排队
  if (nextKey !== ticketKey) {
    ticketKey = nextKey
    submitted.value = false
    localMode.value = ''
    const expires = Number(currentTicket && currentTicket.queue_expires_in)
    remaining.value = Number.isFinite(expires) ? Math.max(0, Math.floor(expires)) : (base === 'handoff_pending' ? 90 : 0)
  }

  if (base === 'human_active' || base === 'closed') {
    localMode.value = ''
    submitted.value = false
    stopTicker()
    return
  }

  if (base === 'handoff_pending') {
    // 服务端说已过期，直接进留言
    if (remaining.value <= 0) {
      localMode.value = 'offline'
      stopTicker()
      return
    }
    if (!localMode.value) startTicker()
    return
  }

  stopTicker()
}

watch(
  () => [props.status, props.ticket, props.userName],
  () => {
    if (!form.name && props.userName) form.name = props.userName
    syncState()
  },
  {immediate: true, deep: true}
)

onBeforeUnmount(stopTicker)

const handleHandoff = () => {
  if (!props.canHandoff) {
    goLogin()
    return
  }
  emit('handoff')
}

const goLogin = () => {
  try {
    auth.isLoginModalOpen = true
  } catch (e) {
    // 没有 pinia 环境时退回路由首页，至少不会卡死
    if (route && route.path !== '/') window.location.href = `/?redirect=${encodeURIComponent(route.fullPath)}`
  }
}

const cancelQueue = () => {
  localMode.value = 'idle'
  stopTicker()
  emit('cancelled', {reason: 'queued'})
  showToast('已取消转接排队')
}

const dismissOffline = () => {
  // 不留言就回到 idle：还能再次点「转人工」（服务端建单是幂等的）
  localMode.value = 'idle'
  stopTicker()
  emit('cancelled', {reason: 'offline'})
}

const restart = () => {
  emit('restart')
}

const submitOffline = async () => {
  if (!canSubmit.value) {
    showToast('请填写联系方式和想咨询的问题')
    return
  }
  if (!props.conversationId) {
    showToast({type: 'fail', message: '会话不存在，请重新转人工'})
    return
  }

  submitting.value = true
  try {
    const data = await submitOfflineMessage({
      conversation_id: props.conversationId,
      name: form.name.trim(),
      contact: form.contact.trim(),
      demand: form.demand.trim()
    })
    if (data && data.saved === false) {
      showToast({type: 'fail', message: '留言未保存，请稍后重试'})
      return
    }
    submitted.value = true
    emit('offline-submitted', data || {})
    showToast('已记录，客服会在工作时间联系你')
  } catch (e) {
    // 后端没起 / 404 / 500 都走这里：只提示，不白屏
    showToast({type: 'fail', message: (e && e.message) || '留言提交失败，请稍后重试'})
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="handoff-bar" :class="`mode-${viewMode}`">
    <!-- idle：未转人工 -->
    <template v-if="viewMode === 'idle'">
      <p class="bar-text">AI 回答不了？可以转接人工客服</p>
      <button
          v-if="canHandoff"
          type="button"
          class="primary-btn"
          @click="handleHandoff"
      >
        <Headphones :size="13"/>
        <span>转人工</span>
      </button>
      <button
          v-else
          type="button"
          class="primary-btn is-light"
          @click="goLogin"
      >
        <span>登录后可转人工</span>
      </button>
    </template>

    <!-- queued：排队中 -->
    <template v-else-if="viewMode === 'queued'">
      <span class="status-dot"></span>
      <p class="bar-text">
        正在为你转接<template v-if="queuePosition">，当前第 {{ queuePosition }} 位</template>
      </p>
      <span class="countdown" :title="`预计等待 ${countdownText}`">{{ countdownText }}</span>
      <button type="button" class="ghost-btn" @click="cancelQueue">取消</button>
    </template>

    <!-- human_active：客服已接入 -->
    <template v-else-if="viewMode === 'human_active'">
      <span class="status-dot is-green"></span>
      <p class="bar-text">
        <strong>{{ agentLabel }}</strong> 已接入<em>，消息将由客服回复</em>
      </p>
      <span class="live-chip">人工在线</span>
    </template>

    <!-- closed：会话结束 -->
    <template v-else-if="viewMode === 'closed'">
      <p class="bar-text">本次会话已结束</p>
      <button type="button" class="ghost-btn" @click="restart">重新开始</button>
    </template>

    <!-- offline：留言 -->
    <template v-else-if="viewMode === 'offline'">
      <div v-if="submitted" class="offline-done">
        <CheckCircle2 :size="14"/>
        <span>已记录，客服会在工作时间联系你</span>
      </div>

      <template v-else>
        <div class="offline-head">
          <p class="bar-text">当前无客服在线，先留下联系方式吧</p>
          <button type="button" class="ghost-btn" @click="dismissOffline">暂不需要</button>
        </div>

        <form class="offline-form" @submit.prevent="submitOffline">
          <input
              v-model="form.name"
              class="field"
              type="text"
              maxlength="20"
              placeholder="姓名（选填）"
              autocomplete="name"
          />
          <input
              v-model="form.contact"
              class="field"
              type="text"
              maxlength="40"
              placeholder="手机号 / 微信"
              autocomplete="tel"
          />
          <input
              v-model="form.demand"
              class="field is-wide"
              type="text"
              maxlength="120"
              placeholder="想咨询的问题"
          />
          <button type="submit" class="primary-btn" :disabled="!canSubmit">
            {{ submitting ? '提交中…' : '提交留言' }}
          </button>
        </form>
      </template>
    </template>
  </div>
</template>

<style scoped lang="scss">
.handoff-bar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 48px;
  padding: 6px 16px;
  border-top: 1px solid #f3f4f6;
  background: #fafafa;
  font-size: 12px;
  line-height: 1.4;
  color: #6b7280;

  &.mode-queued {
    background: #fff7f7;
    color: #b91c1c;
  }

  &.mode-human_active {
    background: #ecfdf5;
    border-top-color: #d1fae5;
    color: #047857;
  }

  &.mode-closed {
    background: #f9fafb;
    color: #6b7280;
  }

  &.mode-offline {
    flex-direction: column;
    align-items: stretch;
    gap: 6px;
    padding: 8px 16px 10px;
    background: #fff7f7;
    color: #b91c1c;
  }

  .bar-text {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;

    strong {
      font-weight: 600;
    }

    em {
      font-style: normal;
      opacity: 0.75;
    }
  }

  .status-dot {
    flex-shrink: 0;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #ef4444;
    animation: handoff-pulse 1.1s ease-in-out infinite;

    &.is-green {
      background: #10b981;
      animation: none;
    }
  }

  .countdown {
    flex-shrink: 0;
    padding: 0 6px;
    border-radius: 6px;
    background: #fee2e2;
    color: #b91c1c;
    font-size: 11px;
    font-variant-numeric: tabular-nums;
    line-height: 18px;
  }

  .live-chip {
    flex-shrink: 0;
    padding: 0 6px;
    border-radius: 6px;
    background: #d1fae5;
    color: #047857;
    font-size: 11px;
    line-height: 18px;
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
    line-height: 1;
    white-space: nowrap;
    cursor: pointer;

    &:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }

    &.is-light {
      background: #fff;
      border: 1px solid #fecaca;
      color: #b91c1c;
      font-weight: 500;
    }
  }

  .ghost-btn {
    flex-shrink: 0;
    height: 26px;
    padding: 0 10px;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    background: #fff;
    color: #6b7280;
    font-size: 12px;
    line-height: 1;
    white-space: nowrap;
    cursor: pointer;

    &:hover {
      border-color: #fecaca;
      color: #b91c1c;
    }
  }

  .offline-head {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }

  .offline-done {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 0;
    color: #047857;
    font-size: 12px;
  }

  .offline-form {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;

    .field {
      min-width: 0;
      height: 30px;
      padding: 0 10px;
      border: 1px solid #f3f4f6;
      border-radius: 8px;
      background: #fff;
      color: #374151;
      font-family: inherit;
      font-size: 12px;
      outline: none;

      &::placeholder {
        color: #9ca3af;
      }

      &:focus {
        border-color: #fca5a5;
      }

      &.is-wide {
        grid-column: 1 / -1;
      }
    }

    .primary-btn {
      grid-column: 1 / -1;
      height: 30px;
    }
  }

  @media (max-width: 480px) {
    padding-left: 12px;
    padding-right: 12px;
    font-size: 11.5px;

    .offline-form {
      grid-template-columns: 1fr;

      .field.is-wide {
        grid-column: auto;
      }
    }
  }
}

@keyframes handoff-pulse {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }

  50% {
    opacity: 0.35;
    transform: scale(0.8);
  }
}
</style>
