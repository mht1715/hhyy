import {requestJson} from './http'

/**
 * 药品目录的公开只读接口（游客也能访问）。
 *
 * 为什么不复用 api/product.js 里的 utils/request（axios）：
 * 那个拦截器一旦收到 401 就会 clearAuth() 并整页跳回首页。药品广场是 C 端入口，
 * 游客逛的时候不该因为 token 过期被「踢」走；这里让页面自己决定失败怎么提示、
 * 是否降级。而且这两个接口本身就不需要登录，用 fetch 封装比 axios 更轻。
 */

/**
 * 拼查询串：空值直接跳过。
 * 否则会发出 `?keyword=&category=` 这种脏参数，后端虽然能处理，但日志和缓存都不好看。
 */
const toQuery = (params = {}) => {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null) return
    const text = String(value).trim()
    if (!text) return
    search.set(key, text)
  })
  const query = search.toString()
  return query ? `?${query}` : ''
}

/**
 * 药品广场列表。
 *
 * @param {{keyword?: string, category?: string, signal?: AbortSignal}} params
 *   keyword 同时匹配名称 / 通用名 / 适应症；category 传空串表示「全部」。
 *   signal 给页面的防抖搜索用：新一次输入开始时 abort 旧请求，避免旧结果后到覆盖新结果。
 * @returns {Promise<Array>} 药品数组
 */
export const listCatalogProducts = ({keyword = '', category = '', signal} = {}) =>
    requestJson(`/api/catalog/products${toQuery({keyword, category})}`, {signal})

/**
 * 分类枚举。
 *
 * 不前端硬编码分类：后台新增药品时可能带出新分类，硬编码会让新分类永远筛不出来。
 *
 * @param {{signal?: AbortSignal}} options
 * @returns {Promise<string[]>} 分类字符串数组
 */
export const listCatalogCategories = ({signal} = {}) =>
    requestJson('/api/catalog/categories', {signal})
