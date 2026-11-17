import request from '../utils/request'

export const getCartApi = () => request.get('/cart')
export const addToCartApi = (product_id, quantity) => request.post('/cart', {product_id, quantity})
export const removeCartItemApi = (id) => request.delete(`/cart/${id}`)
export const clearCartApi = () => request.delete('/cart')
export const updateCartQuantityApi = (id, quantity) => request.put(`/cart/${id}`, {quantity})