<script setup>
/**
 * 患者工作台：把「看数字 → 处理掉 → 回对话」收在同一页。
 *
 * 为什么六个 Tab 不拆成六个路由：这里做的事都是「扫一眼再顺手点一下」，
 * 每跳一次页面就丢一次其它 Tab 的数据和滚动位置。但 Tab 仍然写进 URL（?tab=），
 * 刷新、分享、从别处回跳都能落回原位。
 *
 * 数据策略：概览要的数字由 /api/me/workbench 一次聚合给出；订单 / 购物车 / 会话 / 记忆
 * 各自还有更细的列表接口，所以「切到哪个 Tab 才拉哪份」，每个 Tab 只自动尝试一次，
 * 失败后由面板里的「重试」显式再拉——否则来回切 Tab 会把接口打成请求风暴。
 *
 * 保活：问诊 Tab 用 v-show。AgentChat 的流式回答挂在 SSE 上，组件一卸载就断流，
 * 其余 Tab 都是纯展示，用 v-if 按需挂载反而更省资源。
 */
import {computed, onActivated, onMounted, ref, watch} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import dayjs from 'dayjs'
import {showConfirmDialog, showToast} from 'vant'
import {
  ArrowRight,
  Brain,
  Building2,
  ClipboardList,
  ExternalLink,
  Headphones,
  LayoutDashboard,
  MessageSquare,
  Package,
  ShoppingCart,
  Sparkles,
  Stethoscope,
  Trash2,
  Truck,
  UserRound
} from 'lucide-vue-next'
import WorkbenchShell from '../components/workbench/WorkbenchShell.vue'
import PanelCard from '../components/workbench/PanelCard.vue'
import StatCard from '../components/workbench/StatCard.vue'
import FeatureHint from '../components/workbench/FeatureHint.vue'
import AgentChat from '../components/agent/AgentChat.vue'
import OrderCard from '../components/order/OrderCard.vue'
import CartItem from '../components/cart/CartItem.vue'
import {fetchMyWorkbench} from '../api/workbench'
import {writeCheckoutItems} from '../utils/checkout'
import {cancelOrderApi, getMyOrdersApi, receiveOrderApi} from '../api/order'
import {clearCartApi, getCartApi, removeCartItemApi, updateCartQuantityApi} from '../api/cart'
import {clearMemory, deleteMemory, fetchMemory, setMemoryEnabled} from '../api/memory'
import {fetchConversations} from '../api/support'
import {DEMO_SECTIONS, quickStarters} from '../data/quickPrompts'
import {openGuide} from '../store/guide'

// KeepAlive 靠 name 匹配（见 App.vue 的 CACHED 白名单）
defineOptions({name: 'PatientView'})

const route = useRoute()
const router = useRouter()

/* ------------------------------------------------------------------ *
 * 常量：枚举文案都以本文件为准，别的页面（OrderView / ServiceView /
 * MemoryView）用的是同一套值，改的时候要一起改。
 * ------------------------------------------------------------------ */

// 底部 Tab 控制在 5 个：会话与记忆都是低频查看项，合并成「我的」
const TAB_KEYS = ['overview', 'chat', 'orders', 'cart', 'mine']

const AGENTS = [
  {code: 'drug_consult', name: '用药咨询', icon: Stethoscope},
  {code: 'order_after_sale', name: '订单售后', icon: Package},
  {code: 'company_intro', name: '公司介绍', icon: Building2},
  {code: 'customer_service', name: '客服', icon: Headphones}
]

const AGENT_NAMES = AGENTS.reduce((map, agent) => {
  map[agent.code] = agent.name
  return map
}, {})

const CONVERSATION_STATUS = {
  bot_active: {label: '进行中', tone: 'primary'},
  handoff_pending: {label: '等待转接', tone: 'warn'},
  human_active: {label: '人工接待', tone: 'ok'},
  closed: {label: '已结束', tone: 'muted'}
}

// 后端 OrderStatus 是小写；OrderView 里的「待发货」就是 paid，别按字面理解成「已支付」
const ORDER_STATUS = {
  pending: {label: '待付款', tone: 'warn'},
  paid: {label: '待发货', tone: 'primary'},
  shipped: {label: '待收货', tone: 'info'},
  completed: {label: '已完成', tone: 'ok'},
  cancelled: {label: '已取消', tone: 'muted'}
}

const ORDER_FILTERS = [
  {key: 'all', label: '全部'},
  {key: 'pending', label: '待付款'},
  {key: 'paid', label: '待发货'},
  {key: 'shipped', label: '待收货'},
  {key: 'completed', label: '已完成'},
  {key: 'cancelled', label: '已取消'}
]

const TICKET_STATUS = {
  queued: {label: '排队中', tone: 'warn'},
  assigned: {label: '人工接待中', tone: 'ok'},
  resolved: {label: '已结束', tone: 'muted'},
  offline: {label: '已留言', tone: 'info'}
}

const MEMORY_TYPES = {
  fact: '事实',
  preference: '偏好',
  episode: '情节',
  risk: '禁忌',
  other: '其他'
}

// 类型色只是视觉分组，颜色本身不承载含义
const MEMORY_TYPE_TONES = {
  fact: 'info',
  preference: 'ok',
  episode: 'warn',
  risk: 'primary',
  other: 'muted'
}

/* ------------------------------------------------------------------ *
 * 小工具
 * ------------------------------------------------------------------ */

const normalizeStatus = (value) => String(value || '').toLowerCase()

const statusMeta = (map, value, fallbackLabel = '') => {
  const meta = map[normalizeStatus(value)]
  if (meta) return meta
  const label = value ? String(value) : fallbackLabel
  return {label, tone: 'muted'}
}

const formatTime = (value, pattern = 'YYYY-MM-DD HH:mm') => {
  if (!value) return ''
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format(pattern) : String(value)
}

const money = (value) => `¥${(Number(value) || 0).toFixed(2)}`

const shortId = (id) => {
  const text = String(id || '')
  return text ? `#${text.slice(0, 8)}` : '#—'
}

// 401 单独给一句人话：这是患者最可能遇到的错误（token 过期）
const errorText = (error, fallback) => {
  if (error && error.status === 401) return '登录已过期，请重新登录后再试'
  return (error && error.message) || fallback
}

const agentName = (code) => AGENT_NAMES[code] || code || 'AI 助手'
const conversationStatusMeta = (status) => statusMeta(CONVERSATION_STATUS, status, '未知状态')
const orderStatusMeta = (status) => statusMeta(ORDER_STATUS, status, '未知状态')
const ticketStatusMeta = (status) => statusMeta(TICKET_STATUS, status, '处理中')
const ticketLabel = (status) => ticketStatusMeta(status).label

const memoryTypeLabel = (type) => MEMORY_TYPES[normalizeStatus(type)] || MEMORY_TYPES.other
const memoryTypeTone = (type) => MEMORY_TYPE_TONES[normalizeStatus(type)] || 'muted'

const memorySourceText = (item) => {
  if (!item) return '来源未知'
  if (item.source_message_id) return '来自对话消息'
  if (item.source_conversation_id) return '来自会话记录'
  return '来源未知'
}

/* ------------------------------------------------------------------ *
 * Tab 与 URL：?tab=xxx，切换用 replace，不污染浏览器历史
 * ------------------------------------------------------------------ */

const readTabFromUrl = () => {
  const raw = Array.isArray(route.query.tab) ? route.query.tab[0] : route.query.tab
  const key = String(raw || '')
  return TAB_KEYS.includes(key) ? key : 'overview'
}

const active = ref(readTabFromUrl())

const writeTabToUrl = (key) => {
  const raw = Array.isArray(route.query.tab) ? route.query.tab[0] : route.query.tab
  const current = raw === undefined ? '' : String(raw)
  const next = key === 'overview' ? '' : key
  if (current === next) return
  // 展开 route.query 是为了不冲掉 AgentChat 自己维护的 ?c=（会话 id）
  const query = {...route.query}
  if (next) query.tab = next
  else delete query.tab
  router.replace({query}).catch(() => {})
}

// 概览是默认 Tab，URL 上就不留参数了；其它 Tab 一律写进 ?tab=
const tabTarget = (key) => ({path: '/patient', query: key === 'overview' ? {} : {tab: key}})

/* ------------------------------------------------------------------ *
 * 概览数据（聚合接口）
 * ------------------------------------------------------------------ */

const wb = ref(null)
const wbLoading = ref(false)
const wbError = ref('')
const updatedAt = ref('')
const refreshing = ref(false)

const loadWorkbench = async (options = {}) => {
  // silent 用于「回到概览时对齐数字」：不要骨架屏闪一下，也不要因为一次静默失败
  // 把整页打成错误态——上一次的数字仍然可用
  const silent = options.silent === true
  if (!silent) wbLoading.value = true
  try {
    wb.value = await fetchMyWorkbench()
    updatedAt.value = dayjs().format('HH:mm:ss')
    // 成功才清错误：静默刷新失败时保留上一次的错误态，别把「加载失败」悄悄变成空态
    wbError.value = ''
    // 聚合接口已经带了记忆开关与摘要，先灌进记忆 Tab 的状态里：
    // 这样没进过记忆 Tab 也能显示正确状态，而且不用为了开关多打一次 /api/me/memory
    if (wb.value && wb.value.memory && !memoryTouched.value) {
      memoryInfo.value = {
        ...memoryInfo.value,
        enabled: wb.value.memory.enabled !== false,
        summary: wb.value.memory.summary || memoryInfo.value.summary
      }
    }
  } catch (error) {
    if (!silent) wbError.value = errorText(error, '工作台数据加载失败')
  } finally {
    if (!silent) wbLoading.value = false
  }
}

const stats = computed(() => (wb.value && wb.value.stats ? wb.value.stats : {}))
const ticket = computed(() => (wb.value ? wb.value.ticket : null))

const recentConversations = computed(() => {
  const rows = wb.value && Array.isArray(wb.value.recent_conversations) ? wb.value.recent_conversations : []
  return rows.slice(0, 3)
})

const recentOrders = computed(() => {
  const rows = wb.value && Array.isArray(wb.value.recent_orders) ? wb.value.recent_orders : []
  return rows.slice(0, 3)
})

const statValue = (key) => {
  const value = stats.value[key]
  return Number.isFinite(Number(value)) ? Number(value) : '—'
}

const cartStatHint = computed(() => {
  const amount = Number(stats.value.cart_amount)
  return Number.isFinite(amount) && amount > 0 ? `已选 ${money(amount)}` : '还没有加购商品'
})

const memoryStatHint = computed(() => (memoryEnabledFlag.value ? 'AI 会参考这些信息' : '记忆已关闭，不再写入'))

const tabs = computed(() => [
  {key: 'overview', label: '概览', icon: LayoutDashboard},
  {key: 'chat', label: '问诊', icon: Stethoscope},
  {key: 'orders', label: '订单', icon: ClipboardList, badge: Number(stats.value.orders_pending) || 0},
  {key: 'cart', label: '购物车', icon: ShoppingCart, badge: Number(stats.value.cart_items) || 0},
  {key: 'mine', label: '我的', icon: UserRound}
])

/* 服务进度：一个工单只展示「当前进行到哪一步」，细节留给会话页 */
const ticketTitle = computed(() => {
  const row = ticket.value
  if (!row) return ''
  const status = normalizeStatus(row.status)
  if (status === 'queued') {
    const position = Number(row.queue_position) || 0
    return position > 0 ? `排队中第 ${position} 位` : '排队中'
  }
  if (status === 'assigned') return '人工接待中'
  if (status === 'resolved') return '已结束'
  if (status === 'offline') return '已留言'
  return row.status ? String(row.status) : '处理中'
})

const ticketDetail = computed(() => {
  const row = ticket.value
  if (!row) return ''
  const bits = []
  if (row.reason) bits.push(`原因：${row.reason}`)
  if (row.trigger) bits.push(`触发：${row.trigger}`)
  if (row.created_at) bits.push(`建单 ${formatTime(row.created_at, 'MM-DD HH:mm')}`)
  return bits.join(' · ')
})

const ticketTip = computed(() => {
  switch (normalizeStatus(ticket.value && ticket.value.status)) {
    case 'queued':
      return '有坐席空出来会自动接入，接入后这里会变成「人工接待中」。'
    case 'assigned':
      return '客服已接管这段对话，AI 暂停回答；处理完会显示「已结束」。'
    case 'resolved':
      return '工单已关闭。问题还没解决的话，回到会话里可以重新发起转人工。'
    case 'offline':
      return '当时没有坐席在线，留言已保存，客服上线后会回访。'
    default:
      return ''
  }
})

const orderSummary = (order) => {
  const names = Array.isArray(order && order.item_names) ? order.item_names.filter(Boolean) : []
  const count = Number(order && order.item_count) || 0
  if (!names.length) return count > 0 ? `共 ${count} 件商品` : '商品信息缺失'
  const head = names.slice(0, 2).join('、')
  return count > 2 ? `${head} 等 ${count} 件` : head
}

/* 快捷提问：数据来自 quickPrompts，避免这里再抄一份问题文案 */
const quickAsks = computed(() => {
  const starters = quickStarters('drug_consult')
  const followUps = (DEMO_SECTIONS.drug_consult && DEMO_SECTIONS.drug_consult[1]
    ? DEMO_SECTIONS.drug_consult[1].items
    : [])
  return [...starters, ...followUps].slice(0, 5)
})

/* ------------------------------------------------------------------ *
 * 订单 Tab
 * ------------------------------------------------------------------ */

const orders = ref([])
const ordersLoading = ref(false)
const ordersError = ref('')
const ordersTouched = ref(false)
const orderFilter = ref('all')
const mutatingOrder = ref('')

const loadOrders = async () => {
  ordersLoading.value = true
  ordersError.value = ''
  try {
    const data = await getMyOrdersApi()
    orders.value = Array.isArray(data) ? data : []
  } catch (error) {
    ordersError.value = errorText(error, '订单加载失败')
  } finally {
    ordersLoading.value = false
  }
}

const orderCounts = computed(() => {
  const counts = {}
  orders.value.forEach((order) => {
    const key = normalizeStatus(order.status)
    counts[key] = (counts[key] || 0) + 1
  })
  return counts
})

const filteredOrders = computed(() => {
  if (orderFilter.value === 'all') return orders.value
  return orders.value.filter((order) => normalizeStatus(order.status) === orderFilter.value)
})

const ordersDesc = computed(() => `共 ${orders.value.length} 笔，当前筛选 ${filteredOrders.value.length} 笔`)
const ordersEmptyText = computed(() => (orderFilter.value === 'all' ? '还没有任何订单' : '该状态下暂无订单'))

const goOrder = (order) => {
  if (!order) return
  router.push(`/orders/${order.id}`)
}

// 状态变更后统计数字（待收货、订单数）会变，顺手静默对齐一次概览
const syncOrdersAndStats = async () => {
  await Promise.allSettled([loadOrders(), loadWorkbench({silent: true})])
}

const cancelOrder = async (order) => {
  if (!order || mutatingOrder.value) return
  try {
    await showConfirmDialog({
      title: '取消这笔订单？',
      message: `订单 ${shortId(order.id)} 取消后无法恢复。`,
      confirmButtonText: '取消订单',
      cancelButtonText: '再想想',
      confirmButtonColor: '#ef4444'
    })
  } catch (e) {
    return
  }
  mutatingOrder.value = order.id
  try {
    await cancelOrderApi(order.id)
    showToast('订单已取消')
    await syncOrdersAndStats()
  } catch (error) {
    showToast({type: 'fail', message: errorText(error, '取消失败，请稍后重试')})
  } finally {
    mutatingOrder.value = ''
  }
}

const receiveOrder = async (order) => {
  if (!order || mutatingOrder.value) return
  mutatingOrder.value = order.id
  try {
    await receiveOrderApi(order.id)
    showToast('已确认收货')
    await syncOrdersAndStats()
  } catch (error) {
    showToast({type: 'fail', message: errorText(error, '确认收货失败，请稍后重试')})
  } finally {
    mutatingOrder.value = ''
  }
}

/* ------------------------------------------------------------------ *
 * 购物车 Tab
 * ------------------------------------------------------------------ */

const cart = ref({items: [], total_price: 0})
const cartLoading = ref(false)
const cartError = ref('')
const cartTouched = ref(false)
const cartBusyId = ref('')
const cartClearing = ref(false)

const loadCart = async () => {
  cartLoading.value = true
  cartError.value = ''
  try {
    const data = await getCartApi()
    cart.value = {
      items: data && Array.isArray(data.items) ? data.items : [],
      total_price: data ? Number(data.total_price) || 0 : 0
    }
  } catch (error) {
    cartError.value = errorText(error, '购物车加载失败')
  } finally {
    cartLoading.value = false
  }
}

const cartRows = computed(() => (Array.isArray(cart.value.items) ? cart.value.items : []))
// 合计在前端按行重算：加减数量时不必等接口回来，金额就已经对得上了
const cartTotalAmount = computed(() => cartRows.value.reduce(
  (sum, row) => sum + (Number(row.price) || 0) * (Number(row.quantity) || 0),
  0
))
const cartTotalCount = computed(() => cartRows.value.reduce(
  (sum, row) => sum + (Number(row.quantity) || 0),
  0
))

// CartItem 直接给出「改完是多少」，这里不再自己算 +1/-1
const changeCartQuantity = async (row, next) => {
  if (!row || cartBusyId.value) return
  const before = Number(row.quantity) || 0
  const target = Number(next) || 0
  if (target < 1) {
    showToast('至少 1 件，不要了可以点删除')
    return
  }
  cartBusyId.value = row.id
  row.quantity = target // 先动本地：加减号要立刻有反馈
  try {
    await updateCartQuantityApi(row.id, target)
  } catch (error) {
    row.quantity = before // 失败回滚，别让界面显示一个后端没接受的数字
    showToast({type: 'fail', message: errorText(error, '修改数量失败')})
  } finally {
    cartBusyId.value = ''
  }
}

const removeCartRow = async (row) => {
  if (!row || cartBusyId.value) return
  cartBusyId.value = row.id
  try {
    await removeCartItemApi(row.id)
    cart.value = {...cart.value, items: cartRows.value.filter((item) => item.id !== row.id)}
    showToast('已移出购物车')
    await loadWorkbench({silent: true})
  } catch (error) {
    showToast({type: 'fail', message: errorText(error, '移出失败，请稍后重试')})
  } finally {
    cartBusyId.value = ''
  }
}

const clearCart = async () => {
  if (cartClearing.value) return
  if (!cartRows.value.length) {
    showToast('购物车已经是空的')
    return
  }
  try {
    await showConfirmDialog({
      title: '清空购物车？',
      message: `将移除全部 ${cartRows.value.length} 种商品。`,
      confirmButtonText: '清空',
      cancelButtonText: '取消',
      confirmButtonColor: '#ef4444'
    })
  } catch (e) {
    return
  }
  cartClearing.value = true
  try {
    await clearCartApi()
    cart.value = {items: [], total_price: 0}
    showToast('购物车已清空')
    await loadWorkbench({silent: true})
  } catch (error) {
    showToast({type: 'fail', message: errorText(error, '清空失败，请稍后重试')})
  } finally {
    cartClearing.value = false
  }
}

// 结算清单必须显式写进去：之前这里直接 push('/checkout')，
// 结算页拿不到清单就永远显示「没有要结算的商品」
const goCheckout = () => {
  if (!cartRows.value.length) {
    showToast('购物车是空的，先去逛逛')
    return
  }
  writeCheckoutItems(cartRows.value)
  router.push('/checkout')
}

/* ------------------------------------------------------------------ *
 * 会话 Tab
 * ------------------------------------------------------------------ */

const conversations = ref([])
const convLoading = ref(false)
const convError = ref('')
const convTouched = ref(false)

const loadConversations = async () => {
  convLoading.value = true
  convError.value = ''
  try {
    const data = await fetchConversations()
    conversations.value = Array.isArray(data) ? data : []
  } catch (error) {
    convError.value = errorText(error, '会话列表加载失败')
  } finally {
    convLoading.value = false
  }
}

const allConversations = computed(() => conversations.value)

// /api/conversations 不带消息数，但概览里的最近会话带了——
// 用同一段会话的已知条数补上，补不到就不显示，不编数字
const wbMessageCounts = computed(() => {
  const map = {}
  const rows = wb.value && Array.isArray(wb.value.recent_conversations) ? wb.value.recent_conversations : []
  rows.forEach((row) => {
    map[String(row.id)] = Number(row.message_count) || 0
  })
  return map
})

const messageCountOf = (row) => {
  const direct = Number(row && row.message_count)
  if (Number.isFinite(direct) && direct > 0) return direct
  const known = wbMessageCounts.value[String((row && row.id) || '')]
  return Number.isFinite(known) && known > 0 ? known : 0
}

const goConversation = (row) => {
  if (!row) return
  // 带上 ?c=<会话 id>：AgentChat 会把这段对话（含人工客服的消息）接回来
  router.push({path: `/agents/${row.agent_code || 'drug_consult'}`, query: {c: String(row.id)}})
}

const goService = () => router.push('/service')
// M5：药品广场（游客也能逛），购物车页在同一入口
const goDrugs = () => router.push('/drugs')

/* ------------------------------------------------------------------ *
 * 记忆 Tab
 * ------------------------------------------------------------------ */

const memoryInfo = ref({enabled: true, summary: '', profile: null, items: []})
const memoryLoading = ref(false)
const memoryError = ref('')
const memoryTouched = ref(false)
const memorySwitching = ref(false)
const memoryBusyId = ref('')
const memoryClearing = ref(false)

const loadMemory = async () => {
  memoryLoading.value = true
  memoryError.value = ''
  try {
    const data = await fetchMemory()
    memoryInfo.value = {
      enabled: !data || data.enabled !== false,
      summary: (data && data.summary) || '',
      profile: (data && data.profile) || null,
      items: data && Array.isArray(data.items) ? data.items : []
    }
  } catch (error) {
    memoryError.value = errorText(error, '记忆加载失败')
  } finally {
    memoryLoading.value = false
  }
}

const memoryEnabledFlag = computed(() => memoryInfo.value.enabled !== false)

const memoryItems = computed(() => (Array.isArray(memoryInfo.value.items) ? memoryInfo.value.items : []))

// 三个来源可能都缺：优先取记忆接口，再退到概览里的摘要
const memorySummaryText = computed(() => {
  const local = memoryInfo.value.summary ? String(memoryInfo.value.summary) : ''
  const profile = memoryInfo.value.profile && memoryInfo.value.profile.summary
    ? String(memoryInfo.value.profile.summary)
    : ''
  const fromWb = wb.value && wb.value.memory && wb.value.memory.summary ? String(wb.value.memory.summary) : ''
  return local || profile || fromWb
})

const toggleMemory = async (value) => {
  if (memorySwitching.value) return
  const next = !!value
  memorySwitching.value = true
  try {
    const data = await setMemoryEnabled(next)
    const applied = data && typeof data.enabled === 'boolean' ? data.enabled : next
    memoryInfo.value = {...memoryInfo.value, enabled: applied}
    if (wb.value && wb.value.memory) {
      wb.value = {...wb.value, memory: {...wb.value.memory, enabled: applied}}
    }
    showToast(applied ? '已开启记忆' : '已关闭记忆')
  } catch (error) {
    // 受控开关：失败就保持原值，让开关弹回去
    showToast({type: 'fail', message: errorText(error, '设置失败，请稍后重试')})
  } finally {
    memorySwitching.value = false
  }
}

const removeMemoryItem = async (item) => {
  if (!item || memoryBusyId.value) return
  memoryBusyId.value = item.id
  try {
    const data = await deleteMemory(item.id)
    // 契约：别人的 id 一律 deleted:false，不区分「不存在」与「不是你的」
    if (data && data.deleted === false) {
      showToast('这条记忆不存在或已被删除')
    } else {
      showToast('已删除')
    }
    memoryInfo.value = {
      ...memoryInfo.value,
      items: memoryItems.value.filter((row) => row.id !== item.id)
    }
    await loadWorkbench({silent: true})
  } catch (error) {
    showToast({type: 'fail', message: errorText(error, '删除失败，请稍后重试')})
  } finally {
    memoryBusyId.value = ''
  }
}

const clearAllMemory = async () => {
  if (memoryClearing.value) return
  if (!memoryItems.value.length) {
    showToast('暂无记忆可清空')
    return
  }
  try {
    await showConfirmDialog({
      title: '清空全部记忆？',
      message: `将删除全部 ${memoryItems.value.length} 条记忆，AI 之后不会再记得这些信息，且不可恢复。`,
      confirmButtonText: '清空',
      cancelButtonText: '取消',
      confirmButtonColor: '#ef4444'
    })
  } catch (e) {
    return
  }
  memoryClearing.value = true
  try {
    const data = await clearMemory()
    memoryInfo.value = {...memoryInfo.value, items: [], summary: '', profile: null}
    showToast(`已清空 ${Number(data && data.deleted) || 0} 条记忆`)
    await loadWorkbench({silent: true})
  } catch (error) {
    showToast({type: 'fail', message: errorText(error, '清空失败，请稍后重试')})
  } finally {
    memoryClearing.value = false
  }
}

const goMemoryPage = () => router.push('/me/memory')

/* ------------------------------------------------------------------ *
 * 问诊 Tab
 * ------------------------------------------------------------------ */

const chatAgent = ref('drug_consult')

const switchAgent = async (code) => {
  if (!code || chatAgent.value === code) return
  // URL 上的 ?c= 属于上一个助手的会话；不清掉的话，新挂载的 AgentChat
  // 会把它当成「要接回的会话」直接恢复进来，等于把两个助手的对话串在一起。
  // 必须等 replace 落地再换 key：AgentChat 是在 onMounted 里读 ?c= 的，
  // 早一步挂载就会读到还没被删掉的那个 id。
  const cid = Array.isArray(route.query.c) ? route.query.c[0] : route.query.c
  if (cid) {
    const query = {...route.query}
    delete query.c
    await router.replace({query}).catch(() => {})
  }
  // 换 key 重新挂载：AgentChat 内部状态、会话 id、WS 都是按 agent 建的
  chatAgent.value = code
}

// 概览/订单里的「去问用药问题」留在页内切换，避免为了一句提问离开工作台。
// 先 await switchAgent 再切 Tab：否则「删 ?c=」与「写 ?tab=」两次 replace 会互相覆盖，
// 后一次从旧 route 里把刚删掉的 c 又抄回来
const goChat = async (code = 'drug_consult') => {
  await switchAgent(code)
  active.value = 'chat'
}

const askQuick = (item) => {
  // AgentChat 支持 ?q= 预填（M5 新增），但只预填、不自动发送：
  // 一进页面就发会被限流，也让人来不及看清当前是哪个 Agent。
  if (!item || !item.text) {
    router.push({path: '/agents/drug_consult'})
    return
  }
  showToast('已把问题填进输入框，确认后发送')
  router.push({path: '/agents/drug_consult', query: {q: item.text}})
}

/* ------------------------------------------------------------------ *
 * 按 Tab 懒加载：只拉当前 Tab 需要的那份
 * ------------------------------------------------------------------ */

const activateTab = async (key, force = false) => {
  if (key === 'overview') {
    // 回到概览时对齐数字（购物车加减 / 取消订单之后统计会变），有旧数据就走静默刷新
    await loadWorkbench({silent: !!wb.value})
    return
  }
  if (key === 'chat') return // AgentChat 自己管数据
  if (key === 'orders') {
    if (force || !ordersTouched.value) {
      ordersTouched.value = true
      await loadOrders()
    }
    return
  }
  if (key === 'cart') {
    if (force || !cartTouched.value) {
      cartTouched.value = true
      await loadCart()
    }
    return
  }
  if (key === 'mine') {
    // 「我的」里两块数据各自懒加载：进 Tab 时并行拉，失败互不影响
    const tasks = []
    if (force || !convTouched.value) {
      convTouched.value = true
      tasks.push(loadConversations())
    }
    if (force || !memoryTouched.value) {
      memoryTouched.value = true
      tasks.push(loadMemory())
    }
    await Promise.allSettled(tasks)
  }
}

const loadAll = async () => {
  if (refreshing.value) return
  refreshing.value = true
  try {
    const tasks = [loadWorkbench()]
    // 概览/问诊的数据都在聚合接口与 AgentChat 里，不需要额外再拉一次
    if (active.value !== 'overview' && active.value !== 'chat') {
      tasks.push(activateTab(active.value, true))
    }
    await Promise.allSettled(tasks)
  } finally {
    refreshing.value = false
  }
}

// onMounted 先按地址栏落 Tab（深链 ?tab=orders 要准），再并行拉聚合概览 + 当前 Tab
onMounted(async () => {
  active.value = readTabFromUrl()
  // 首屏只并行两支：聚合概览 + 当前 Tab 的列表；一支失败不影响另一支
  const tasks = [loadWorkbench()]
  if (active.value !== 'overview' && active.value !== 'chat') {
    tasks.push(activateTab(active.value, true))
  }
  await Promise.allSettled(tasks)
})

/**
 * 页面被 KeepAlive 缓存后再次进入（例如下单成功跳回工作台、从详情页返回），
 * 不能沿用离开时的旧数字——这正是「下完单回来统计没变」的原因。
 * 每次激活都静默对齐一次：概览数字 + 当前 Tab 的列表。
 */
let activatedOnce = false
onActivated(async () => {
  if (!activatedOnce) {
    activatedOnce = true // 首次进入由 onMounted 负责，避免重复请求
    return
  }
  const tasks = [loadWorkbench({silent: true})]
  if (active.value !== 'overview' && active.value !== 'chat') {
    tasks.push(activateTab(active.value, true))
  }
  await Promise.allSettled(tasks)
})

// Tab 切换：写 URL + 懒加载该 Tab 的数据。
// 购物车每次都重拉：它会被别的页面改（广场加购、下单成功清空），
// 拿着上一次的旧行去结算，等于把已经买过的商品再下一单。
watch(active, (key) => {
  writeTabToUrl(key)
  activateTab(key, key === 'cart')
})

// 地址栏的 ?tab= 变了（例如点了指标卡），把页面切过去
watch(() => route.query.tab, () => {
  const key = readTabFromUrl()
  if (key !== active.value) active.value = key
})
</script>

<template>
  <WorkbenchShell
      role="patient"
      role-label="患者"
      title="患者工作台"
      subtitle="用药咨询、订单服务与记忆管理，都在这一页。"
      :tabs="tabs"
      v-model:active="active"
      :refreshing="refreshing"
      :updated-at="updatedAt"
      @refresh="loadAll"
  >
    <!-- ------------------------------ 概览 ------------------------------ -->
    <div v-if="active === 'overview'" class="pane">
      <div class="stats-grid">
        <StatCard
            label="进行中会话"
            :value="statValue('conversations')"
            unit="个"
            hint="点开继续上次对话"
            tone="primary"
            :icon="MessageSquare"
            :to="tabTarget('mine')"
            :loading="wbLoading"
        />
        <StatCard
            label="待收货"
            :value="statValue('orders_pending')"
            unit="单"
            hint="已发货，记得确认收货"
            tone="warn"
            :icon="Truck"
            :to="tabTarget('orders')"
            :loading="wbLoading"
        />
        <StatCard
            label="购物车"
            :value="statValue('cart_items')"
            unit="件"
            :hint="cartStatHint"
            :icon="ShoppingCart"
            :to="tabTarget('cart')"
            :loading="wbLoading"
        />
        <StatCard
            label="我的记忆"
            :value="statValue('memories')"
            unit="条"
            :hint="memoryStatHint"
            tone="ok"
            :icon="Brain"
            :to="tabTarget('mine')"
            :loading="wbLoading"
        />
      </div>

      <FeatureHint
          title="这一页展示的是真实数据"
          text="数字由 /api/me/workbench 一次聚合给出，切到哪个 Tab 才拉哪份列表。快捷提问会打开对应助手并把问题填进输入框（不自动发送，避免一进页面就撞限流）。"
          :tags="[{label: 'RAG 引用', key: 'rag'}, {label: '设计取舍', key: 'design'}]"
          storage-key="patient.overview"
          @tag-click="openGuide('thinking')"
      />

      <div class="panel-grid">
        <PanelCard
            title="服务进度"
            desc="转人工之后的排队与接待状态"
            :icon="Headphones"
            :loading="wbLoading"
            :error="wbError"
            :empty="!ticket"
            empty-text="当前没有进行中的工单"
            empty-hint="在对话里说「我要投诉」或点「转人工」，会自动建单"
            :rows="2"
            @retry="loadWorkbench()"
        >
          <template #extra>
            <button type="button" class="btn" @click="goService">
              会话页<ArrowRight :size="13"/>
            </button>
          </template>

          <div class="ticket">
            <div class="ticket-head">
              <span class="ticket-title">{{ ticketTitle }}</span>
              <span class="pill" :class="`pill--${ticketStatusMeta(ticket.status).tone}`">
                {{ ticketStatusMeta(ticket.status).label }}
              </span>
            </div>
            <p v-if="ticketDetail" class="ticket-detail">{{ ticketDetail }}</p>
            <p v-if="ticketTip" class="ticket-tip">{{ ticketTip }}</p>
          </div>
        </PanelCard>

        <PanelCard
            title="最近对话"
            desc="最近 3 段对话，点一下接着聊"
            :icon="MessageSquare"
            :loading="wbLoading"
            :error="wbError"
            :empty="recentConversations.length === 0"
            empty-text="还没有对话记录"
            empty-hint="去「问诊」Tab 问一句，这里就有记录了"
            :rows="3"
            @retry="loadWorkbench()"
        >
          <ul class="mini-list">
            <li v-for="row in recentConversations" :key="row.id">
              <button type="button" class="mini-item" @click="goConversation(row)">
                <span class="mini-main">
                  <span class="mini-title">{{ row.title || '未命名会话' }}</span>
                  <span class="mini-meta">
                    <span>{{ agentName(row.agent_code) }}</span>
                    <span>{{ conversationStatusMeta(row.status).label }}</span>
                    <span v-if="messageCountOf(row)">{{ messageCountOf(row) }} 条消息</span>
                    <span class="mini-time">{{ formatTime(row.updated_at, 'MM-DD HH:mm') }}</span>
                  </span>
                </span>
                <ArrowRight :size="14" class="mini-arrow"/>
              </button>
            </li>
          </ul>
        </PanelCard>

        <PanelCard
            title="最近订单"
            desc="最近 3 笔订单，点开看详情"
            :icon="ClipboardList"
            :loading="wbLoading"
            :error="wbError"
            :empty="recentOrders.length === 0"
            empty-text="还没有订单"
            empty-hint="下单后这里会显示金额与状态"
            :rows="3"
            @retry="loadWorkbench()"
        >
          <ul class="mini-list">
            <li v-for="order in recentOrders" :key="order.id">
              <button type="button" class="mini-item" @click="goOrder(order)">
                <span class="mini-main">
                  <span class="mini-row">
                    <span class="mini-money">{{ money(order.total_amount) }}</span>
                    <span class="pill" :class="`pill--${orderStatusMeta(order.status).tone}`">
                      {{ orderStatusMeta(order.status).label }}
                    </span>
                  </span>
                  <span class="mini-meta">
                    <span>{{ orderSummary(order) }}</span>
                    <span class="mini-time">{{ formatTime(order.created_at, 'MM-DD HH:mm') }}</span>
                  </span>
                </span>
                <ArrowRight :size="14" class="mini-arrow"/>
              </button>
            </li>
          </ul>
        </PanelCard>

        <PanelCard
            title="快捷提问"
            desc="点一下把问题填进用药咨询助手的输入框（不自动发送）"
            :icon="Sparkles"
            :rows="2"
        >
          <div class="ask-grid">
            <button
                v-for="item in quickAsks"
                :key="item.text"
                type="button"
                class="ask-chip"
                :title="item.expect || item.text"
                @click="askQuick(item)"
            >
              <span class="ask-text">{{ item.text }}</span>
              <span v-if="item.expect" class="ask-expect">{{ item.expect }}</span>
            </button>
          </div>
        </PanelCard>
      </div>
    </div>

    <!-- ------------------------------ 问诊 ------------------------------ -->
    <!-- v-show 而不是 v-if：流式回答挂在 SSE 上，卸载即断流 -->
    <div v-show="active === 'chat'" class="pane chat-pane">
      <div class="agent-switch">
        <button
            v-for="agent in AGENTS"
            :key="agent.code"
            type="button"
            class="agent-chip"
            :class="{'is-active': chatAgent === agent.code}"
            @click="switchAgent(agent.code)"
        >
          <component :is="agent.icon" :size="15"/>
          {{ agent.name }}
        </button>
      </div>

      <AgentChat :key="chatAgent" :agent-code="chatAgent" compact/>
    </div>

    <!-- ------------------------------ 订单 ------------------------------ -->
    <div v-if="active === 'orders'" class="pane">
      <div class="filter-bar">
        <button
            v-for="item in ORDER_FILTERS"
            :key="item.key"
            type="button"
            class="filter-chip"
            :class="{'is-active': orderFilter === item.key}"
            @click="orderFilter = item.key"
        >
          {{ item.label }}
          <span v-if="item.key !== 'all' && orderCounts[item.key]" class="chip-count">
            {{ orderCounts[item.key] }}
          </span>
        </button>
      </div>

      <PanelCard
          title="我的订单"
          :desc="ordersDesc"
          :icon="ClipboardList"
          :loading="ordersLoading"
          :error="ordersError"
          :empty="filteredOrders.length === 0"
          :empty-text="ordersEmptyText"
          empty-hint="不确定要不要买？可以先问问 AI 药师"
          :rows="4"
          @retry="loadOrders"
      >
        <template #extra>
          <button type="button" class="btn" @click="goChat()">去问问用药问题</button>
        </template>

        <div class="order-list">
          <!-- 订单卡与「我的订单」页、管理员订单管理共用同一个组件：
               缩略图、状态标签、点进详情只实现一次 -->
          <OrderCard
              v-for="order in filteredOrders"
              :key="order.id"
              flat
              mode="patient"
              :order="order"
              :mutating="mutatingOrder === order.id"
              @open="goOrder"
              @cancel="cancelOrder"
              @receive="receiveOrder"
          />
        </div>
      </PanelCard>
    </div>

    <!-- ------------------------------ 购物车 ------------------------------ -->
    <div v-if="active === 'cart'" class="pane">
      <PanelCard
          title="购物车"
          desc="数量改动即时生效，最终金额以结算页为准"
          :icon="ShoppingCart"
          :loading="cartLoading"
          :error="cartError"
          :empty="cartRows.length === 0"
          empty-text="购物车是空的"
          empty-hint="去商品页挑点东西，或者先问问 AI 药师你需要什么"
          :rows="3"
          @retry="loadCart"
      >
        <template #extra>
          <button type="button" class="btn" @click="goDrugs">去逛逛</button>
          <button
              type="button"
              class="btn btn-danger"
              :disabled="cartClearing || cartRows.length === 0"
              @click="clearCart"
          >
            {{ cartClearing ? '清空中…' : '清空' }}
          </button>
        </template>

        <div class="cart-list">
          <!-- 与购物车浮层、购物车页共用同一行组件（缩略图 / 步进器 / 小计 / 删除） -->
          <CartItem
              v-for="row in cartRows"
              :key="row.id"
              :item="row"
              :busy="cartBusyId === row.id"
              @change="changeCartQuantity"
              @remove="removeCartRow"
          />
        </div>

        <div class="cart-footer">
          <div class="cart-total">
            共 <strong>{{ cartTotalCount }}</strong> 件，合计
            <strong class="total-money">{{ money(cartTotalAmount) }}</strong>
          </div>
          <button
              type="button"
              class="btn is-primary"
              :disabled="cartRows.length === 0"
              @click="goCheckout"
          >
            去结算
          </button>
        </div>
      </PanelCard>
    </div>

    <!-- ------------------------------ 我的（会话 + 记忆） ------------------------------ -->
    <!-- 底部 Tab 要控制在 5 个以内，所以会话与记忆合并：两者都是低频查看，
         并排放在一屏里信息密度反而更高，也少一次 Tab 跳转 -->
    <div v-if="active === 'mine'" class="pane">
      <PanelCard
          title="我的会话"
          desc="AI 与人工客服的对话都在这里，可回到原会话继续"
          :icon="MessageSquare"
          :loading="convLoading"
          :error="convError"
          :empty="allConversations.length === 0"
          empty-text="还没有会话记录"
          empty-hint="去「问诊」Tab 问一句，这里就会留下记录"
          :rows="4"
          @retry="loadConversations"
      >
        <template #extra>
          <button type="button" class="btn" @click="goService">消息页</button>
        </template>

        <ul class="conv-list">
          <li
              v-for="row in allConversations"
              :key="row.id"
              class="conv-item is-clickable"
              @click="goConversation(row)"
          >
            <div class="conv-main">
              <div class="conv-top">
                <span class="conv-title">{{ row.title || '未命名会话' }}</span>
                <span class="pill" :class="`pill--${conversationStatusMeta(row.status).tone}`">
                  {{ conversationStatusMeta(row.status).label }}
                </span>
              </div>
              <div class="conv-meta">
                <span>{{ agentName(row.agent_code) }}</span>
                <span v-if="messageCountOf(row)">{{ messageCountOf(row) }} 条消息</span>
                <span v-if="row.ticket" class="meta-ticket">
                  工单 · {{ ticketLabel(row.ticket.status) }}
                </span>
                <span class="mini-time">{{ formatTime(row.updated_at, 'MM-DD HH:mm') }}</span>
              </div>
            </div>

            <button type="button" class="btn" @click.stop="goConversation(row)">
              继续对话<ArrowRight :size="13"/>
            </button>
          </li>
        </ul>
      </PanelCard>

      <div class="section-divider">
        <Brain :size="14"/>
        <span>长期记忆</span>
        <i>只影响你的回答，随时可删</i>
      </div>

      <section class="card switch-card">
        <div class="switch-text">
          <strong>允许 AI 记录我的信息</strong>
          <span>关闭后不再写入新记忆、也不再注入对话；已有条目仍可删除。</span>
        </div>
        <van-switch
            :model-value="memoryEnabledFlag"
            :loading="memorySwitching"
            size="24px"
            active-color="#ef4444"
            @update:model-value="toggleMemory"
        />
      </section>

      <section v-if="memorySummaryText" class="card summary-card">
        <span class="summary-label">AI 对你的印象</span>
        <p class="summary-text">{{ memorySummaryText }}</p>
      </section>

      <PanelCard
          title="记忆条目"
          desc="只用于让回答更贴合你的情况，随时可以逐条删除"
          :icon="Brain"
          :loading="memoryLoading"
          :error="memoryError"
          :empty="memoryItems.length === 0"
          empty-text="还没有记住任何信息"
          empty-hint="聊几句之后，它会记住过敏史、剂型偏好这类信息"
          :rows="4"
          @retry="loadMemory"
      >
        <template #extra>
          <button
              type="button"
              class="btn btn-danger"
              :disabled="memoryClearing || memoryItems.length === 0"
              @click="clearAllMemory"
          >
            {{ memoryClearing ? '清空中…' : '一键清空' }}
          </button>
        </template>

        <ul class="memory-list">
          <li v-for="item in memoryItems" :key="item.id" class="memory-item">
            <div class="memory-main">
              <div class="memory-top">
                <span class="pill" :class="`pill--${memoryTypeTone(item.type)}`">
                  {{ memoryTypeLabel(item.type) }}
                </span>
                <span v-if="item.sensitive" class="pill pill--danger">敏感</span>
              </div>
              <p class="memory-content">{{ item.content }}</p>
              <div class="memory-meta">
                <span>{{ formatTime(item.created_at) }}</span>
                <span>{{ memorySourceText(item) }}</span>
              </div>
            </div>

            <button
                type="button"
                class="icon-btn"
                :disabled="memoryBusyId === item.id"
                title="删除这条记忆"
                @click="removeMemoryItem(item)"
            >
              <Trash2 :size="15"/>
            </button>
          </li>
        </ul>

        <div class="panel-foot">
          <button type="button" class="link-btn" @click="goMemoryPage">
            完整管理页<ExternalLink :size="13"/>
          </button>
        </div>
      </PanelCard>
    </div>
  </WorkbenchShell>
</template>

<style scoped lang="scss">
.pane {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}

/* ---------------------------------- 通用零件 ---------------------------------- */

.card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 14px 16px;
  min-width: 0;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  height: 34px;
  padding: 0 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
  color: #374151;
  font-size: 12.5px;
  white-space: nowrap;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s, background-color 0.15s;

  &:hover:not(:disabled) {
    border-color: #fecaca;
    color: #b91c1c;
  }

  &:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }

  &.is-primary {
    border-color: #ef4444;
    background: #ef4444;
    color: #fff;

    &:hover:not(:disabled) {
      border-color: #dc2626;
      background: #dc2626;
      color: #fff;
    }
  }

  &.btn-danger {
    border-color: #fecaca;
    background: #fef2f2;
    color: #b91c1c;
  }
}

.icon-btn {
  flex-shrink: 0;
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: 1px solid #f3f4f6;
  border-radius: 8px;
  background: #f9fafb;
  color: #9ca3af;
  cursor: pointer;

  &:hover:not(:disabled) {
    background: #fef2f2;
    color: #ef4444;
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
}

.link-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0;
  border: none;
  background: transparent;
  color: #b91c1c;
  font-size: 12.5px;
  cursor: pointer;

  &:hover {
    color: #ef4444;
    text-decoration: underline;
  }
}

.pill {
  flex-shrink: 0;
  padding: 1px 7px;
  border-radius: 999px;
  background: #f3f4f6;
  color: #6b7280;
  font-size: 11px;
  line-height: 17px;
  white-space: nowrap;

  &.pill--primary {
    background: #fef2f2;
    color: #b91c1c;
  }

  &.pill--warn {
    background: #fffbeb;
    color: #b45309;
  }

  &.pill--ok {
    background: #ecfdf5;
    color: #047857;
  }

  &.pill--info {
    background: #eff6ff;
    color: #1d4ed8;
  }

  &.pill--danger {
    background: #fef2f2;
    border: 1px solid #fecaca;
    color: #b91c1c;
  }

  &.pill--muted {
    background: #f3f4f6;
    color: #6b7280;
  }
}

/* ---------------------------------- 概览 ---------------------------------- */

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.panel-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  align-items: start;
}

.ticket {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.ticket-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.ticket-title {
  font-size: 15px;
  font-weight: 600;
  color: #111827;
}

.ticket-detail {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: #6b7280;
  overflow-wrap: anywhere;
}

.ticket-tip {
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
  color: #9ca3af;
}

.mini-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.mini-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 0;
  border: none;
  border-bottom: 1px solid #f3f4f6;
  background: transparent;
  text-align: left;
  cursor: pointer;

  &:hover .mini-title {
    color: #b91c1c;
  }
}

/* 分隔线挂在行上，所以要按 li 判最后一行——button 自己永远是 li 的 last-child */
.mini-list > li:last-child .mini-item {
  border-bottom: none;
}

.mini-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.mini-title {
  font-size: 13px;
  font-weight: 500;
  color: #374151;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mini-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.mini-money {
  font-size: 14px;
  font-weight: 700;
  color: #b91c1c;
}

.mini-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  font-size: 11px;
  color: #9ca3af;
  min-width: 0;
}

.mini-time {
  color: #c0c4cc;
}

.mini-arrow {
  flex-shrink: 0;
  color: #d1d5db;
}

/* 长列表放进自己的滚动区：订单/会话/记忆多起来时不要把整页拉长
   （底部 Tab 是 fixed 的，页面越长越难回到顶部；配合全局「返回顶部」按钮） */
.order-list,
.cart-list,
.conv-list,
.memory-list {
  max-height: 52vh;
  overflow-y: auto;
  padding-right: 4px;
  scrollbar-width: thin;
  scrollbar-color: #e5e7eb transparent;

  &::-webkit-scrollbar {
    width: 6px;
  }

  &::-webkit-scrollbar-thumb {
    background: #e5e7eb;
    border-radius: 3px;
  }
}

.ask-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.ask-chip {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s, background-color 0.15s;

  &:hover {
    border-color: #fecaca;
    background: #fff7f7;
  }
}

.ask-text {
  font-size: 12.5px;
  font-weight: 500;
  color: #374151;
  line-height: 1.5;
}

.ask-expect {
  width: 100%;
  font-size: 11px;
  color: #9ca3af;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ---------------------------------- 问诊 ---------------------------------- */

.chat-pane {
  gap: 10px;
}

.agent-switch {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 2px;
  scrollbar-width: none;

  &::-webkit-scrollbar {
    display: none;
  }
}

.agent-chip {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 36px;
  padding: 0 14px;
  border: 1px solid #e5e7eb;
  border-radius: 999px;
  background: #fff;
  color: #4b5563;
  font-size: 13px;
  white-space: nowrap;
  cursor: pointer;

  &:hover {
    border-color: #fecaca;
    color: #b91c1c;
  }

  &.is-active {
    border-color: #fecaca;
    background: #fef2f2;
    color: #b91c1c;
    font-weight: 600;
  }
}

/* ---------------------------------- 订单 ---------------------------------- */

.filter-bar {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding: 2px 2px 4px;
  scrollbar-width: none;

  &::-webkit-scrollbar {
    display: none;
  }
}

.filter-chip {
  flex-shrink: 0;
  height: 32px;
  padding: 0 12px;
  border: 1px solid #e5e7eb;
  border-radius: 999px;
  background: #fff;
  color: #6b7280;
  font-size: 12.5px;
  white-space: nowrap;
  cursor: pointer;

  &:hover {
    border-color: #fecaca;
    color: #b91c1c;
  }

  &.is-active {
    border-color: #fecaca;
    background: #fef2f2;
    color: #b91c1c;
    font-weight: 600;
  }

  .chip-count {
    margin-left: 4px;
    font-size: 11px;
    color: #b91c1c;
  }
}

.order-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.order-item {
  min-width: 0;
  padding: 12px 14px;
  border: 1px solid #f3f4f6;
  border-radius: 12px;
  background: #fff;
}

.order-top {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.order-id {
  font-size: 12px;
  color: #9ca3af;
  letter-spacing: 0.4px;
}

.order-amount {
  margin-left: auto;
  font-size: 15px;
  font-weight: 700;
  color: #b91c1c;
}

.order-names {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.6;
  color: #374151;
  overflow-wrap: anywhere;
}

.order-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  margin-top: 4px;
  font-size: 11px;
  color: #9ca3af;
}

.order-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 10px;
}

/* ---------------------------------- 购物车 ---------------------------------- */

.cart-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.cart-item {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding: 12px 0;
  border-bottom: 1px solid #f3f4f6;

  &:last-child {
    border-bottom: none;
  }
}

.cart-main {
  flex: 1;
  min-width: 0;
}

.cart-name {
  margin: 0;
  font-size: 13.5px;
  font-weight: 500;
  line-height: 1.6;
  color: #374151;
  overflow-wrap: anywhere;
}

.cart-price {
  margin: 3px 0 0;
  font-size: 11.5px;
  color: #9ca3af;
}

.stepper {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  overflow: hidden;

  button {
    display: grid;
    place-items: center;
    width: 30px;
    height: 30px;
    border: none;
    background: #fff;
    color: #4b5563;
    cursor: pointer;

    &:hover:not(:disabled) {
      background: #fef2f2;
      color: #b91c1c;
    }

    &:disabled {
      opacity: 0.45;
      cursor: not-allowed;
    }
  }

  span {
    min-width: 34px;
    text-align: center;
    font-size: 13px;
    color: #111827;
  }
}

.cart-subtotal {
  flex-shrink: 0;
  width: 74px;
  text-align: right;
  font-size: 13px;
  font-weight: 600;
  color: #b91c1c;
}

.cart-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 6px;
  padding-top: 12px;
  border-top: 1px dashed #e5e7eb;
}

.cart-total {
  font-size: 12.5px;
  color: #6b7280;

  strong {
    color: #111827;
  }

  .total-money {
    font-size: 18px;
    font-weight: 700;
    color: #b91c1c;
  }
}

/* ---------------------------------- 我的会话 ---------------------------------- */

.conv-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.conv-item {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding: 12px 0;
  border-bottom: 1px solid #f3f4f6;

  /* 整行可点（点卡片正文也能进会话，不用非去戳右边那个按钮） */
  &.is-clickable {
    cursor: pointer;
    transition: background-color 0.16s;

    &:hover {
      background: #fffbfb;

      .conv-title {
        color: #b91c1c;
      }
    }
  }

  &:last-child {
    border-bottom: none;
  }
}

.conv-main {
  flex: 1;
  min-width: 0;
}

.conv-top {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.conv-title {
  flex: 1;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 500;
  color: #374151;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  margin-top: 4px;
  font-size: 11px;
  color: #9ca3af;

  .meta-ticket {
    padding: 0 6px;
    border-radius: 6px;
    background: #fef2f2;
    color: #b91c1c;
  }
}

/* ---------------------------------- 记忆 ---------------------------------- */

/* 「我的」Tab 里会话与记忆之间需要一条分隔标题，否则两块内容会连成一片 */
.section-divider {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 2px 2px 0;
  padding-top: 6px;
  color: #6b7280;
  font-size: 12px;

  svg {
    color: #dc2626;
    flex-shrink: 0;
  }

  span {
    font-weight: 600;
    color: #374151;
  }

  i {
    font-style: normal;
    font-size: 11px;
    color: #9ca3af;
  }
}

.switch-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.switch-text {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;

  strong {
    font-size: 14px;
    font-weight: 600;
    color: #111827;
  }

  span {
    font-size: 11.5px;
    line-height: 1.6;
    color: #9ca3af;
  }
}

.summary-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.summary-label {
  font-size: 11px;
  color: #9ca3af;
}

.summary-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: #374151;
  overflow-wrap: anywhere;
}

.memory-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.memory-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
  padding: 12px 0;
  border-bottom: 1px solid #f3f4f6;

  &:last-child {
    border-bottom: none;
  }
}

.memory-main {
  flex: 1;
  min-width: 0;
}

.memory-top {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.memory-content {
  margin: 5px 0 0;
  font-size: 13.5px;
  line-height: 1.65;
  color: #374151;
  overflow-wrap: anywhere;
}

.memory-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  margin-top: 5px;
  font-size: 11px;
  color: #9ca3af;
}

.panel-foot {
  display: flex;
  justify-content: flex-end;
  padding-top: 10px;
  margin-top: 4px;
  border-top: 1px solid #f3f4f6;
}

/* 平板：四张指标卡挤在一行会开始挤压数字，退成 2×2；面板仍是两列 */
@media (max-width: 1024px) and (min-width: 769px) {
  .stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

/* ---------------------------------- 移动端 ---------------------------------- */
/* 布局在手机上退化成单列：指标卡、面板、快捷提问都一行一个，
   表格化的内容（订单/购物车/记忆）靠 overflow-wrap 换行，不横向撑破视口 */
@media (max-width: 768px) {
  .stats-grid,
  .panel-grid,
  .ask-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .btn,
  .agent-chip {
    min-height: 40px;
  }

  .filter-chip {
    height: 40px;
    padding: 0 14px;
  }

  .ask-chip {
    min-height: 40px;
  }

  .icon-btn,
  .stepper button {
    width: 40px;
    height: 40px;
  }

  .order-actions {
    justify-content: stretch;

    .btn {
      flex: 1 1 100px;
    }
  }

  .cart-item,
  .conv-item {
    flex-wrap: wrap;
  }

  .cart-subtotal {
    width: auto;
    margin-left: auto;
  }

  .cart-footer {
    .btn {
      width: 100%;
    }
  }

  .conv-item .btn {
    width: 100%;
  }
}
</style>
