/**
 * M4 观测看板接口（契约见 docs/接口契约-M4.md §1）。
 *
 * 两个接口都是只读聚合，走普通 JSON（不是 SSE）；错误统一抛 Error
 * （error.status / error.detail），页面据此区分「仅管理员可用」与「稍后重试」。
 */

import {requestJson} from './http'

/**
 * GET /api/admin/observe/overview?days=7
 * @param {number} days 时间窗天数（7 / 14 / 30）
 * @returns {Promise<object>} totals / latency / quality / cost / guardrail / memory / agents / eval / links
 */
export const fetchOverview = (days = 7) => {
  const value = Number(days) || 7
  return requestJson(`/api/admin/observe/overview?days=${encodeURIComponent(String(value))}`)
}

/**
 * GET /api/admin/observe/recent?limit=20
 * @param {number} limit 返回条数
 * @returns {Promise<Array>} 最近若干轮对话（含 guardrail / feedback / trace_id）
 */
export const fetchRecent = (limit = 20) => {
  const value = Number(limit) || 20
  return requestJson(`/api/admin/observe/recent?limit=${encodeURIComponent(String(value))}`)
}

/**
 * GET /api/admin/observe/feedback/export?days=30&rating=down
 * 把差评导出成「评估集候选」：前端直接下载 JSON，人工确认后并进 golden set。
 * @returns {Promise<Array>} [{question, answer, agent_code, expected_docs, rating, reason, ...}]
 */
export const exportFeedback = (days = 30, rating = 'down') => {
  const d = Number(days) || 30
  const r = String(rating || 'down')
  return requestJson(
    `/api/admin/observe/feedback/export?days=${encodeURIComponent(String(d))}&rating=${encodeURIComponent(r)}`
  )
}

export default {fetchOverview, fetchRecent, exportFeedback}
