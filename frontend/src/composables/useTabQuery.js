/**
 * 工作台 Tab ↔ `?tab=` 的双向同步（患者 / 医生工作台共用）。
 *
 * 为什么单独抽出来：这几个工作台都在 `App.vue` 的 KeepAlive 白名单里，切到别的角色后
 * 旧页面只是 **deactivated**，它的 `watch` 依然活着。之前的实际故障是：
 *
 *   医生工作台 → 顶栏切到患者 → 在患者页点「订单」Tab
 *   → 地址栏先变成 `/patient?tab=orders`
 *   → 后台那个被缓存的 DoctorView 也收到了 `route.query.tab` 变化，它不认识 `orders`，
 *     于是「把手改出来的非法值收敛掉」，把地址栏改成 `/patient`
 *   → 患者页的 `?tab` 变空，`active` 跟着回到 overview
 *
 * 用户看到的就是「点了没反应」，而且**刷新一下又好了**（刷新后 KeepAlive 是空的，
 * 没有第二个实例在后台改 URL）。所以这里立一条规矩：
 *
 * **只有「当前路由就是我这页」的实例才允许读写 `?tab=`；后台缓存的实例一律只看不动。**
 */
import {watch} from 'vue'
import {useRoute, useRouter} from 'vue-router'

/**
 * @param {object} options
 * @param {string} options.path     本页路由（'/patient' / '/doctor'），用来判断「我是不是当前页」
 * @param {string[]} options.tabs   合法的 tab key；不在列表里的一律落回 fallback
 * @param {string} options.fallback 默认 Tab（同时决定它要不要写进 URL）
 * @param {import('vue').Ref<string>} options.active 当前 Tab 的 ref
 * @param {boolean} [options.converge] 地址栏出现非法值时，是否顺手把它改成 fallback
 */
export function useTabQuery({path, tabs, fallback = 'overview', active, converge = false}) {
  const route = useRoute()
  const router = useRouter()

  // 关键守卫：被 KeepAlive 缓存的旧实例 route 已经指向别的页面了，不能动地址栏
  const ownsRoute = () => route.path === path

  const readRaw = () => {
    const raw = route.query.tab
    const value = Array.isArray(raw) ? raw[0] : raw
    return typeof value === 'string' ? value : ''
  }

  const readTab = () => {
    const raw = readRaw()
    return tabs.includes(raw) ? raw : fallback
  }

  const write = (key) => {
    if (!ownsRoute()) return
    const current = readRaw()
    // 默认 Tab 不写进 URL，地址栏干净一点
    const next = key === fallback ? '' : key
    if (current === next) return
    // 展开 route.query 是为了不冲掉别的参数（例如 AgentChat 自己维护的 ?c=）
    const query = {...route.query}
    if (next) query.tab = next
    else delete query.tab
    router.replace({query}).catch(() => {})
  }

  // Tab → URL
  watch(active, (key) => write(key))

  /**
   * 把当前 Tab 写回地址栏。被缓存的工作台重新激活时调一次：
   * 切角色的入口（顶栏「快捷切换账号」）都是 push 到不带参数的地址，
   * 组件里的 Tab 还是上次那个，URL 却是空的——刷新一下就丢位置了。
   */
  const sync = () => write(active.value)

  // URL → Tab（前进/后退、点了指标卡的 to、手改地址栏）
  watch(() => route.query.tab, () => {
    if (!ownsRoute()) return
    const raw = readRaw()
    if (!raw) {
      // 地址栏没带 tab：多半是「切角色回来」或顶栏点的 /patient。
      // 这时保留组件里原有的 Tab，并把它补回 URL——不要反过来把人打回概览。
      sync()
      return
    }
    const next = readTab()
    if (next !== active.value) {
      active.value = next
      return
    }
    if (converge && raw !== next) write(next)
  })

  return {readTab, write, sync, ownsRoute}
}

export default useTabQuery
