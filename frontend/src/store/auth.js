import {defineStore} from 'pinia'
import {loginApi} from '../api/auth'
import {useCartStore} from './cart'
import {clearAuth, getRole, getToken, getUsername, setAuth} from '../utils/session'

export const useAuthStore = defineStore('auth', {
    state: () => ({
        // 优先本标签页的登录态：同一浏览器两个标签页可以分别是患者 / 客服
        token: getToken(),
        username: getUsername(),
        role: getRole(),
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
            this.isLoginModalOpen = false // 登录成功自动关闭弹窗
            setAuth({token: this.token, role: this.role, username: this.username})
            // 登录成功后，立刻拉取购物车。
            // 但购物车只是附属数据：客服这类没有购物车的角色会 403，
            // 不能因此把「登录成功」变成「切换失败」（M3 踩过：客服根本进不去工作台）
            try {
                const cartStore = useCartStore()
                await cartStore.fetchCart()
            } catch (e) {
                // 忽略：购物车拉不到不影响登录态
            }
        },
        logout() {
            this.token = ''
            this.username = ''
            this.role = ''
            clearAuth()
            // 退出登录后，清空本地的购物车展示
            const cartStore = useCartStore()
            cartStore.$reset()
        }
    }
})