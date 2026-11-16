import axios from 'axios'

const request = axios.create({
    baseURL: '/api',
    timeout: 15000
})

// 请求拦截器：自动注入 Token
request.interceptors.request.use(
    (config) => {
        const token = localStorage.getItem('token')
        if (token) {
            config.headers.Authorization = `Bearer ${token}`
        }
        return config
    },
    (error) => Promise.reject(error)
)

// 响应拦截器：统一处理错误
request.interceptors.response.use(
    (response) => response.data,
    (error) => {
        if (error.response) {
            const {status, data} = error.response
            if (status === 401) {
                // Token 过期，清除缓存并跳转登录
                localStorage.clear()
                window.location.href = '/login'
            }
            return Promise.reject(new Error(data.detail || '请求失败'))
        }
        return Promise.reject(error)
    }
)

export default request