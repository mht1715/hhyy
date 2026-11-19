/**
 * M5 工作台聚合接口。
 *
 * 三个接口都返回「原始数字」而不是格式化好的文案：前端统一负责 `%`、`¥`、`ms`
 * 的显示，避免同一个指标在两个页面出现两种写法。
 */

import {requestJson} from './http'

/**
 * GET /api/me/workbench —— 患者 / 医生 / 客服的「我的」概览。
 * @returns {Promise<{role, role_label, user, stats, recent_conversations,
 *   recent_orders, ticket, memory, generated_at}>}
 */
export const fetchMyWorkbench = () => requestJson('/api/me/workbench')

/**
 * GET /api/public/stats —— 游客落地页的真实数字（无需登录）。
 * @returns {Promise<{kb: {libraries, documents, chunks}, agents, eval, generated_at}>}
 */
export const fetchPublicStats = () => requestJson('/api/public/stats')

/**
 * GET /api/support/stats —— 坐席视角的队列与接待（24h 窗口）。
 * @returns {Promise<{accepted, resolved, queued, avg_wait_seconds, max_wait_seconds}>}
 */
export const fetchSupportStats = () => requestJson('/api/support/stats')

/**
 * GET /api/admin/observe/system —— 依赖状态 + 配置快照（仅管理员）。
 */
export const fetchSystemStatus = () => requestJson('/api/admin/observe/system')

export default {fetchMyWorkbench, fetchPublicStats, fetchSupportStats, fetchSystemStatus}
