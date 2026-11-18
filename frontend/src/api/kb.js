import request from '../utils/request'

/**
 * 知识库后台 API（后端前缀 /api，request.js 已处理 baseURL 与鉴权）。
 *
 * 注意：集合路由（列表 / 新建）后端声明为 "/"，这里统一带上尾斜杠，
 * 避免 FastAPI 的 307 重定向在 Vite 代理（changeOrigin=true）下把请求
 * 跳到后端地址、丢掉 Authorization 头。与 api/product.js 的写法保持一致。
 */

// ---------------------------------------------------------------- 知识库
export const getKbListApi = () => request.get('/admin/kb/')
export const getKbStatsApi = () => request.get('/admin/kb/stats')
export const getKbDetailApi = (id) => request.get(`/admin/kb/${id}`)
export const createKbApi = (data) => request.post('/admin/kb/', data)
export const updateKbApi = (id, data) => request.put(`/admin/kb/${id}`, data)
export const deleteKbApi = (id) => request.delete(`/admin/kb/${id}`)

// ---------------------------------------------------------------- 文档
export const getKbDocumentsApi = (id) => request.get(`/admin/kb/${id}/documents`)

// multipart/form-data：字段为 file / url / text 之一，另有 title、effective_from、effective_to
// 不要手动设置 Content-Type，交给浏览器生成 boundary
export const uploadKbDocumentApi = (id, formData) =>
    request.post(`/admin/kb/${id}/documents`, formData)

export const reindexKbDocumentApi = (id, docId) =>
    request.post(`/admin/kb/${id}/documents/${docId}/reindex`)

export const retryKbDocumentApi = (id, docId) =>
    request.post(`/admin/kb/${id}/documents/${docId}/retry`)

export const deleteKbDocumentApi = (id, docId) =>
    request.delete(`/admin/kb/${id}/documents/${docId}`)

// ---------------------------------------------------------------- 分段
export const getKbChunksApi = (id, docId) =>
    request.get(`/admin/kb/${id}/documents/${docId}/chunks`)

export const updateKbChunkApi = (id, chunkId, data) =>
    request.put(`/admin/kb/${id}/chunks/${chunkId}`, data)

// ---------------------------------------------------------------- 权限矩阵
export const getKbPermissionsApi = () => request.get('/admin/kb/permissions')
// 后端按全量覆盖处理：只传 can_read 为 true 的项
export const updateKbPermissionsApi = (id, permissions) =>
    request.put(`/admin/kb/${id}/permissions`, {permissions})

// ---------------------------------------------------------------- 检索测试台
export const searchTestApi = (kbId, data) =>
    request.post(`/admin/kb/${kbId}/search-test`, data)
