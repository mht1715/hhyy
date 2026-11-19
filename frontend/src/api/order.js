import request from '../utils/request'

export const checkoutApi = (data) => request.post('/orders/checkout', data)
export const getMyOrdersApi = () => request.get('/orders')
export const getOrderDetailApi = (id) => request.get(`/orders/${id}`)
export const cancelOrderApi = (id) => request.put(`/orders/${id}/cancel`)
export const receiveOrderApi = (id) => request.put(`/orders/${id}/receive`)
export const shipOrderApi = (id) => request.put(`/orders/${id}/ship`)
// 管理员：全部订单列表 / 计数摘要（之前后台没有「看全部订单」的入口）
export const getAdminOrdersApi = (params) => request.get('/orders/admin/all', {params})
export const getAdminOrderSummaryApi = () => request.get('/orders/admin/summary')