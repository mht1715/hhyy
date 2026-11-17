import request from '../utils/request'

export const checkoutApi = () => request.post('/orders/checkout')
export const getMyOrdersApi = () => request.get('/orders')