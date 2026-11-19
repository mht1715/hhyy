/**
 * 结算清单：从「要买哪几件」到「结算页展示什么、下单提交什么」的唯一来源。
 *
 * 之前的实现（M5 之前）在 sessionStorage 里只存了一串购物车行 id，
 * 结算页再拿这串 id 去 `useCartStore().items` 里过滤。三个入口各写一遍，
 * 结果就是三处都能出错：
 *
 *   1. 患者工作台的「去结算」忘了写这个 key → 结算页 ``[]`` → 显示「没有要结算的商品」；
 *   2. 结算页的 store 还没 fetch 完，过滤结果天然是空（刷新一下又能进）；
 *   3. 旧 id 残留在 sessionStorage 里，和后端购物车对不上，怎么点都是空。
 *
 * 现在改成存「快照」：一件商品一行（商品 id / 名称 / 规格 / 单价 / 数量 / 图片），
 * 结算页不依赖任何 store 就能渲染，刷新也还在。两个 key 互斥（购物车结算 vs 立即购买）
 * 由本文件负责清对手，调用方不需要记得清。
 */

const ITEMS_KEY = 'checkout_items'
const DIRECT_KEY = 'direct_buy_item'

const readJson = (key) => {
  try {
    const raw = window.sessionStorage.getItem(key)
    return raw ? JSON.parse(raw) : null
  } catch (e) {
    // 隐私模式 / 存储被禁用 / 旧版本写进去的脏 JSON：一律当成「没有清单」
    return null
  }
}

const writeJson = (key, value) => {
  try {
    window.sessionStorage.setItem(key, JSON.stringify(value))
  } catch (e) {
    // 存不进去就靠结算页的兜底（整车结算）继续走，不让结算入口直接失效
  }
}

const removeKey = (key) => {
  try {
    window.sessionStorage.removeItem(key)
  } catch (e) {
    // 忽略
  }
}

/**
 * 把购物车行 / 商品对象收敛成结算行。
 * @returns {object|null} 缺 product_id 的（已下架、脏数据）直接返回 null 由调用方过滤
 */
export const toCheckoutItem = (row) => {
  if (!row || !row.product_id) return null
  const quantity = Math.floor(Number(row.quantity))
  return {
    // 购物车行 id：用来和最新购物车对照，立即购买没有这个 id
    id: row.id ? String(row.id) : '',
    product_id: String(row.product_id),
    name: row.name || '',
    spec: row.spec || '',
    price: Number(row.price) || 0,
    quantity: Number.isFinite(quantity) && quantity > 0 ? quantity : 1,
    image_url: row.image_url || ''
  }
}

export const normalizeCheckoutItems = (rows) =>
    (Array.isArray(rows) ? rows.map(toCheckoutItem).filter(Boolean) : [])

/** 结算合计。前端只用于展示，真正的金额以后端下单结果为准。 */
export const checkoutTotal = (rows) =>
    normalizeCheckoutItems(rows).reduce((sum, item) => sum + item.price * item.quantity, 0)

/** 写入「购物车结算」清单，并清掉「立即购买」的残留，避免串单。 */
export const writeCheckoutItems = (rows) => {
  const items = normalizeCheckoutItems(rows)
  writeJson(ITEMS_KEY, items)
  removeKey(DIRECT_KEY)
  return items
}

/**
 * 读取购物车结算清单。
 * 旧版本存的是 id 字符串数组，这里会整体过滤成空数组——调用方据此退回「整车结算」，
 * 比把一串对不上的 id 当成商品渲染要好。
 */
export const readCheckoutItems = () => normalizeCheckoutItems(readJson(ITEMS_KEY))

/** 写入「立即购买」清单（单品），并清掉购物车结算的残留。 */
export const writeDirectItem = (row) => {
  const item = toCheckoutItem(row)
  if (item) writeJson(DIRECT_KEY, item)
  removeKey(ITEMS_KEY)
  return item
}

export const readDirectItem = () => toCheckoutItem(readJson(DIRECT_KEY))

/** 下单成功后两个 key 一起清：结算清单的使命到此为止。 */
export const clearCheckout = () => {
  removeKey(ITEMS_KEY)
  removeKey(DIRECT_KEY)
}

export default {
  toCheckoutItem,
  normalizeCheckoutItems,
  checkoutTotal,
  writeCheckoutItems,
  readCheckoutItems,
  writeDirectItem,
  readDirectItem,
  clearCheckout
}
