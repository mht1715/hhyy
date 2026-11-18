/**
 * M4 消息反馈接口（契约见 docs/接口契约-M4.md §3）。
 *
 * 只允许对「自己的」assistant 消息反馈：
 * - 403 不是自己的消息
 * - 404 消息不存在
 * - 400 重复提交或参数不合法
 * 因此这里不做重试，调用方按 status 给提示即可。
 */

import {requestJson} from './http'

/**
 * POST /api/chat/feedback
 * @param {{messageId: string, rating: 'up'|'down', reason?: string}} payload
 * @returns {Promise<{recorded: boolean, message_id: string, rating: string}>}
 */
export const sendFeedback = ({messageId, rating, reason} = {}) => {
  const body = {
    message_id: messageId,
    rating
  }
  // reason 只对 👎 有意义，空字符串不传（后端按「未填原因」处理）
  const detail = reason === undefined || reason === null ? '' : String(reason).trim()
  if (detail) body.reason = detail
  return requestJson('/api/chat/feedback', {method: 'POST', body})
}

export default {sendFeedback}
