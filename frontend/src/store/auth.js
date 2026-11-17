import {defineStore} from 'pinia'
import {loginApi} from '../api/auth'
import {useCartStore} from './cart'

export const useAuthStore = defineStore('auth', {
    state: () => ({
        token: localStorage.getItem('token') || '',
        username: localStorage.getItem('username') || '',
        role: localStorage.getItem('role') || '',
        isLoginModalOpen: false
    }),
    getters: {
        isLoggedIn: (state) => !!state.token,
        isAdmin: (state) => state.role === 'admin',
        isDoctor: (state) => state.role === 'doctor',
        isPatient: (state) => state.role === 'patient',
        // 判断是否具备指定角色中的一个
        hasRole: (state) => (roles) => {
            if (!Array.isArray(roles)) return state.role === roles
            return roles.includes(state.role)
        }
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
            // 登录成功后，立刻拉取购物车
            const cartStore = useCartStore()
            await cartStore.fetchCart()
        },
        logout() {
            this.token = ''
            this.username = ''
            this.role = ''
            localStorage.clear()
            // 退出登录后，清空本地的购物车展示
            const cartStore = useCartStore()
            cartStore.$reset()
        }
    }
})