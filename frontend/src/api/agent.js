import request from '../utils/request'

export const parseProductApi = (text) => request.post('/agent/parse-product', {text})