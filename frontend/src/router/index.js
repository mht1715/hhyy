import {createRouter, createWebHistory} from 'vue-router'
import {canAccess, resolveHomePath} from '../utils/permission'
import {getRole, getToken} from '../utils/session'

const routes = [
    {
        path: '/',
        name: 'VisitorHome',
        component: () => import('../views/HomeView.vue')
    },
    // Agent 广场与通用对话：公开页面，游客也可访问
    {
        path: '/agents',
        name: 'Agents',
        component: () => import('../views/AgentsView.vue')
    },
    {
        path: '/agents/:code',
        name: 'AgentChat',
        component: () => import('../views/AgentChatView.vue')
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
    // M3：记忆管理（登录即可，游客 401 由守卫拦截）
    {
        path: '/me/memory',
        name: 'Memory',
        component: () => import('../views/MemoryView.vue'),
        meta: {requiresAuth: true}
    },
    // M3：客服工作台（仅 support / admin）
    {
        path: '/support',
        name: 'Support',
        component: () => import('../views/SupportView.vue'),
        meta: {requiresAuth: true, roles: ['support', 'admin']}
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
    // 与 store / api 用同一套读取顺序（本标签页优先），避免「store 已登录、守卫说没登录」
    const token = getToken()
    const role = getRole()

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