import {computed, ref} from 'vue'
import {streamChat} from '../api/chat'
import {collectMentions} from './useMention'
import {streamEvents} from './useSSE'

const uuid = () => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `m-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

const normalizeMentions = (mentions) => (Array.isArray(mentions) ? mentions : [])
  .filter((mention) => mention && (mention.agent_code || mention.code))
  .map((mention) => ({
    agent_code: mention.agent_code || mention.code,
    name: mention.name || '',
    offset: Number.isInteger(mention.offset) ? mention.offset : 0
  }))

const createAssistantMessage = () => ({
  id: uuid(),
  role: 'assistant',
  content: '',
  status: 'streaming',
  mentions: [],
  agentsRunning: [],
  contributors: [],
  retrieval: [],
  tools: [],
  citations: [],
  handoff: null,
  usage: null,
  guardrail: null,
  suggestedActions: [],
  suggested_actions: [],
  route: null,
  replayed: false,
  stopped: false,
  error: null,
  conversationId: null,
  messageId: null,
  traceId: null,
  latencyMs: null
})

const normalizeInitialMessage = (item, index) => {
  const raw = item && typeof item === 'object' ? item : {content: String(item || '')}
  return {
    ...raw,
    id: raw.id || `init-${index}`,
    role: raw.role === 'user' ? 'user' : 'assistant',
    content: raw.content !== undefined ? raw.content : (raw.text !== undefined ? raw.text : ''),
    status: raw.status || 'done',
    mentions: raw.mentions || [],
    agentsRunning: raw.agentsRunning || [],
    contributors: raw.contributors || [],
    retrieval: raw.retrieval || [],
    tools: raw.tools || [],
    citations: raw.citations || []
  }
}

/**
 * 通用 Agent 会话状态机。
 *
 * send 负责把一轮对话的流事件落到最后一条 assistant 消息上；
 * 所有需要跨轮复用的状态（conversationId）都留在这里，
 * 组件只消费 messages / streaming / route。
 *
 * @param {{agentCode?: string, context?: object, initialMessages?: Array}} options
 */
export function useAgentChat({agentCode = 'drug_consult', context = null, initialMessages = []} = {}) {
  const buildInitialMessages = () => (Array.isArray(initialMessages) ? initialMessages : [])
    .map(normalizeInitialMessage)

  const messages = ref(buildInitialMessages())
  const streaming = ref(false)
  const error = ref(null)
  const route = ref(null)
  const conversationId = ref(null)
  const canSend = computed(() => !streaming.value)

  // 当前请求的 controller / 轮次令牌：stop 之后旧请求的 finally 不能影响新请求
  let controller = null
  let activeToken = null

  const upsertContributor = (message, contributor) => {
    if (!contributor || !contributor.code) return
    const index = message.contributors.findIndex((item) => item.code === contributor.code)
    if (index === -1) {
      message.contributors.push({
        code: contributor.code,
        name: contributor.name || contributor.code,
        summary: contributor.summary || ''
      })
      return
    }
    const previous = message.contributors[index]
    message.contributors[index] = {
      ...previous,
      ...contributor,
      summary: contributor.summary || previous.summary || ''
    }
  }

  const mergeContributors = (message, contributors) => {
    if (!Array.isArray(contributors)) return
    contributors.forEach((contributor) => upsertContributor(message, contributor))
  }

  const applyEvent = (index, eventName, data, signal) => {
    const message = messages.value[index]
    if (!message) return

    const payload = data && typeof data === 'object' ? data : {}
    const rawText = payload.raw !== undefined ? String(payload.raw) : ''

    switch (eventName) {
      case 'meta':
        if (payload.conversation_id) {
          conversationId.value = payload.conversation_id
          message.conversationId = payload.conversation_id
        }
        if (payload.message_id) message.messageId = payload.message_id
        if (payload.trace_id) message.traceId = payload.trace_id
        break

      case 'route':
        route.value = payload
        message.route = payload
        break

      case 'agent': {
        const code = payload.code || payload.agent_code
        if (!code) break
        const name = payload.name || code
        if (payload.phase === 'start') {
          if (!message.agentsRunning.some((agent) => agent.code === code)) {
            message.agentsRunning.push({code, name})
          }
        } else if (payload.phase === 'done') {
          message.agentsRunning = message.agentsRunning.filter((agent) => agent.code !== code)
          upsertContributor(message, {code, name, summary: payload.summary || ''})
        }
        break
      }

      case 'retrieval':
        message.retrieval.push(payload)
        break

      case 'tool':
        message.tools.push(payload)
        break

      case 'citation':
        if (payload.index !== undefined) {
          const existing = message.citations.findIndex((item) => item.index === payload.index)
          if (existing === -1) {
            message.citations.push(payload)
          } else {
            message.citations.splice(existing, 1, payload)
          }
        }
        break

      case 'delta':
        // 用户已点停止：即使还有残包在管道里，也不允许再追加 token
        if (signal.aborted) break
        if (typeof payload.text === 'string') {
          message.content += payload.text
        }
        break

      case 'handoff':
        message.handoff = payload
        break

      case 'done':
        message.status = 'done'
        if (payload.message_id) message.messageId = payload.message_id
        if (payload.trace_id) message.traceId = payload.trace_id
        if (payload.latency_ms !== undefined) message.latencyMs = payload.latency_ms
        if (payload.usage) message.usage = payload.usage
        if (payload.guardrail) message.guardrail = payload.guardrail
        // done 里的 citations 是权威列表（后端已按正文裁剪、且保留原序号）：
        // 直接的 citation 事件可能多发了「没被引用」的，以 done 为准整体替换
        if (Array.isArray(payload.citations)) {
          message.citations = payload.citations
        }
        mergeContributors(message, payload.contributors)
        if (Array.isArray(payload.suggested_actions)) {
          message.suggestedActions = payload.suggested_actions
          message.suggested_actions = payload.suggested_actions
        }
        if (payload.replayed) message.replayed = true
        break

      case 'error':
        error.value = payload.message || rawText || '生成失败，请稍后重试'
        message.status = 'error'
        message.error = {
          code: payload.code || 'stream_error',
          message: payload.message || rawText || '生成失败，请稍后重试',
          retryable: payload.retryable !== false
        }
        break

      default:
        // 未知事件忽略，保证协议向前兼容
        break
    }
  }

  const markStopped = (index, messageId) => {
    const message = messages.value[index]
    if (!message || message.id !== messageId || message.status !== 'streaming') return
    message.status = 'done'
    message.stopped = true
  }

  const markConnectionLost = (index, messageId) => {
    const message = messages.value[index]
    if (!message || message.id !== messageId || message.status !== 'streaming') return
    const text = '连接中断，回答可能不完整，请重试'
    message.status = 'error'
    message.error = {code: 'stream_closed', message: text, retryable: true}
    error.value = text
  }

  const runStream = async (userMessage) => {
    const token = Symbol('agent-chat-stream')
    activeToken = token
    error.value = null
    route.value = null

    const assistantIndex = messages.value.length
    const assistant = createAssistantMessage()
    const assistantId = assistant.id
    messages.value.push(assistant)
    streaming.value = true

    const localController = new AbortController()
    controller = localController
    const {signal} = localController

    const payload = {
      agent_code: agentCode || 'drug_consult',
      conversation_id: conversationId.value,
      client_message_id: uuid(),
      message: userMessage.content,
      mentions: userMessage.mentions || [],
      context: {
        product_id: null,
        order_id: null,
        ...(context && typeof context === 'object' ? context : {})
      }
    }

    let doneReceived = false
    let failed = false

    try {
      const response = await streamChat(payload, {signal})

      for await (const frame of streamEvents(response)) {
        if (signal.aborted) break

        applyEvent(assistantIndex, frame.event, frame.data, signal)

        if (frame.event === 'done') {
          doneReceived = true
          // done 是契约里的最后一帧，收到就可以收尾，不必等服务端断连
          break
        }
        if (frame.event === 'error') {
          failed = true
          break
        }
      }

      if (!signal.aborted && !failed && !doneReceived) {
        markConnectionLost(assistantIndex, assistantId)
      }
    } catch (e) {
      if (signal.aborted || (e && e.name === 'AbortError')) {
        markStopped(assistantIndex, assistantId)
      } else {
        const text = (e && e.message) || '网络异常，请稍后重试'
        error.value = text
        const message = messages.value[assistantIndex]
        if (message && message.id === assistantId) {
          message.status = 'error'
          message.error = {
            code: (e && e.status) || 'network_error',
            message: text,
            retryable: true
          }
        }
      }
    } finally {
      // stop() 已经切走了 activeToken，旧请求不再改新请求的状态
      if (activeToken === token) {
        const message = messages.value[assistantIndex]
        if (message && message.id === assistantId && message.status === 'streaming') {
          if (signal.aborted) {
            message.status = 'done'
            message.stopped = true
          } else if (!doneReceived && !message.error) {
            message.status = 'error'
            message.error = {
              code: 'stream_closed',
              message: '连接中断，回答可能不完整，请重试',
              retryable: true
            }
          }
        }
        streaming.value = false
        controller = null
        activeToken = null
      }
    }
  }

  /**
   * 发送一轮消息。
   * @param {string} text
   * @param {{mentions?: Array}} options
   */
  const send = (text, options = {}) => {
    if (streaming.value) return Promise.resolve()
    const value = typeof text === 'string' ? text : ''
    if (!value.trim()) return Promise.resolve()

    const mentions = collectMentions(value, normalizeMentions(options.mentions))
    const userMessage = {
      id: uuid(),
      role: 'user',
      content: value,
      mentions,
      createdAt: Date.now()
    }

    messages.value.push(userMessage)
    return runStream(userMessage)
  }

  /**
   * 中止当前生成：之后不会再追加任何 token。
   */
  const stop = () => {
    if (!controller) return
    controller.abort()
    controller = null
    activeToken = null
    streaming.value = false

    for (let i = messages.value.length - 1; i >= 0; i -= 1) {
      const message = messages.value[i]
      if (message.role === 'assistant') {
        if (message.status === 'streaming') {
          message.status = 'done'
          message.stopped = true
        }
        break
      }
    }
  }

  /**
   * 重试：保留最后一条用户消息，删掉它后面失败的 assistant 气泡后重发。
   */
  const retry = () => {
    if (streaming.value) return Promise.resolve()

    let userIndex = -1
    for (let i = messages.value.length - 1; i >= 0; i -= 1) {
      if (messages.value[i].role === 'user') {
        userIndex = i
        break
      }
    }
    if (userIndex === -1) return Promise.resolve()

    const userMessage = messages.value[userIndex]
    messages.value.splice(userIndex + 1)
    return runStream(userMessage)
  }

  const reset = () => {
    if (controller) controller.abort()
    controller = null
    activeToken = null
    streaming.value = false
    error.value = null
    route.value = null
    conversationId.value = null
    messages.value = buildInitialMessages()
  }

  return {
    messages,
    streaming,
    error,
    route,
    send,
    stop,
    retry,
    reset,
    canSend
  }
}
