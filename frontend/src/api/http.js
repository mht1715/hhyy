/**
 * M3 普通 JSON 接口的 fetch 封装（记忆 / 转人工 / 客服工作台）。
 *
 * 为什么不用 utils/request.js（axios）：那个拦截器会对 401 直接清空 localStorage
 * 并跳首页、还会无条件 toast；而记忆页 / 客服台需要自己决定降级方式
 * （403 显示「仅客服与管理员可用」、404 显示空态、409 显示状态冲突）。
 *
 * 但还是照抄 api/chat.js 的 createHttpError + readErrorBody 思路：
 * 后端 4xx 返回 `{"detail": "..."}`，detail 可能是字符串也可能是对象，
 * 一律转成可读文本挂到 Error.message 上，绝不把 "[object Object]" 抛给用户。
 */

import {getToken} from '../utils/session'

const authToken = () => {
  try {
    return getToken()
  } catch (e) {
    return ''
  }
}

/** 任意 detail 值转可读文本。 */
export const toDetailText = (detail) => {
  if (detail === undefined || detail === null || detail === '') return ''
  if (typeof detail === 'string') return detail
  if (typeof detail === 'number' || typeof detail === 'boolean') return String(detail)
  try {
    return JSON.stringify(detail)
  } catch (e) {
    return String(detail)
  }
}

/** 非 2xx 时尽量把后端原文带出来；解析失败则降级为纯文本。 */
export const readErrorBody = async (response) => {
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
      const detail = body.detail !== undefined
        ? body.detail
        : (body.message !== undefined ? body.message : text)
      return {detail, message: toDetailText(detail)}
    }
  } catch (e) {
    // 不是 JSON，直接当作纯文本错误
  }

  return {detail: text, message: text}
}

/** 统一的 HTTP 错误对象：status / detail / code 供调用方按需判断。 */
export const createHttpError = (status, detail, message, code) => {
  const text = message || toDetailText(detail) || `请求失败（HTTP ${status}）`
  const error = new Error(text)
  error.status = status
  error.detail = detail === undefined ? null : detail
  if (code !== undefined) error.code = code
  return error
}

/**
 * 发起一个普通 JSON 请求，并剥掉 `{code, message, data}` 外壳。
 *
 * @param {string} path 以 /api 开头的绝对路径
 * @param {{method?: string, body?: any, headers?: object, signal?: AbortSignal}} options
 * @returns {Promise<any>} 响应里的 data（没有 data 字段时返回整个 body）
 */
export async function requestJson(path, options = {}) {
  const {
    method = 'GET',
    body,
    headers = {},
    signal
  } = options

  const token = authToken()
  const finalHeaders = {
    Accept: 'application/json',
    ...headers
  }
  if (body !== undefined) finalHeaders['Content-Type'] = 'application/json'
  if (token) finalHeaders.Authorization = `Bearer ${token}`

  let response
  try {
    response = await fetch(path, {
      method,
      headers: finalHeaders,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal
    })
  } catch (e) {
    if (e && e.name === 'AbortError') throw e
    const error = new Error('网络异常，请稍后重试')
    error.status = 0
    error.detail = null
    error.cause = e
    throw error
  }

  if (!response.ok) {
    const {detail, message} = await readErrorBody(response)
    throw createHttpError(response.status, detail, message)
  }

  if (response.status === 204) return null

  let payload = null
  try {
    payload = await response.json()
  } catch (e) {
    // 空响应体（例如 200 无内容）按 null 处理
    return null
  }

  if (payload && typeof payload === 'object' && payload.code !== undefined) {
    if (Number(payload.code) !== 200) {
      throw createHttpError(
        Number(payload.code) || response.status,
        payload.detail !== undefined ? payload.detail : payload.message,
        payload.message,
        payload.code
      )
    }
    return payload.data !== undefined ? payload.data : payload
  }

  return payload && payload.data !== undefined ? payload.data : payload
}

export default {requestJson, createHttpError, readErrorBody, toDetailText}
