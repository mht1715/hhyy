import {createRouter, createWebHistory} from 'vue-router'

const routes = [
    {
        path: '/',
        name: 'VisitorHome',
        component: () => import('../views/HomeView.vue')
    },
    {
        path: '/admin',
        name: 'Admin',
        component: () => import('../views/AdminView.vue'),
        meta: {requiresAuth: true, role: 'admin'}
    },
    {
        path: '/doctor',
        name: 'Doctor',
        component: () => import('../views/DoctorView.vue'),
        meta: {requiresAuth: true, role: 'doctor'}
    },
    {
        path: '/patient',
        name: 'Patient',
        component: () => import('../views/PatientView.vue'),
        meta: {requiresAuth: true, role: 'patient'}
    }
]

const router = createRouter({
    history: createWebHistory(),
    routes
})

// 路由守卫：权限校验
router.beforeEach((to, from, next) => {
    const token = localStorage.getItem('token')
    const role = localStorage.getItem('role')

    // 如果需要登录，但没登录 -> 回首页（首页内置了登录弹窗）
    if (to.meta.requiresAuth && !token) {
        return next('/')
    }

    // 如果已登录，且访问的角色路由与当前角色不符 -> 重定向到其所属路由
    if (to.meta.role && to.meta.role !== role) {
        if (role === 'admin') return next('/admin')
        if (role === 'doctor') return next('/doctor')
        if (role === 'patient') return next('/patient')
        return next('/')
    }

    next()
})

export default router