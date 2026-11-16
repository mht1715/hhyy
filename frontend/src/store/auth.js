import {defineStore} from 'pinia'
import {loginApi} from '../api/auth'

export const useAuthStore = defineStore('auth', {
    state: () => ({
        token: localStorage.getItem('token') || '',
        username: localStorage.getItem('username') || '',
        role: localStorage.getItem('role') || '',
        isLoginModalOpen: false // 新增：控制登录弹窗显隐
    }),
    getters: {
        isLoggedIn: (state) => !!state.token
    },
    actions: {
        async login(username, password = '123456') {
            const res = await loginApi(username, password)
            this.token = res.access_token
            this.username = res.username
            this.role = res.role
            localStorage.setItem('token', this.token)
            localStorage.setItem('username', this.username)
            localStorage.setItem('role', this.role)
            this.isLoginModalOpen = false // 登录成功自动关闭弹窗
        },
        logout() {
            this.token = ''
            this.username = ''
            this.role = ''
            localStorage.clear()
        }
    }
})