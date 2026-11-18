/**
 * 登录态存储（M3 联调修复）。
 *
 * 为什么「sessionStorage 优先」：
 * - `localStorage` 是整个浏览器共享的。同一个浏览器开两个标签页分别登录 patient / support 时，
 *   后登录的会把前一个顶掉——演示「患者 ↔ 坐席」时两边变成同一个身份，
 *   于是所有消息都显示成同一方发的（看起来就像「客服消息没有客服标识」）。
 * - `sessionStorage` 按标签页隔离：一个标签页患者、另一个标签页客服，互不影响；
 *   同时仍然写 `localStorage`，新标签页默认继承「最近一次登录」，不至于每个标签页都要重新登录。
 */

const TOKEN_KEY = 'token'
const ROLE_KEY = 'role'
const USER_KEY = 'username'

const read = (key) => {
  try {
    return sessionStorage.getItem(key) || localStorage.getItem(key) || ''
  } catch (e) {
    return ''
  }
}

const write = (key, value) => {
  try {
    sessionStorage.setItem(key, value)
  } catch (e) {
    // 隐私模式 / 存储被禁用：忽略
  }
  try {
    localStorage.setItem(key, value)
  } catch (e) {
    // 忽略
  }
}

export const getToken = () => read(TOKEN_KEY)
export const getRole = () => read(ROLE_KEY)
export const getUsername = () => read(USER_KEY)

/** 登录成功后统一写入两处。 */
export const setAuth = ({token, role, username} = {}) => {
  write(TOKEN_KEY, token || '')
  write(ROLE_KEY, role || '')
  write(USER_KEY, username || '')
}

/** 退出登录：清掉当前标签页和浏览器级的登录态。 */
export const clearAuth = () => {
  for (const store of [sessionStorage, localStorage]) {
    try {
      store.removeItem(TOKEN_KEY)
      store.removeItem(ROLE_KEY)
      store.removeItem(USER_KEY)
    } catch (e) {
      // 忽略
    }
  }
}

export default {getToken, getRole, getUsername, setAuth, clearAuth}
