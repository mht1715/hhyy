/**
 * 页面返回的统一实现。
 *
 * 之前的写法有两种，都有坑：
 * - `router.back()`：直接打开链接 / 新标签页打开时 history 里没有上一条，
 *   会把用户送出站外（或者什么都没发生）；
 * - `router.push('/agents')`：不管从哪来都固定跳一个页面，从药品详情进客服台
 *   再返回，就永远回不到药品详情。
 *
 * Vue Router 会把来源写进 `history.state.back`（刷新后仍然在），
 * 所以优先 back()，只有真的没有来源时才落到调用方给的兜底页。
 */

/** 当前页是否有可返回的上一条记录。 */
export const hasHistoryBack = (currentPath) => {
  if (typeof window === 'undefined') return false
  const state = window.history.state || {}
  if (!state.back) return false
  // 同一路径的 back 是 no-op（例如 replace 过 query），当成没有
  if (currentPath && state.back === currentPath) return false
  return true
}

/**
 * 返回上一页；没有上一条时跳到 fallback。
 * @returns {'back'|'push'} 实际走了哪条分支（方便测试与埋点）
 */
export const goBackOr = (router, fallback = '/') => {
  const current = router.currentRoute && router.currentRoute.value ? router.currentRoute.value.fullPath : ''
  if (hasHistoryBack(current)) {
    router.back()
    return 'back'
  }
  router.push(fallback)
  return 'push'
}

export default {hasHistoryBack, goBackOr}
