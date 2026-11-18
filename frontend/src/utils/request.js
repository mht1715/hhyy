import axios from 'axios'
import {showToast} from 'vant'
import {clearAuth, getToken} from './session'

const request = axios.create({
    baseURL: '/api',
    timeout: 30000 // AI 解析可能较慢，超时时间设长点
})

// 请求拦截器
request.interceptors.request.use(
    (config) => {
        const token = getToken()
        if (token) {
            config.headers.Authorization = `Bearer ${token}`
        }
        return config
    },
    (error) => Promise.reject(error)
)

// 响应拦截器
request.interceptors.response.use(
    (response) => {
        const res = response.data
        // 如果后端返回了 code 且不是 200，说明业务报错
        if (res.code && res.code !== 200) {
            showToast({type: 'fail', message: res.message || '请求失败'})
            return Promise.reject(new Error(res.message || 'Error'))
        }
        // 直接把最核心的 data 剥出来给业务层
        return res.data !== undefined ? res.data : res
    },
    (error) => {
        // HTTP 层报错（如 401, 404, 500）
        const msg = error.response?.data?.detail || error.response?.data?.message || '网络异常，请稍后再试'
        showToast({type: 'fail', message: msg})

        if (error.response?.status === 401) {
            clearAuth()
            // 延迟跳转，让 toast 显示完
            setTimeout(() => {
                window.location.href = '/'
            }, 1500)
        }
        return Promise.reject(new Error(msg))
    }
)

export default request