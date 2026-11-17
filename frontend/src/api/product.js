import request from '../utils/request'

export const getProductsApi = () => request.get('/products/')
export const createProductApi = (data) => request.post('/products/', data)
export const updateProductApi = (id, data) => request.put(`/products/${id}`, data)
export const deleteProductApi = (id) => request.delete(`/products/${id}`)
export const getProductDetailApi = (id) => request.get(`/products/${id}`)