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
    },
    {
        path: '/products',
        name: 'Products',
        component: () => import('../views/ProductView.vue'),
        meta: {requiresAuth: true, roles: ['admin', 'doctor']} // 允许的多个角色
    },
    {
        path: '/product/:id',
        name: 'ProductDetail',
        component: () => import('../views/ProductDetailView.vue'),
    },
    {
        path: '/checkout',
        name: 'Checkout',
        component: () => import('../views/CheckoutView.vue'),
        meta: {requiresAuth: true}
    },
    {
        path: '/service',
        name: 'Service',
        component: () => import('../views/ServiceView.vue'),
        meta: {requiresAuth: true}
    },
    {
        path: '/orders',
        name: 'Orders',
        component: () => import('../views/OrderView.vue'),
        meta: {requiresAuth: true}
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

    if (to.meta.requiresAuth && !token) {
        return next('/')
    }

    // 支持数组形式的角色校验
    if (to.meta.roles && !to.meta.roles.includes(role)) {
        if (role === 'admin') return next('/admin')
        if (role === 'doctor') return next('/doctor')
        if (role === 'patient') return next('/patient')
        return next('/')
    }

    next()
})

export default router