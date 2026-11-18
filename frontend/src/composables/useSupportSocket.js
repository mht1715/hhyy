/**
 * 人工客服 WebSocket（契约见 docs/接口契约-M3.md §6）。
 *
 * 用法：
 *   const socket = useSupportSocket({
 *     conversationId: () => conversationId.value,   // 字符串 / ref / getter 均可
 *     wsTicket: async () => (await createWsTicket()).ws_ticket,
 *     autoConnect: false
 *   })
 *   await socket.connect()
 *
 * 关键约束（都来自契约）：
 * - 鉴权放在**第一帧** `{type:'auth', ticket}`，JWT / ticket 不进 query string；
 * - 服务端 25s 发 `ping`，客户端必须回 `{type:'pong'}`；
 * - 90s 没有任何帧就重连；重连指数退避 1s → 2s → 4s → 8s → 10s 封顶；
 * - 主动 close() 之后不再重连；组件卸载由 onScopeDispose 兜底 close。
 */

import {getCurrentScope, onScopeDispose, ref, unref} from 'vue'
import {createWsTicket} from '../api/support'

// 指数退避的档位，最后一项就是上限
const BACKOFF_STEPS = [1000, 2000, 4000, 8000, 10000]
// 超过这个时间没收到任何帧就认为连接已死（服务端 25s 一次 ping，留足余量）
const IDLE_TIMEOUT_MS = 90000

const resolveValue = (source) => (typeof source === 'function' ? source() : unref(source))

const wsBaseUrl = () => {
  const isHttps = typeof location !== 'undefined' && location.protocol === 'https:'
  const host = typeof location !== 'undefined' ? location.host : ''
  return `${isHttps ? 'wss' : 'ws'}://${host}`
}

const newLocalId = () => `ws-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`

/**
 * @param {{conversationId?: string|object|Function, wsTicket?: string|object|Function,
 *   autoConnect?: boolean}} options
 */
export function useSupportSocket({conversationId, wsTicket, autoConnect = false} = {}) {
  const connected = ref(false)
  const connecting = ref(false)
  /** 会话状态：human_active / closed …（来自 ready / status 帧） */
  const status = ref('')
  /** 最近一次 status/ready 帧带的工单信息 */
  const ticket = ref(null)
  /** ready 帧里的坐席名，或 status 帧的 by 字段 */
  const agentName = ref('')
  /** ready 帧里的角色：user / support */
  const role = ref('')
  const messages = ref([])
  const error = ref(null)

  let socket = null
  let closedByUser = false
  let disposed = false
  let attempt = 0
  let reconnectTimer = null
  let idleTimer = null
  let activeConversationId = ''

  const currentConversationId = () => {
    const value = resolveValue(conversationId)
    return value === undefined || value === null ? '' : String(value)
  }

  const clearIdleTimer = () => {
    if (idleTimer) {
      clearTimeout(idleTimer)
      idleTimer = null
    }
  }

  const clearReconnectTimer = () => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
  }

  const clearTimers = () => {
    clearIdleTimer()
    clearReconnectTimer()
  }

  // 任何一帧都算「连接还活着」
  const touchIdle = () => {
    clearIdleTimer()
    idleTimer = setTimeout(() => {
      idleTimer = null
      if (closedByUser || disposed) return
      // 假死连接：主动断开后走重连，而不是傻等 onclose
      error.value = '客服连接超时，正在重连…'
      dropSocket()
      scheduleReconnect()
    }, IDLE_TIMEOUT_MS)
  }

  const dropSocket = () => {
    const current = socket
    socket = null
    connected.value = false
    connecting.value = false
    if (!current) return
    try {
      current.onopen = null
      current.onmessage = null
      current.onclose = null
      current.onerror = null
      current.close()
    } catch (e) {
      // 已经关闭时 close() 可能抛错，忽略
    }
  }

  const sendRaw = (payload) => {
    if (!socket || socket.readyState !== 1) return false
    try {
      socket.send(JSON.stringify(payload))
      return true
    } catch (e) {
      return false
    }
  }

  const appendMessage = (raw) => {
    if (!raw || typeof raw !== 'object') return
    const id = raw.id || raw.message_id
    if (id && messages.value.some((item) => item.id === id)) return
    messages.value.push({
      ...raw,
      id: id || newLocalId(),
      role: raw.role || 'assistant',
      content: raw.content !== undefined ? raw.content : ''
    })
  }

  const handleFrame = (frame) => {
    if (!frame || typeof frame !== 'object') return

    switch (frame.type) {
      case 'ready':
        role.value = frame.role || ''
        if (frame.status) status.value = frame.status
        if (frame.name) agentName.value = frame.name
        if (frame.conversation_id) activeConversationId = String(frame.conversation_id)
        break

      case 'message':
        appendMessage(frame.message)
        break

      case 'status':
        if (frame.status) status.value = frame.status
        if (frame.ticket) ticket.value = frame.ticket
        if (frame.by) agentName.value = frame.by
        break

      case 'ping':
        // 契约要求回 pong，否则服务端可能判死
        sendRaw({type: 'pong'})
        break

      case 'error': {
        error.value = frame.message || '客服连接异常'
        const code = frame.code || ''
        // 鉴权类错误重连也没意义，直接停下
        if (code === 'FORBIDDEN' || code === 'UNAUTHORIZED') {
          closedByUser = true
          clearTimers()
          dropSocket()
        }
        break
      }

      default:
        // 未知帧忽略，保持向前兼容
        break
    }
  }

  const resolveTicket = async () => {
    const fromOption = typeof wsTicket === 'function' ? await wsTicket() : unref(wsTicket)
    if (fromOption) return String(fromOption)
    // 没给 ticket 时自己换一张短期票据，调用方就只用传 conversationId
    const data = await createWsTicket()
    return data && data.ws_ticket ? String(data.ws_ticket) : ''
  }

  const scheduleReconnect = () => {
    if (disposed || closedByUser) return
    const delay = BACKOFF_STEPS[Math.min(attempt, BACKOFF_STEPS.length - 1)]
    attempt += 1
    clearReconnectTimer()
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      connect()
    }, delay)
  }

  /**
   * 建立连接。重复调用是安全的（已连接 / 连接中直接返回）。
   * @returns {Promise<boolean>}
   */
  const connect = async () => {
    if (disposed) return false

    const cid = currentConversationId()
    if (!cid) {
      error.value = '缺少会话 ID，无法连接客服'
      return false
    }
    if (typeof WebSocket === 'undefined') {
      error.value = '当前浏览器不支持 WebSocket'
      return false
    }
    if (socket && (socket.readyState === 0 || socket.readyState === 1)) return true
    // 已经有一次 connect 在等票据：别再开第二条连接（重复握手会让服务端多一条订阅）
    if (connecting.value) return true

    closedByUser = false
    clearReconnectTimer()
    error.value = null
    connecting.value = true

    // 换了会话就清掉上一段的消息，断线重连则保留
    if (cid !== activeConversationId) {
      activeConversationId = cid
      messages.value = []
      ticket.value = null
      agentName.value = ''
      role.value = ''
      status.value = ''
    }

    let wsTicketValue = ''
    try {
      wsTicketValue = await resolveTicket()
    } catch (e) {
      connecting.value = false
      error.value = (e && e.message) || '获取客服连接凭证失败'
      scheduleReconnect()
      return false
    }

    if (!wsTicketValue) {
      connecting.value = false
      error.value = '获取客服连接凭证失败'
      scheduleReconnect()
      return false
    }

    let ws
    try {
      ws = new WebSocket(`${wsBaseUrl()}/ws/support/${encodeURIComponent(cid)}`)
    } catch (e) {
      connecting.value = false
      error.value = '客服连接创建失败'
      scheduleReconnect()
      return false
    }

    socket = ws

    ws.onopen = () => {
      if (socket !== ws) return
      connected.value = true
      connecting.value = false
      attempt = 0
      touchIdle()
      // 契约：连接建立后第一帧必须是 auth，ticket 不放 query string
      sendRaw({type: 'auth', ticket: wsTicketValue})
    }

    ws.onmessage = (event) => {
      if (socket !== ws) return
      touchIdle()
      let frame = null
      try {
        frame = JSON.parse(event.data)
      } catch (e) {
        return
      }
      handleFrame(frame)
    }

    ws.onerror = () => {
      if (socket !== ws) return
      error.value = error.value || '客服连接异常'
    }

    ws.onclose = () => {
      if (socket !== ws) return
      socket = null
      connected.value = false
      connecting.value = false
      clearIdleTimer()
      if (!closedByUser && !disposed) scheduleReconnect()
    }

    return true
  }

  /**
   * 发一条消息（坐席只有接管后才能发，未接管服务端会回 error:NOT_ASSIGNED）。
   * @param {string} content
   * @param {{clientMessageId?: string}} [options] 带上本地消息 id，服务端会原样回带，
   *   用来把「乐观气泡」和落库消息对齐（否则自己发的消息会显示两遍）
   * @returns {boolean} 是否已交给 socket
   */
  const send = (content, options = {}) => {
    const text = typeof content === 'string' ? content : ''
    if (!text.trim()) return false
    if (!connected.value) {
      error.value = '客服连接已断开，消息未发送'
      return false
    }
    const clientMessageId = options && options.clientMessageId ? String(options.clientMessageId) : ''
    const ok = sendRaw({
      type: 'message',
      content: text,
      ...(clientMessageId ? {client_message_id: clientMessageId} : {})
    })
    if (!ok) error.value = '消息发送失败，请重试'
    return ok
  }

  /** 主动关闭：之后不会自动重连。 */
  const close = () => {
    closedByUser = true
    clearTimers()
    attempt = 0
    dropSocket()
  }

  if (getCurrentScope()) {
    onScopeDispose(() => {
      disposed = true
      close()
    })
  }

  if (autoConnect) {
    connect()
  }

  return {
    connected,
    connecting,
    status,
    ticket,
    agentName,
    role,
    messages,
    error,
    send,
    connect,
    close
  }
}

export default useSupportSocket
