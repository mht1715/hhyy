import {useAuthStore} from '../store/auth'

export const permission = {
    mounted(el, binding) {
        const auth = useAuthStore()
        // 获取指令绑定的值，比如 v-permission="['admin', 'doctor']" 或 v-permission="'admin'"
        const requiredRoles = binding.value

        if (!requiredRoles) return

        // 判断是否有权限
        let hasPermission = false
        if (Array.isArray(requiredRoles)) {
            hasPermission = requiredRoles.includes(auth.role)
        } else {
            hasPermission = auth.role === requiredRoles
        }

        // 如果没有权限，直接从 DOM 树中移除该元素
        if (!hasPermission) {
            el.parentNode && el.parentNode.removeChild(el)
        }
    }
}