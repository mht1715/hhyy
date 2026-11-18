import {createRouter, createWebHistory} from 'vue-router'
import {canAccess, resolveHomePath} from '../utils/permission'

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
    // 知识库后台：/admin/kb/permissions 与 /admin/kb/search-test 必须排在
    // /admin/kb/:id 之前，否则会被 :id 动态段捕获。
    {
        path: '/admin/kb',
        name: 'KbList',
        component: () => import('../views/admin/KbListView.vue'),
        meta: {requiresAuth: true, role: 'admin'}
    },
    {
        path: '/admin/kb/permissions',
        name: 'KbPermissions',
        component: () => import('../views/admin/KbPermissionsView.vue'),
        meta: {requiresAuth: true, role: 'admin'}
    },
    {
        path: '/admin/kb/search-test',
        name: 'KbSearchTest',
        component: () => import('../views/admin/SearchTestView.vue'),
        meta: {requiresAuth: true, role: 'admin'}
    },
    {
        path: '/admin/kb/:id',
        name: 'KbDetail',
        component: () => import('../views/admin/KbDetailView.vue'),
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
    },
    {
        path: '/orders/:id',
        name: 'OrderDetail',
        component: () => import('../views/OrderDetailView.vue'),
        meta: {requiresAuth: true}
    }
]

const router = createRouter({
    history: createWebHistory(),
    routes
})

// 路由守卫：登录态 + 角色校验
// 同时支持 meta.role（单角色）与 meta.roles（多角色），判断逻辑收敛到 utils/permission
router.beforeEach((to) => {
    const token = localStorage.getItem('token')
    const role = localStorage.getItem('role') || ''

    if (to.meta.requiresAuth && !token) {
        return {path: '/', query: {redirect: to.fullPath}}
    }

    if (to.meta.requiresAuth && !canAccess(role, to.meta)) {
        const home = resolveHomePath(role)
        // 落到自己没有权限的页面会造成死循环，兜底回首页
        return home === to.path ? {path: '/'} : {path: home}
    }

    return true
})

export default router