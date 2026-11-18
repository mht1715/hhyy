/**
 * M4 Prompt 模板接口（契约见 docs/接口契约-M4.md §2）。
 *
 * 版本模型：同一个 code 下每个 version 一行，status ∈ draft|testing|production|archived，
 * rollout 是 0~100 的灰度百分比。**把某个版本 PUT 成 status:"production" 就是上线 / 回滚**，
 * 后端会自动把同 code 的其它 production 归档。
 */

import {requestJson} from './http'

/**
 * GET /api/admin/prompts?code=xxx —— 不传 code 时返回全部版本。
 * @param {string} code 可选，按 code 过滤
 * @returns {Promise<Array>} PromptTemplateOut[]
 */
export const listPrompts = (code = '') => {
  const value = code ? String(code) : ''
  const query = value ? `?code=${encodeURIComponent(value)}` : ''
  return requestJson(`/api/admin/prompts${query}`)
}

/**
 * POST /api/admin/prompts —— 新建版本（不传 version 时后端自动 +1）。
 * @param {{code: string, content: string, version?: number, status?: string,
 *   labels?: string[], rollout?: number, model?: string, variables_schema?: object}} payload
 * @returns {Promise<object>} 新建出来的版本
 */
export const createPrompt = (payload) => (
  requestJson('/api/admin/prompts', {
    method: 'POST',
    body: payload || {}
  })
)

/**
 * PUT /api/admin/prompts/{id} —— 只传要改的字段。
 * status 传 "production" 即上线 / 回滚（同 code 其它 production 会被归档）。
 * @param {string} id
 * @param {{content?: string, status?: string, labels?: string[], rollout?: number, model?: string}} payload
 * @returns {Promise<object>} 更新后的版本
 */
export const updatePrompt = (id, payload) => (
  requestJson(`/api/admin/prompts/${encodeURIComponent(String(id))}`, {
    method: 'PUT',
    body: payload || {}
  })
)

/**
 * POST /api/admin/prompts/{id}/preview —— 渲染模板，不落库。
 * @param {string} id
 * @param {object} variables 变量名 → 值
 * @returns {Promise<{rendered: string, missing: string[], used: string[]}>}
 */
export const previewPrompt = (id, variables) => (
  requestJson(`/api/admin/prompts/${encodeURIComponent(String(id))}/preview`, {
    method: 'POST',
    body: {variables: variables && typeof variables === 'object' ? variables : {}}
  })
)

/**
 * GET /api/admin/prompts/{code}/resolve?user_key=xxx —— 演示灰度命中哪一版。
 * @param {string} code
 * @param {string} userKey 任意字符串（按 hash 落桶）
 * @returns {Promise<{code: string, version: number, status: string, rollout: number, reason: string}>}
 */
export const resolvePrompt = (code, userKey) => (
  requestJson(
    `/api/admin/prompts/${encodeURIComponent(String(code))}/resolve?user_key=${encodeURIComponent(String(userKey || ''))}`
  )
)

export default {listPrompts, createPrompt, updatePrompt, previewPrompt, resolvePrompt}
