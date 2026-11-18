import request from '../utils/request'

export const checkoutApi = (data) => request.post('/orders/checkout', data)
export const getMyOrdersApi = () => request.get('/orders')
export const getOrderDetailApi = (id) => request.get(`/orders/${id}`)
export const cancelOrderApi = (id) => request.put(`/orders/${id}/cancel`)
export const receiveOrderApi = (id) => request.put(`/orders/${id}/receive`)
export const shipOrderApi = (id) => request.put(`/orders/${id}/ship`)