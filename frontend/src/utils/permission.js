/**
 * 角色 / 路由权限判断的单一实现。
 *
 * 之前的问题（PRD G9）：路由守卫只判断 meta.roles，而 /admin、/doctor、/patient
 * 用的是 meta.role，导致任意已登录用户都能直接访问后台页面。
 *
 * 这里统一支持两种写法：
 *   meta: { requiresAuth: true, role: 'admin' }
 *   meta: { requiresAuth: true, roles: ['admin', 'doctor'] }
 */

/** 各角色的默认落地页。新增 support 路由时在这里补一行即可。 */
export const homePathByRole = {
  admin: '/admin',
  doctor: '/doctor',
  patient: '/patient'
}

/**
 * 从路由 meta 中解析出允许访问的角色列表。
 * @returns {string[]|null} null 表示该路由不限制角色
 */
export function allowedRoles(meta = {}) {
  if (Array.isArray(meta.roles) && meta.roles.length > 0) return meta.roles
  if (typeof meta.role === 'string' && meta.role) return [meta.role]
  return null
}

/** 当前角色能否访问该路由。 */
export function canAccess(role, meta = {}) {
  const roles = allowedRoles(meta)
  if (!roles) return true
  return roles.includes(role)
}

/** 角色对应的默认落地页，未知角色回首页。 */
export function resolveHomePath(role) {
  return homePathByRole[role] || '/'
}

export default { allowedRoles, canAccess, resolveHomePath, homePathByRole }
