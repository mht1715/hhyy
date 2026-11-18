/**
 * M3 记忆接口（契约见 docs/接口契约-M3.md §3）。
 *
 * 所有读写都由后端按 token 里的 user_id 过滤，前端不传 user_id。
 * 错误统一抛 Error（error.status / error.detail），调用方 toast 即可。
 */

import {requestJson} from './http'

/**
 * GET /api/me/memory
 * @returns {Promise<{enabled: boolean, profile: object, items: Array, stats: object}>}
 */
export const fetchMemory = () => requestJson('/api/me/memory')

/**
 * DELETE /api/me/memory/{id}
 * 只删自己的；别人的 id 返回 deleted:false（后端不区分「不存在」与「不是你的」）。
 * @param {string} id
 * @returns {Promise<{deleted: boolean}>}
 */
export const deleteMemory = (id) => (
  requestJson(`/api/me/memory/${encodeURIComponent(String(id))}`, {method: 'DELETE'})
)

/**
 * DELETE /api/me/memory —— 一键清空（含语义记忆向量）。
 * @returns {Promise<{deleted: number}>}
 */
export const clearMemory = () => requestJson('/api/me/memory', {method: 'DELETE'})

/**
 * PATCH /api/me/memory
 * 关闭后不再写入新记忆、也不再注入 prompt；历史条目保留。
 * @param {boolean} enabled
 * @returns {Promise<{enabled: boolean}>}
 */
export const setMemoryEnabled = (enabled) => (
  requestJson('/api/me/memory', {
    method: 'PATCH',
    body: {enabled: !!enabled}
  })
)

export default {fetchMemory, deleteMemory, clearMemory, setMemoryEnabled}
