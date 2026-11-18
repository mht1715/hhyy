/**
 * M2 对话 API（契约见 docs/接口契约-M2.md）。
 *
 * 这里不走 utils/request.js：SSE 必须拿到原生 Response 的 body 流，
 * 而 axios 会把响应整体读完再返回，且拦截器会把 res.data 剥掉。
 * 因此流式对话与 Agent 列表都用原生 fetch，鉴权头手动补。
 */

let agentsCache = null
// 同时发起的列表请求合并成一次，避免 @ 候选与广场各拉一遍
let agentsRequest = null

const getToken = () => {
  try {
    return localStorage.getItem('token') || ''
  } catch (e) {
    return ''
  }
}

const toDetailText = (detail) => {
  if (!detail) return ''
  if (typeof detail === 'string') return detail
  try {
    return JSON.stringify(detail)
  } catch (e) {
    return String(detail)
  }
}

// 非 2xx 时后端返回普通 JSON（detail 可能是字符串或对象），尽量把原文带出来
const readErrorBody = async (response) => {
  let text = ''
  try {
    text = await response.text()
  } catch (e) {
    return {detail: '', message: ''}
  }
  if (!text) return {detail: '', message: ''}

  try {
    const body = JSON.parse(text)
    if (body && typeof body === 'object') {
      const detail = body.detail !== undefined ? body.detail : body.message
      return {
        detail: detail !== undefined ? detail : text,
        message: toDetailText(detail)
      }
    }
  } catch (e) {
    // 不是 JSON，直接当作纯文本错误
  }

  return {detail: text, message: text}
}

const createHttpError = (status, detail, message) => {
  const text = message || toDetailText(detail) || `请求失败（HTTP ${status}）`
  const error = new Error(text)
  error.status = status
  error.detail = detail === undefined ? null : detail
  return error
}

/**
 * 发起流式对话请求。
 * @param {object} payload 契约里的请求体
 * @param {{signal?: AbortSignal}} options
 * @returns {Promise<Response>} 交给我们自己的 useSSE 解析
 */
export async function streamChat(payload, {signal} = {}) {
  const token = getToken()
  const headers = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream'
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  const response = await fetch('/api/chat/stream', {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
    signal
  })

  if (!response.ok) {
    const {detail, message} = await readErrorBody(response)
    throw createHttpError(response.status, detail, message)
  }

  return response
}

/**
 * Agent 广场 / @ 候选用的列表。
 * 模块级缓存，force=true 时强刷一次。
 * @param {boolean} force
 * @returns {Promise<Array>}
 */
export async function fetchAgents(force = false) {
  if (!force && agentsCache) return agentsCache
  if (!force && agentsRequest) return agentsRequest

  const token = getToken()
  const request = (async () => {
    const response = await fetch('/api/agents?visible=1', {
      headers: {
        Accept: 'application/json',
        ...(token ? {Authorization: `Bearer ${token}`} : {})
      }
    })

    if (!response.ok) {
      const {detail, message} = await readErrorBody(response)
      throw createHttpError(response.status, detail, message)
    }

    const body = await response.json()
    // 兼容 {code, message, data:[...]} 与直接返回数组两种形状
    const list = Array.isArray(body) ? body : (Array.isArray(body?.data) ? body.data : [])
    agentsCache = list
    return list
  })()

  agentsRequest = request
  try {
    return await request
  } finally {
    if (agentsRequest === request) agentsRequest = null
  }
}
