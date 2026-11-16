import request from '../utils/request'

export const loginApi = (username, password) => {
    const formData = new URLSearchParams()
    formData.append('username', username)
    formData.append('password', password)
    return request.post('/auth/login', formData)
}