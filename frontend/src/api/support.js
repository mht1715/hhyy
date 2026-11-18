/**
 * M3 转人工 / 客服工作台接口（契约见 docs/接口契约-M3.md §4 / §5）。
 *
 * 全部走普通 JSON（不是 SSE），错误统一抛 Error（error.status / error.detail），
 * 这样页面可以针对 401/403/409 做不同降级，而不是被 axios 拦截器直接跳首页。
 */

import {requestJson} from './http'

/* ------------------------------------------------------------------ *
 * 会话（§4）
 * ------------------------------------------------------------------ */

/**
 * GET /api/conversations —— 只返回自己的会话。
 * support/admin 传 {scope: 'all'} 可拿全部（工作台用）。
 * @param {{scope?: string}} options
 * @returns {Promise<Array>}
 */
export const fetchConversations = (options = {}) => {
  const scope = options && options.scope ? String(options.scope) : ''
  const query = scope ? `?scope=${encodeURIComponent(scope)}` : ''
  return requestJson(`/api/conversations${query}`)
}

/**
 * GET /api/conversations/{id} —— 会话详情 + 历史消息。
 * @param {string} id
 */
export const fetchConversation = (id) => (
  requestJson(`/api/conversations/${encodeURIComponent(String(id))}`)
)

/* ------------------------------------------------------------------ *
 * 转人工（§5.1 / §5.2）
 * ------------------------------------------------------------------ */

/**
 * POST /api/handoff —— 建单排队（游客 401；同一会话有活跃工单时幂等返回）。
 * @param {string} conversationId
 * @param {string} reason
 * @returns {Promise<{ticket_id: string, status: string, queue_position: number,
 *   queue_expires_in: number, reason: string, trigger: string, conversation_id: string}>}
 */
export const requestHandoff = (conversationId, reason = '') => (
  requestJson('/api/handoff', {
    method: 'POST',
    body: {
      conversation_id: conversationId,
      ...(reason ? {reason} : {})
    }
  })
)

/**
 * POST /api/handoff/offline —— 90s 无人接管后提交留言。
 * @param {{conversation_id: string, name?: string, contact?: string, demand?: string}} payload
 * @returns {Promise<{ticket_id: string, status: string, saved: boolean}>}
 */
export const submitOfflineMessage = (payload) => (
  requestJson('/api/handoff/offline', {
    method: 'POST',
    body: payload || {}
  })
)

/* ------------------------------------------------------------------ *
 * 坐席接口（§5.3 / §5.4）
 * ------------------------------------------------------------------ */

/**
 * GET /api/support/tickets?status=queued,assigned
 * 不传 status 时后端默认返回 queued,assigned。
 * @param {string} status 逗号分隔的状态列表
 * @returns {Promise<Array>}
 */
export const fetchTickets = (status = '') => {
  const value = status ? String(status) : ''
  const query = value ? `?status=${encodeURIComponent(value)}` : ''
  return requestJson(`/api/support/tickets${query}`)
}

/**
 * POST /api/support/tickets/{id}/accept —— queued → assigned，会话 → human_active。
 * 非法流转返回 409 + detail。
 */
export const acceptTicket = (id) => (
  requestJson(`/api/support/tickets/${encodeURIComponent(String(id))}/accept`, {
    method: 'POST'
  })
)

/**
 * POST /api/support/tickets/{id}/resolve —— assigned → resolved，会话 → closed。
 */
export const resolveTicket = (id) => (
  requestJson(`/api/support/tickets/${encodeURIComponent(String(id))}/resolve`, {
    method: 'POST'
  })
)

/**
 * POST /api/support/tickets/{id}/messages —— 坐席发消息（落库 + 广播）。
 * WS 不可用时的降级通道。
 */
export const sendAgentMessage = (id, content) => (
  requestJson(`/api/support/tickets/${encodeURIComponent(String(id))}/messages`, {
    method: 'POST',
    body: {content}
  })
)

/**
 * POST /api/support/ws-ticket —— 先 HTTP 拿短期 ticket，再连 WS（JWT 不进 query string）。
 * @returns {Promise<{ws_ticket: string, expires_in: number, ws_url: string}>}
 */
export const createWsTicket = () => requestJson('/api/support/ws-ticket', {method: 'POST'})

export default {
  fetchConversations,
  fetchConversation,
  requestHandoff,
  submitOfflineMessage,
  fetchTickets,
  acceptTicket,
  resolveTicket,
  sendAgentMessage,
  createWsTicket
}
