/**
 * 订单状态文案与动作可用性（单一实现）。
 *
 * 后端的 OrderStatus 是小写；「paid」在这里表示「已付款、待发货」，
 * 不是「已发货」——三个页面（OrderView / 患者工作台 / 管理员订单管理）
 * 都从这里取，避免同一个状态在不同页面写成两个词。
 */

export const ORDER_STATUS_META = {
  pending: {label: '待付款', tone: 'warn'},
  paid: {label: '待发货', tone: 'primary'},
  shipped: {label: '待收货', tone: 'info'},
  completed: {label: '已完成', tone: 'ok'},
  cancelled: {label: '已取消', tone: 'muted'}
}

export const ORDER_FILTERS = [
  {key: 'all', label: '全部'},
  {key: 'pending', label: '待付款'},
  {key: 'paid', label: '待发货'},
  {key: 'shipped', label: '待收货'},
  {key: 'completed', label: '已完成'},
  {key: 'cancelled', label: '已取消'}
]

export const normalizeOrderStatus = (value) => String(value || '').toLowerCase()

export const orderStatusMeta = (status) => {
  const meta = ORDER_STATUS_META[normalizeOrderStatus(status)]
  if (meta) return meta
  return {label: status ? String(status) : '未知状态', tone: 'muted'}
}

/** 患者能取消：还没发货（待付款 / 待发货）。 */
export const canCancelOrder = (order) =>
  ['pending', 'paid'].includes(normalizeOrderStatus(order && order.status))

/** 患者能确认收货：商家已发货。 */
export const canReceiveOrder = (order) =>
  normalizeOrderStatus(order && order.status) === 'shipped'

/** 管理员能发货：已付款待发货。 */
export const canShipOrder = (order) => normalizeOrderStatus(order && order.status) === 'paid'

export const orderMoney = (value) => `¥${(Number(value) || 0).toFixed(2)}`

/** 订单号只显示前 8 位：UUID 全量在列表里既占宽又不好念。 */
export const shortOrderId = (id) => {
  const text = String(id || '')
  return text.length > 10 ? `${text.slice(0, 8)}…` : text
}

/** 明细件数：按 quantity 累加，不是「几种商品」。 */
export const orderItemCount = (order) => {
  const items = Array.isArray(order && order.items) ? order.items : []
  return items.reduce((sum, item) => sum + (Number(item.quantity) || 0), 0)
}

/** 明细摘要：「花红胶囊、花红片 等 3 种」。 */
export const orderItemText = (order, limit = 2) => {
  const items = Array.isArray(order && order.items) ? order.items : []
  const names = items.map((item) => item.name).filter(Boolean)
  if (!names.length) return '商品信息缺失'
  if (names.length <= limit) return names.join('、')
  return `${names.slice(0, limit).join('、')} 等 ${names.length} 种`
}

export default {
  ORDER_FILTERS,
  ORDER_STATUS_META,
  canCancelOrder,
  canReceiveOrder,
  canShipOrder,
  normalizeOrderStatus,
  orderItemCount,
  orderItemText,
  orderMoney,
  orderStatusMeta,
  shortOrderId
}
