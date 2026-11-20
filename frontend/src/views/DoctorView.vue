<script setup>
// KeepAlive 依赖组件名（App.vue 的 CACHED 白名单按 name 匹配）
defineOptions({name: 'DoctorView'})

/**
 * 医生工作台（/doctor，仅 doctor 角色）。
 *
 * 为什么把药品 CRUD 直接放进工作台，而不是只放一个「去药品库」的链接：
 * 医生的真实动作是「查资料 → 补资料 → 问 AI」，如果每件事都换一个页面，
 * 一次任务会被拆成三次导航。这里复用同一套 API 与 ProductFormModal，
 * 完整列表页 /products 仍然保留，两边操作的是同一份数据。
 *
 * 数据策略：
 * 1. 概览与药品各自按需加载，切到哪个 Tab 才拉哪份数据，避免首屏被多个请求堵住；
 * 2. 咨询面板一旦挂载就常驻（v-show），换 Tab 不会断开 SSE 流式回答；
 * 3. 刷新只刷新当前 Tab；咨询流由 AgentChat 自己维护，刷新不打断进行中的回答。
 */
import {computed, onActivated, onMounted, ref, watch} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import dayjs from 'dayjs'
import {showConfirmDialog, showToast} from 'vant'
import {
  ArrowRight,
  BotMessageSquare,
  FileText,
  LayoutDashboard,
  Lightbulb,
  LockKeyhole,
  MessageSquareText,
  MessagesSquare,
  Pencil,
  Pill,
  Plus,
  Search,
  ShieldAlert,
  Sparkles,
  Trash2,
  X,
  Zap
} from 'lucide-vue-next'
import WorkbenchShell from '../components/workbench/WorkbenchShell.vue'
import PanelCard from '../components/workbench/PanelCard.vue'
import StatCard from '../components/workbench/StatCard.vue'
import FeatureHint from '../components/workbench/FeatureHint.vue'
import ProductFormModal from '../components/product/ProductFormModal.vue'
import AgentChat from '../components/agent/AgentChat.vue'
import {fetchMyWorkbench} from '../api/workbench'
import {fetchConversations} from '../api/support'
import {createProductApi, deleteProductApi, getProductsApi, updateProductApi} from '../api/product'
import {useAuthStore} from '../store/auth'
import {openGuide} from '../store/guide'
import {useTabQuery} from '../composables/useTabQuery'

/* ------------------------------------------------------------------ *
 * 常量与通用小工具
 * ------------------------------------------------------------------ */

// 会话表里只存 agent_code，这里做一层可读名称；未知 code 原样展示，避免「猜错名字」
const AGENT_LABELS = {
  drug_consult: 'AI 药师',
  order_after_sale: '订单售后',
  company_intro: '企业介绍',
  customer_service: '客服助手'
}

const tabs = [
  {key: 'overview', label: '概览', icon: LayoutDashboard},
  {key: 'drugs', label: '药品库', icon: Pill},
  {key: 'consult', label: 'AI 用药咨询', icon: BotMessageSquare}
]
const TAB_KEYS = tabs.map((tab) => tab.key)

// 非法 tab 一律回落概览：URL 可以被手改，页面不能因此变成空白
const normalizeTab = (value) => (TAB_KEYS.includes(value) ? value : 'overview')

const DESIGN_TAGS = [{label: '为什么这么设计', key: 'thinking'}]

/**
 * axios / fetch 两条链路的错误形态不同：可能是字符串、数组，也可能没有 message。
 * 这里统一成一句能安全放进 showToast 的文本，绝不把 [object Object] 抛给用户。
 */
const errorText = (error, fallback) => {
  const message = error && error.message
  if (typeof message !== 'string') return fallback
  const text = message.trim()
  if (!text || text.includes('[object Object]')) return fallback
  return text
}

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

/* ------------------------------------------------------------------ *
 * Tab 状态：组件内 state 负责切换，URL 只做同步（刷新 / 分享能回到原位）
 * ------------------------------------------------------------------ */

const active = ref('overview')
// 咨询面板要保活，但也没必要一进工作台就建立会话上下文：第一次切过去才开始挂载
const consultVisited = ref(false)

// Tab ↔ ?tab= 的同步交给 useTabQuery：只有「当前路由就是 /doctor」的实例能改地址栏。
// 之前本页自己 watch(route.query.tab)，被 KeepAlive 缓存后仍会在别的页面上
// 把认不出的 tab「收敛」成 overview，顺手清掉患者页的 ?tab=（点 Tab 像没反应）。
const {readTab: readTabFromRoute, write: writeTabToRoute, sync: syncTabToUrl} = useTabQuery({
  path: '/doctor',
  tabs: TAB_KEYS,
  fallback: 'overview',
  active,
  converge: true
})
active.value = readTabFromRoute()
consultVisited.value = active.value === 'consult'

// 咨询面板的 ?c= 只在「人在 /doctor 的咨询 Tab 上」时归它维护（工作台被缓存后它仍然活着）
const ownsConsultQuery = computed(() => active.value === 'consult' && route.path === '/doctor')

const switchTab = (key) => {
  const next = normalizeTab(key)
  if (next !== active.value) active.value = next
}

// StatCard 的 to 走 router.push，因此这里生成「同一个 /doctor、不同 query」的地址
const tabLocation = (tab) => (tab === 'overview' ? '/doctor' : {path: '/doctor', query: {tab}})

const refreshing = ref(false)
const updatedAt = ref('')

/* ------------------------------------------------------------------ *
 * 概览数据
 * ------------------------------------------------------------------ */

const workbench = ref(null)
const overviewLoading = ref(false)
const overviewError = ref('')
const overviewLoaded = ref(false)

const recentConversations = ref([])
const conversationsLoading = ref(false)
const conversationsError = ref('')
const conversationsLoaded = ref(false)

// 首屏还没发起请求时也算「加载中」，否则会先闪一下空态文案
const conversationsPending = computed(() => (
  conversationsLoading.value || (!conversationsLoaded.value && !conversationsError.value)
))

const stats = computed(() => (workbench.value && workbench.value.stats) || {})

// 首帧到 onMounted 之间的空档也当作加载中，避免先闪一下「0 / 空」再变数字
const statsLoading = computed(() => (
  overviewLoading.value || (!overviewLoaded.value && !overviewError.value)
))

const statValue = (key) => {
  const value = stats.value[key]
  return value === undefined || value === null ? '—' : value
}

const documentHint = computed(() => {
  const libraries = stats.value.libraries
  const chunks = stats.value.chunks
  if (libraries === undefined || chunks === undefined) return '知识库后台仅管理员可编辑'
  return `${libraries} 个知识库 · ${chunks} 个切片`
})

// 聚合接口自带 3 条最近会话；单独接口失败时用它兜底，面板不至于整块变红
const workbenchFallbackConversations = () => {
  const list = workbench.value && Array.isArray(workbench.value.recent_conversations)
    ? workbench.value.recent_conversations
    : []
  return list.slice(0, 5)
}

const loadWorkbench = async ({silent = false} = {}) => {
  if (overviewLoading.value) return
  if (!silent) {
    overviewLoading.value = true
    overviewError.value = ''
  }
  try {
    const data = await fetchMyWorkbench()
    workbench.value = data || null
    overviewLoaded.value = true
    overviewError.value = ''
    updatedAt.value = dayjs().format('HH:mm:ss')
  } catch (error) {
    // 刷新失败保留上一次的数字：把已经看到的指标清空，比显示一条错误更让人困惑
    overviewError.value = errorText(error, '概览数据加载失败，请重试')
  } finally {
    if (!silent) overviewLoading.value = false
  }
}

const loadConversations = async ({silent = false} = {}) => {
  if (conversationsLoading.value) return
  if (!silent) conversationsLoading.value = true
  try {
    const data = await fetchConversations()
    recentConversations.value = Array.isArray(data) ? data.slice(0, 5) : []
    conversationsLoaded.value = true
    conversationsError.value = ''
    updatedAt.value = dayjs().format('HH:mm:ss')
  } catch (error) {
    const fallback = workbenchFallbackConversations()
    if (fallback.length > 0) {
      recentConversations.value = fallback
      conversationsLoaded.value = true
      conversationsError.value = ''
    } else {
      conversationsError.value = errorText(error, '最近会话加载失败，请重试')
    }
  } finally {
    if (!silent) conversationsLoading.value = false
  }
}

const loadOverview = async () => {
  // 两个接口互不依赖，并发拉；allSettled 保证一个失败不会吞掉另一个的结果
  await Promise.allSettled([loadWorkbench(), loadConversations()])

  // 并发时失败到达顺序不确定：等两个都结束后，再用聚合接口里的会话补一次兜底
  if (conversationsError.value && recentConversations.value.length === 0) {
    const fallback = workbenchFallbackConversations()
    if (fallback.length > 0) {
      recentConversations.value = fallback
      conversationsError.value = ''
      conversationsLoaded.value = true
    }
  }
}

const markOverviewStale = () => {
  // 药品增删改后概览里的「药品资料」数字会变；不立刻多打一次接口，下次切回概览再拉
  overviewLoaded.value = false
}

/* ------------------------------------------------------------------ *
 * 药品库：列表 + 搜索 + 增删改（复用 /products 的逻辑与表单）
 * ------------------------------------------------------------------ */

const products = ref([])
const productsLoading = ref(false)
const productsError = ref('')
const productsLoaded = ref(false)

// 与 conversationsPending 同理：首帧到 onMounted 之间不显示「药品库还是空的」
const productsPending = computed(() => (
  productsLoading.value || (!productsLoaded.value && !productsError.value)
))

const productKeyword = ref('')
const normalizedKeyword = computed(() => productKeyword.value.trim().toLowerCase())

const filteredProducts = computed(() => {
  const keyword = normalizedKeyword.value
  if (!keyword) return products.value
  return products.value.filter((item) => {
    if (!item) return false
    const haystack = [
      item.name,
      item.generic_name,
      item.category,
      item.manufacturer,
      item.approval_number,
      item.spec,
      item.indications
    ].filter(Boolean).join(' ').toLowerCase()
    return haystack.includes(keyword)
  })
})

const drugEmptyText = computed(() => {
  const keyword = productKeyword.value.trim()
  return keyword ? `没有匹配「${keyword}」的药品` : '药品库还是空的'
})

const drugEmptyHint = computed(() => (
  productKeyword.value.trim()
    ? '换个关键词，或清空搜索查看全部药品'
    : '点「新增药品」录入第一条资料'
))

const loadProducts = async ({silent = false} = {}) => {
  if (productsLoading.value) return
  if (!silent) {
    productsLoading.value = true
    productsError.value = ''
  }
  try {
    const data = await getProductsApi()
    products.value = Array.isArray(data) ? data : []
    productsLoaded.value = true
    productsError.value = ''
    updatedAt.value = dayjs().format('HH:mm:ss')
  } catch (error) {
    // axios 拦截器已经弹过 toast，这里只负责把面板切到「可重试」的错误态
    productsError.value = errorText(error, '药品列表加载失败，请稍后重试')
  } finally {
    if (!silent) productsLoading.value = false
  }
}

const productModalOpen = ref(false)
const productEditMode = ref(false)
const productFormData = ref({})
const productAgentText = ref('')
const savingProduct = ref(false)
const deletingId = ref('')

// 与 ProductView 的默认表单保持一致：必填字段先给空值，数字字段给 0，
// 避免 van-stepper 拿到 undefined 后显示 NaN
const emptyProductForm = () => ({
  name: '',
  generic_name: '',
  image_url: '',
  price: 0,
  original_price: 0,
  stock: 0,
  spec: '',
  category: '大健康产品',
  dosage_form: '',
  shelf_life: '',
  indications: '',
  contraindications: '',
  precautions: '',
  adverse_reactions: '',
  approval_number: '',
  manufacturer: ''
})

const openCreate = () => {
  productEditMode.value = false
  productFormData.value = emptyProductForm()
  // 录入文案是「这一次录入」的临时输入，换一条记录时清空，避免误解析上一段描述
  productAgentText.value = ''
  productModalOpen.value = true
}

const openEdit = (item) => {
  if (!item) return
  productEditMode.value = true
  productFormData.value = {...item}
  productAgentText.value = ''
  productModalOpen.value = true
}

const closeProductModal = () => {
  productModalOpen.value = false
}

/**
 * 新增前的必备字段校验。
 *
 * 为什么不把校验完全交给后端：422 的 detail 是数组，axios 拦截器会把它塞进
 * showToast，用户看到的可能是 [object Object]。这里提前拦住最常见的错误，
 * 提示才可读；编辑只校验名称——老数据可能字段不全，不该因为改库存被卡住。
 */
const validateProduct = (formData) => {
  const name = String(formData.name || '').trim()
  if (name.length < 2) return '请填写药品名称（至少 2 个字）'
  if (productEditMode.value) return ''

  const genericName = String(formData.generic_name || '').trim()
  const indications = String(formData.indications || '').trim()
  const contraindications = String(formData.contraindications || '').trim()
  const precautions = String(formData.precautions || '').trim()
  if (genericName.length < 2) return '请填写通用名（至少 2 个字）'
  if (!(Number(formData.price) > 0)) return '价格需要大于 0'
  if (!(Number(formData.original_price) > 0)) return '原价需要大于 0'
  if (!(Number(formData.stock) >= 0)) return '库存不能为负数'
  if (indications.length < 5) return '请填写功能主治（至少 5 个字）'
  if (contraindications.length < 2) return '请填写禁忌（至少 2 个字）'
  if (precautions.length < 2) return '请填写注意事项（至少 2 个字）'
  return ''
}

const handleProductSave = async (formData) => {
  if (!formData || savingProduct.value) return

  const problem = validateProduct(formData)
  if (problem) {
    showToast(problem)
    return
  }

  savingProduct.value = true
  try {
    if (productEditMode.value) {
      if (!formData.id) {
        showToast('缺少药品 ID，请重新打开编辑')
        return
      }
      await updateProductApi(formData.id, formData)
      showToast({type: 'success', message: '药品修改已保存'})
    } else {
      // 新增时去掉列表带来的只读字段（id / sales），只提交表单数据
      const payload = {...formData}
      delete payload.id
      delete payload.sales
      await createProductApi(payload)
      showToast({type: 'success', message: '药品已入库'})
    }

    productModalOpen.value = false
    productAgentText.value = ''
    // 新增后清空搜索，保证刚保存的那条（按创建时间倒序在顶部）一定可见
    if (!productEditMode.value) productKeyword.value = ''
    await loadProducts()
    markOverviewStale()
  } catch (error) {
    showToast({type: 'fail', message: errorText(error, '保存失败，请检查必填项后重试')})
  } finally {
    savingProduct.value = false
  }
}

const removeProduct = async (item) => {
  if (!item || !item.id || deletingId.value) return

  try {
    await showConfirmDialog({
      title: '删除药品资料',
      message: `确认删除「${item.name || '该药品'}」？删除后不可恢复。`,
      confirmButtonText: '删除',
      confirmButtonColor: '#ef4444',
      cancelButtonText: '取消'
    })
  } catch (error) {
    // 取消或关闭弹窗：不提示、不发请求
    return
  }

  deletingId.value = item.id
  try {
    await deleteProductApi(item.id)
    showToast({type: 'success', message: '药品已删除'})
    await loadProducts()
    // 删掉的恰好是搜索命中的最后一条时清空关键词，避免停在一个永远为空的列表
    if (productKeyword.value && filteredProducts.value.length === 0) {
      productKeyword.value = ''
    }
    markOverviewStale()
  } catch (error) {
    showToast({type: 'fail', message: errorText(error, '删除失败，请稍后重试')})
  } finally {
    deletingId.value = ''
  }
}

/* ------------------------------------------------------------------ *
 * 展示格式化
 * ------------------------------------------------------------------ */

const agentName = (code) => AGENT_LABELS[code] || code || '通用助手'

const conversationTitle = (item) => {
  const title = item && item.title ? String(item.title).trim() : ''
  return title || '未命名会话'
}

const formatWhen = (value) => {
  if (!value) return ''
  const time = dayjs(value)
  if (!time.isValid()) return ''
  const minutes = dayjs().diff(time, 'minute')
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  if (minutes < 60 * 24) return `${Math.floor(minutes / 60)} 小时前`
  if (minutes < 60 * 24 * 7) return `${Math.floor(minutes / 60 / 24)} 天前`
  return time.format('MM-DD HH:mm')
}

const formatExact = (value) => {
  if (!value) return ''
  const time = dayjs(value)
  return time.isValid() ? time.format('YYYY-MM-DD HH:mm') : ''
}

const openConversation = (item) => {
  if (!item || !item.id) return
  // 老会话可能没有 agent_code：退回主 Agent，至少能把历史消息接上
  const code = item.agent_code || 'drug_consult'
  router.push({path: `/agents/${encodeURIComponent(code)}`, query: {c: String(item.id)}})
}

const formatPrice = (value) => {
  const amount = Number(value)
  return Number.isFinite(amount) ? amount.toFixed(2) : '—'
}

const hasOriginalPrice = (item) => {
  if (!item) return false
  const original = Number(item.original_price)
  const price = Number(item.price)
  return Number.isFinite(original) && original > 0 && (!Number.isFinite(price) || original > price)
}

const stockText = (value) => {
  const count = Number(value)
  if (!Number.isFinite(count)) return '—'
  if (count <= 0) return '缺货'
  return String(count)
}

const stockTone = (value) => {
  const count = Number(value)
  if (!Number.isFinite(count)) return ''
  if (count <= 0) return 'is-out'
  if (count < 20) return 'is-low'
  return ''
}

/* ------------------------------------------------------------------ *
 * 快捷入口与权限
 * ------------------------------------------------------------------ */

// 检索测试台是 /admin 路由，医生点进去只会被守卫弹回首页；
// 所以这里先自己判断角色，用一个明确的提示代替 403 / 无声跳转
const canUseSearchTest = computed(() => auth.isAdmin)

const openSearchTest = () => {
  if (!canUseSearchTest.value) {
    showToast('检索测试台仅管理员可用：请切换到管理员账号再试')
    return
  }
  router.push('/admin/kb/search-test')
}

/* ------------------------------------------------------------------ *
 * 按需加载与刷新
 * ------------------------------------------------------------------ */

const ensureTabData = (tab) => {
  if (tab === 'consult') {
    consultVisited.value = true
    return
  }

  if (tab === 'drugs') {
    if (productsLoading.value) return
    if (!productsLoaded.value || productsError.value) loadProducts()
    return
  }

  const needWorkbench = !overviewLoaded.value || !!overviewError.value
  const needConversations = !conversationsLoaded.value || !!conversationsError.value
  if (needWorkbench && needConversations) {
    loadOverview()
  } else if (needWorkbench) {
    loadWorkbench()
  } else if (needConversations) {
    loadConversations()
  }
}

const loadAll = async () => {
  if (refreshing.value) return
  refreshing.value = true
  try {
    if (active.value === 'drugs') {
      await loadProducts()
      markOverviewStale()
      return
    }
    if (active.value === 'consult') {
      // 对话本身由 AgentChat 维护；刷新只同步概览数字，绝不打断正在生成的回答
      await loadWorkbench({silent: true})
      return
    }
    await loadOverview()
  } finally {
    refreshing.value = false
  }
}

/* ------------------------------------------------------------------ *
 * 同步与初始化
 * ------------------------------------------------------------------ */

// 切 Tab 时只为新 Tab 准备数据；URL 由 useTabQuery 负责
watch(active, (tab) => {
  ensureTabData(tab)
})

onMounted(() => {
  // 手改出来的非法 ?tab 先收敛回 overview，否则刷新后地址栏会一直停在坏值
  // （useTabQuery 只在 route 变化时收敛，首帧要靠这里补一次）
  writeTabToRoute(active.value)
  ensureTabData(active.value)
})

// 切角色回来看的是缓存实例：地址栏是不带参数的 /doctor，把当前 Tab 补回去
onActivated(() => {
  syncTabToUrl()
})
</script>

<template>
  <WorkbenchShell
      role="doctor"
      role-label="医生"
      title="医生工作台"
      subtitle="药品资料维护 + AI 用药咨询辅助。"
      :tabs="tabs"
      v-model:active="active"
      :refreshing="refreshing"
      :updated-at="updatedAt"
      @refresh="loadAll"
  >
    <template #actions>
      <button type="button" class="head-link" @click="openGuide('thinking')">
        <Lightbulb :size="14"/>
        <span>设计思路</span>
      </button>
    </template>

    <!-- ============================ 概览 ============================ -->
    <div v-if="active === 'overview'" class="tab-panel">
      <FeatureHint
          storage-key="doctor-overview"
          title="Agent 给专业岗位提效，而不是替代处方"
          text="这里把药品资料维护、知识库检索和带引用的 AI 用药咨询放在一个屏里，减少来回跳转。展示重点是 Agent 如何给专业岗位提效，不涉及处方与诊断。"
          :tags="DESIGN_TAGS"
          @tag-click="openGuide('thinking')"
      />

      <div v-if="overviewError" class="inline-error" role="alert">
        <ShieldAlert :size="15"/>
        <span>{{ overviewError }}</span>
        <button type="button" class="inline-retry" @click="loadWorkbench()">重试</button>
      </div>

      <div class="stat-grid">
        <StatCard
            label="药品资料"
            :value="statValue('products')"
            unit="种"
            hint="在库药品，点进来可直接维护"
            tone="primary"
            :icon="Pill"
            :to="tabLocation('drugs')"
            :loading="statsLoading"
        />
        <StatCard
            label="知识库文档"
            :value="statValue('documents')"
            unit="篇"
            :hint="documentHint"
            :icon="FileText"
            :loading="statsLoading"
        />
        <StatCard
            label="24h 咨询"
            :value="statValue('consults_24h')"
            unit="次"
            hint="最近 24 小时新增会话"
            :icon="MessagesSquare"
            :to="tabLocation('consult')"
            :loading="statsLoading"
        />
        <StatCard
            label="最近会话"
            :value="statValue('conversations')"
            unit="个"
            hint="我名下的 AI 会话总数"
            :icon="MessageSquareText"
            :loading="statsLoading"
        />
      </div>

      <div class="overview-grid">
        <PanelCard
            title="最近 AI 咨询"
            desc="点一条回到当时的上下文，接着问"
            :icon="MessageSquareText"
            :loading="conversationsPending"
            :error="conversationsError"
            :empty="conversationsLoaded && !conversationsError && recentConversations.length === 0"
            empty-text="还没有咨询记录"
            empty-hint="去「AI 用药咨询」问一句，这里就会出现会话"
            :rows="3"
            @retry="loadConversations"
        >
          <template #extra>
            <button type="button" class="text-link" @click="switchTab('consult')">
              <span>去咨询</span>
              <ArrowRight :size="13"/>
            </button>
          </template>

          <ul class="conv-list">
            <li v-for="item in recentConversations" :key="item.id">
              <button
                  type="button"
                  class="conv-item"
                  :title="formatExact(item.updated_at)"
                  @click="openConversation(item)"
              >
                <span class="conv-icon"><MessageSquareText :size="15"/></span>
                <span class="conv-main">
                  <span class="conv-title">{{ conversationTitle(item) }}</span>
                  <span class="conv-meta">
                    <span class="agent-chip">{{ agentName(item.agent_code) }}</span>
                    <span>{{ formatWhen(item.updated_at) }}</span>
                    <span v-if="item.message_count">· {{ item.message_count }} 条消息</span>
                  </span>
                </span>
                <ArrowRight :size="14" class="conv-arrow"/>
              </button>
            </li>
          </ul>
        </PanelCard>

        <PanelCard title="快捷入口" desc="把常用动作收敛到一屏" :icon="Zap">
          <div class="quick-list">
            <button type="button" class="quick-item" @click="router.push('/agents')">
              <span class="quick-icon"><Sparkles :size="16"/></span>
              <span class="quick-main">
                <strong>Agent 广场</strong>
                <small>看看还有哪些 Agent，以及它们各自能做什么、边界在哪</small>
              </span>
              <ArrowRight :size="14" class="quick-arrow"/>
            </button>

            <button type="button" class="quick-item" @click="switchTab('drugs')">
              <span class="quick-icon"><Pill :size="16"/></span>
              <span class="quick-main">
                <strong>药品库</strong>
                <small>新增、修改、删除药品资料与说明书</small>
              </span>
              <ArrowRight :size="14" class="quick-arrow"/>
            </button>

            <button
                type="button"
                class="quick-item"
                :class="{'is-locked': !canUseSearchTest}"
                @click="openSearchTest"
            >
              <span class="quick-icon"><LockKeyhole :size="16"/></span>
              <span class="quick-main">
                <strong>
                  检索测试台
                  <span class="lock-tag">仅管理员可用</span>
                </strong>
                <small v-if="canUseSearchTest">用不同角色身份看 RAG 召回、引用与拒答</small>
                <small v-else>医生账号点开只会看到权限提示，不会被路由守卫弹走</small>
              </span>
              <LockKeyhole v-if="!canUseSearchTest" :size="14" class="quick-arrow"/>
              <ArrowRight v-else :size="14" class="quick-arrow"/>
            </button>
          </div>
        </PanelCard>
      </div>
    </div>

    <!-- ============================ 药品库 ============================ -->
    <div v-else-if="active === 'drugs'" class="tab-panel">
      <div class="list-toolbar">
        <div class="search-box">
          <Search :size="15"/>
          <input
              v-model="productKeyword"
              type="search"
              placeholder="搜索名称 / 通用名 / 分类 / 厂家 / 批准文号"
              aria-label="搜索药品"
              @keydown.esc="productKeyword = ''"
          />
          <button
              v-if="productKeyword"
              type="button"
              class="search-clear"
              aria-label="清空搜索"
              @click="productKeyword = ''"
          >
            <X :size="13"/>
          </button>
        </div>

        <div class="toolbar-right">
          <span v-if="productsLoaded" class="list-count">
            {{ filteredProducts.length }} / {{ products.length }} 种
          </span>
          <button type="button" class="primary-btn" @click="openCreate">
            <Plus :size="14"/>
            <span>新增药品</span>
          </button>
        </div>
      </div>

      <PanelCard
          class="drug-panel"
          title="药品资料"
          desc="新增 / 编辑复用同一个表单，删除需要二次确认"
          :icon="Pill"
          :loading="productsPending"
          :error="productsError"
          :empty="productsLoaded && !productsError && filteredProducts.length === 0"
          :empty-text="drugEmptyText"
          :empty-hint="drugEmptyHint"
          :rows="5"
          flush
          @retry="loadProducts"
      >
        <div class="drug-list">
          <div class="drug-list-head">
            <span>药品</span>
            <span>分类</span>
            <span>价格</span>
            <span>库存</span>
            <span class="head-actions">操作</span>
          </div>

          <div v-for="item in filteredProducts" :key="item.id" class="drug-item">
            <div class="drug-main">
              <div class="drug-name" :title="item.name || ''">{{ item.name || '未命名药品' }}</div>
              <div class="drug-sub">
                <span v-if="item.generic_name">通用名 {{ item.generic_name }}</span>
                <span v-if="item.spec">{{ item.spec }}</span>
                <span v-if="item.manufacturer" class="drug-extra">{{ item.manufacturer }}</span>
              </div>
            </div>

            <div class="drug-category">
              <span class="cell-label">分类</span>
              <span class="chip">{{ item.category || '未分类' }}</span>
            </div>

            <div class="drug-price">
              <span class="cell-label">价格</span>
              <span class="price">¥{{ formatPrice(item.price) }}</span>
              <span v-if="hasOriginalPrice(item)" class="origin-price">¥{{ formatPrice(item.original_price) }}</span>
            </div>

            <div class="drug-stock" :class="stockTone(item.stock)">
              <span class="cell-label">库存</span>
              <span>{{ stockText(item.stock) }}</span>
            </div>

            <div class="drug-actions">
              <button type="button" class="row-btn" @click="openEdit(item)">
                <Pencil :size="13"/>
                <span>编辑</span>
              </button>
              <button
                  type="button"
                  class="row-btn is-danger"
                  :disabled="deletingId === item.id"
                  @click="removeProduct(item)"
              >
                <Trash2 :size="13"/>
                <span>{{ deletingId === item.id ? '删除中' : '删除' }}</span>
              </button>
            </div>
          </div>
        </div>
      </PanelCard>
    </div>

    <!-- ========================= AI 用药咨询 ========================= -->
    <!-- 用 v-show 保活：换 Tab 不卸载 AgentChat，SSE 流式回答不会因此断开 -->
    <div v-show="active === 'consult'" class="tab-panel consult-panel">
      <FeatureHint
          storage-key="doctor-consult"
          title="回答带引用，也有明确边界"
          text="回答带引用，可点角标看原文；知识库外的问题会拒答，涉及处方调整或严重不良反应时会提示线下就诊。"
      />

      <div class="consult-chat">
        <AgentChat v-if="consultVisited" agent-code="drug_consult" :owns-query="ownsConsultQuery"/>
      </div>
    </div>

    <!-- 弹窗常驻挂载（不包 v-if）：ProductFormModal 靠 watch(isOpen) 填充表单，
         如果带着 isOpen=true 才首次挂载，watch 不会触发，编辑态会是空表单 -->
    <ProductFormModal
        v-model:agent-text="productAgentText"
        :is-open="productModalOpen"
        :is-edit="productEditMode"
        :initial-data="productFormData"
        @close="closeProductModal"
        @save="handleProductSave"
    />
  </WorkbenchShell>
</template>

<style scoped lang="scss">
/* 顶部操作：与外壳的刷新按钮同风格，避免两个按钮抢视觉焦点 */
.head-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 999px;
  background: #fff;
  color: #6b7280;
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;

  &:hover {
    border-color: #fecaca;
    color: #b91c1c;
  }
}

.tab-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}

.inline-error {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid #fecaca;
  border-radius: 10px;
  background: #fef2f2;
  color: #b91c1c;
  font-size: 12.5px;
  line-height: 1.6;

  > span {
    flex: 1;
    min-width: 0;
    word-break: break-word;
  }

  .inline-retry {
    flex-shrink: 0;
    padding: 3px 12px;
    border: 1px solid #fca5a5;
    border-radius: 999px;
    background: #fff;
    color: #b91c1c;
    font-family: inherit;
    font-size: 12px;
    cursor: pointer;

    &:hover {
      background: #fff7f7;
    }
  }
}

/* 4 张指标卡：桌面一行，平板两列，手机单列（避免数字被压成两行） */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.overview-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}

/* ---------------- 最近会话 ---------------- */

.text-link {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 0;
  border: none;
  background: transparent;
  color: #6b7280;
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;

  &:hover {
    color: #dc2626;
  }
}

.conv-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.conv-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 10px 0;
  border: none;
  border-bottom: 1px solid #f3f4f6;
  background: transparent;
  text-align: left;
  font-family: inherit;
  cursor: pointer;

  &:hover {
    .conv-title {
      color: #dc2626;
    }

    .conv-arrow {
      color: #fca5a5;
    }
  }
}

.conv-list li:last-child .conv-item {
  border-bottom: none;
  padding-bottom: 2px;
}

.conv-icon {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  border-radius: 9px;
  background: #fef2f2;
  color: #dc2626;
}

.conv-main {
  display: flex;
  flex-direction: column;
  gap: 3px;
  flex: 1;
  min-width: 0;
}

.conv-title {
  font-size: 13px;
  font-weight: 600;
  color: #111827;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: color 0.15s;
}

.conv-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #9ca3af;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;

  .agent-chip {
    flex-shrink: 0;
    padding: 0 6px;
    border-radius: 5px;
    background: #f3f4f6;
    color: #6b7280;
    font-size: 10.5px;
    line-height: 16px;
  }
}

.conv-arrow {
  flex-shrink: 0;
  color: #d1d5db;
  transition: color 0.15s;
}

/* ---------------- 快捷入口 ---------------- */

.quick-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.quick-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  width: 100%;
  padding: 10px;
  border: 1px solid #f3f4f6;
  border-radius: 10px;
  background: #fcfcfd;
  text-align: left;
  font-family: inherit;
  cursor: pointer;
  transition: border-color 0.15s, background-color 0.15s;

  &:hover {
    border-color: #fecaca;
    background: #fff7f7;
  }

  &.is-locked {
    background: #fafafa;
  }
}

.quick-icon {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  border-radius: 9px;
  background: #f3f4f6;
  color: #4b5563;
}

.quick-item:hover .quick-icon {
  background: #fef2f2;
  color: #dc2626;
}

.quick-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;

  strong {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
    font-size: 12.5px;
    color: #111827;
  }

  small {
    font-size: 11px;
    line-height: 1.55;
    color: #9ca3af;
  }
}

.lock-tag {
  padding: 0 5px;
  border: 1px solid #fecaca;
  border-radius: 4px;
  background: #fef2f2;
  color: #b91c1c;
  font-size: 10px;
  font-weight: 500;
  line-height: 15px;
}

.quick-arrow {
  flex-shrink: 0;
  margin-top: 8px;
  color: #d1d5db;
}

/* ---------------- 药品库工具条 ---------------- */

.list-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 14px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #fff;
}

.search-box {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  max-width: 440px;
  height: 34px;
  padding: 0 10px;
  border: 1px solid #e5e7eb;
  border-radius: 999px;
  background: #f9fafb;
  color: #9ca3af;
  transition: border-color 0.15s, background-color 0.15s, box-shadow 0.15s;

  &:focus-within {
    border-color: #fca5a5;
    background: #fff;
    box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.08);
  }

  input {
    flex: 1;
    min-width: 0;
    border: none;
    outline: none;
    background: transparent;
    color: #374151;
    font-family: inherit;
    font-size: 12.5px;

    &::placeholder {
      color: #9ca3af;
    }

    &::-webkit-search-cancel-button {
      display: none;
    }
  }
}

.search-clear {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: #e5e7eb;
  color: #6b7280;
  cursor: pointer;

  &:hover {
    background: #fecaca;
    color: #b91c1c;
  }
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;

  .list-count {
    color: #9ca3af;
    font-size: 11.5px;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
}

.primary-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  height: 34px;
  padding: 0 14px;
  border: none;
  border-radius: 999px;
  background: linear-gradient(135deg, #ef4444, #dc2626);
  color: #fff;
  font-family: inherit;
  font-size: 12.5px;
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
  box-shadow: 0 4px 12px -6px rgba(239, 68, 68, 0.7);

  &:hover {
    background: linear-gradient(135deg, #dc2626, #b91c1c);
  }

  &:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
}

/* ---------------- 药品列表（桌面表格） ---------------- */

.drug-list {
  display: flex;
  flex-direction: column;
}

.drug-list-head,
.drug-item {
  display: grid;
  grid-template-columns: minmax(0, 2.4fr) minmax(0, 1fr) 96px 72px 132px;
  gap: 12px;
  align-items: center;
  padding: 10px 18px;
}

.drug-list-head {
  background: #fafafa;
  border-bottom: 1px solid #f3f4f6;
  color: #9ca3af;
  font-size: 11px;

  .head-actions {
    text-align: right;
  }
}

.drug-item {
  border-bottom: 1px solid #f3f4f6;
  transition: background-color 0.15s;

  &:last-child {
    border-bottom: none;
  }

  &:hover {
    background: #fffbfb;
  }
}

.drug-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.drug-name {
  color: #111827;
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.drug-sub {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  color: #9ca3af;
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;

  > span {
    flex-shrink: 0;
  }

  .drug-extra {
    flex-shrink: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }
}

.drug-category {
  min-width: 0;
}

.chip {
  display: inline-block;
  max-width: 100%;
  padding: 1px 8px;
  border-radius: 6px;
  background: #f3f4f6;
  color: #6b7280;
  font-size: 11px;
  line-height: 18px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.drug-price {
  display: flex;
  align-items: baseline;
  gap: 5px;
  min-width: 0;

  .price {
    color: #111827;
    font-size: 13px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }

  .origin-price {
    color: #9ca3af;
    font-size: 11px;
    text-decoration: line-through;
    font-variant-numeric: tabular-nums;
  }
}

.drug-stock {
  color: #374151;
  font-size: 12.5px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;

  &.is-low {
    color: #d97706;
  }

  &.is-out {
    color: #dc2626;
    font-weight: 600;
  }
}

.cell-label {
  display: none;
}

.drug-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  white-space: nowrap;
}

.row-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  height: 26px;
  padding: 0 8px;
  border: 1px solid #e5e7eb;
  border-radius: 7px;
  background: #fff;
  color: #4b5563;
  font-family: inherit;
  font-size: 11.5px;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s, background-color 0.15s;

  &:hover:not(:disabled) {
    border-color: #fecaca;
    background: #fff7f7;
    color: #b91c1c;
  }

  &.is-danger {
    border-color: #fecaca;
    background: #fef2f2;
    color: #b91c1c;
  }

  &:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
}

/* PanelCard 的 flush 模式下去掉内边距，错误 / 空态需要自己补一点呼吸空间 */
.drug-panel :deep(.panel-state) {
  padding: 30px 16px;
}

/* ---------------- AI 用药咨询 ---------------- */

.consult-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: calc(100vh - 400px);
  min-height: 480px;
  max-height: 920px;

  .consult-chat {
    display: flex;
    flex: 1;
    min-height: 0;

    > * {
      flex: 1;
      min-height: 0;
    }
  }
}

/* ---------------- 响应式 ---------------- */

@media (max-width: 1024px) {
  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .overview-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .stat-grid {
    grid-template-columns: 1fr;
  }

  .list-toolbar {
    flex-wrap: wrap;
    padding: 10px 12px;
  }

  .search-box {
    max-width: none;
    width: 100%;
  }

  .toolbar-right {
    justify-content: space-between;
    width: 100%;
  }

  /* 表格切卡片：五列在窄屏会被挤到换行，改成上下分区更好读 */
  .drug-list-head {
    display: none;
  }

  .drug-list {
    gap: 8px;
    padding: 10px;
  }

  .drug-item {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px 14px;
    padding: 12px;
    border: 1px solid #f3f4f6;
    border-radius: 10px;
    background: #fff;
  }

  .drug-item:last-child {
    border-bottom: 1px solid #f3f4f6;
  }

  .drug-main {
    flex: 1 1 100%;
  }

  .drug-category,
  .drug-price,
  .drug-stock {
    display: flex;
    align-items: center;
    gap: 5px;
  }

  .cell-label {
    display: inline;
    color: #9ca3af;
    font-size: 10.5px;
    font-weight: 400;
  }

  .drug-actions {
    flex: 1 1 100%;
    justify-content: flex-end;
    padding-top: 7px;
    border-top: 1px dashed #f3f4f6;
  }

  .row-btn {
    height: 28px;
    padding: 0 10px;
  }

  .consult-panel {
    height: calc(100vh - 430px);
    min-height: 360px;
    max-height: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .drug-item,
  .row-btn,
  .quick-item {
    transition: none;
  }
}
</style>
