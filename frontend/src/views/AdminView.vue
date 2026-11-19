<script setup>
// KeepAlive 依赖组件名（App.vue 的 CACHED 白名单按 name 匹配）
defineOptions({name: 'AdminView'})

/**
 * 管理员工作台：把「系统现在怎么样」和「今天该处理什么」放在首屏。
 *
 * 之前这里是写死的假数字（1,284 用户 / 56 订单），面试官一问数据来源就露馅。
 * 现在三个 Tab 全部接真实接口：
 *   总览 → 指标 + 7 日趋势 + 待办（点进去就是能处理的地方）
 *   质量 → 合规拦截明细 + 差评 + 导出为评估集候选
 *   系统 → 依赖状态 + 配置快照（解释「为什么召回是 0.94」）
 *
 * 深度操作（知识库、检索测试台、Prompt 版本、评估详情）仍然是独立页面：
 * 它们有编辑态和长列表，塞进工作台只会让两边的交互都变差，这里只放入口和摘要。
 */
import {computed, onActivated, onMounted, ref, watch} from 'vue'
import {useRouter} from 'vue-router'
import dayjs from 'dayjs'
import {showConfirmDialog, showToast} from 'vant'
import {
  Activity,
  AlertTriangle,
  BookOpen,
  ChevronRight,
  Database,
  Download,
  FileCode2,
  Gauge,
  Layers,
  MessageSquare,
  Package,
  Search,
  Server,
  ShieldAlert,
  Sparkles,
  ThumbsDown,
  Timer,
  Wallet
} from 'lucide-vue-next'
import WorkbenchShell from '../components/workbench/WorkbenchShell.vue'
import PanelCard from '../components/workbench/PanelCard.vue'
import StatCard from '../components/workbench/StatCard.vue'
import FeatureHint from '../components/workbench/FeatureHint.vue'
import OrderCard from '../components/order/OrderCard.vue'
import {exportFeedback, fetchOverview, fetchRecent} from '../api/observe'
import {getAdminOrdersApi, shipOrderApi} from '../api/order'
import {fetchSystemStatus} from '../api/workbench'
import {ORDER_FILTERS, shortOrderId} from '../utils/orderStatus'
import {openGuide} from '../store/guide'

const router = useRouter()

const TABS = [
  {key: 'overview', label: '总览', icon: Gauge},
  {key: 'orders', label: '订单', icon: Package},
  {key: 'quality', label: '质量', icon: ShieldAlert},
  {key: 'system', label: '系统', icon: Server}
]

const WINDOWS = [
  {key: 7, label: '近 7 天'},
  {key: 14, label: '近 14 天'},
  {key: 30, label: '近 30 天'}
]

const active = ref('overview')
const days = ref(7)

// 模板里不要直接给 ref 赋值（script setup 下容易踩 TDZ / 响应式丢失），统一走方法
const setWindow = (key) => {
  if (days.value !== key) days.value = key
}
const refreshing = ref(false)
const updatedAt = ref('')

const overview = ref(null)
const overviewLoading = ref(false)
const overviewError = ref('')

const recent = ref([])
const recentLoading = ref(false)
const recentError = ref('')

const system = ref(null)
const systemLoading = ref(false)
const systemError = ref('')

/* ------------------------------------------------------------------ *
 * 订单管理（M5 补：之前后台完全没有「看全部订单 / 发货」的入口）
 * ------------------------------------------------------------------ */

const adminOrders = ref([])
const orderCounts = ref({})
const ordersTotal = ref(0)
const pendingShip = ref(0)
const ordersLoading = ref(false)
const ordersError = ref('')
const orderFilter = ref('all')
const shippingId = ref('')

const loadOrders = async () => {
  ordersLoading.value = true
  ordersError.value = ''
  try {
    const data = await getAdminOrdersApi({
      status: orderFilter.value === 'all' ? '' : orderFilter.value,
      limit: 60
    })
    adminOrders.value = Array.isArray(data.items) ? data.items : []
    orderCounts.value = (data && data.counts) || {}
    ordersTotal.value = Number(data && data.total) || 0
    pendingShip.value = Number(data && data.pending_ship) || 0
  } catch (e) {
    ordersError.value = e && e.status === 403
        ? '仅管理员可用，请用 admin 登录'
        : (e && e.message) || '订单加载失败'
  } finally {
    ordersLoading.value = false
  }
}

const setOrderFilter = (key) => {
  if (orderFilter.value === key) return
  orderFilter.value = key
  loadOrders()
}

const handleShip = async (order) => {
  if (!order || shippingId.value) return
  try {
    await showConfirmDialog({
      title: '模拟发货',
      message: `把订单 ${shortOrderId(order.id)} 标记为「已发货」？患者端会立刻看到「待收货」。`,
      confirmButtonText: '发货',
      confirmButtonColor: '#dc2626'
    })
  } catch (e) {
    return
  }
  shippingId.value = order.id
  try {
    await shipOrderApi(order.id)
    showToast('已发货（模拟）')
    // 发货后列表状态与「待发货」计数都会变，一起刷新
    await Promise.allSettled([loadOrders(), loadOverview()])
  } catch (e) {
    showToast({type: 'fail', message: (e && e.message) || '发货失败'})
  } finally {
    shippingId.value = ''
  }
}

/* ------------------------------------------------------------------ *
 * Tab 与 URL 同步：刷新 / 分享能回到同一屏
 * ------------------------------------------------------------------ */

const readTabFromUrl = () => {
  const value = String(new URLSearchParams(window.location.search).get('tab') || '')
  return TABS.some((tab) => tab.key === value) ? value : 'overview'
}

const setTab = (key) => {
  if (!TABS.some((tab) => tab.key === key)) return
  active.value = key
  const query = {...router.currentRoute.value.query, tab: key}
  router.replace({path: '/admin', query})
}

/* ------------------------------------------------------------------ *
 * 数据加载
 * ------------------------------------------------------------------ */

const loadOverview = async () => {
  overviewLoading.value = true
  overviewError.value = ''
  try {
    overview.value = await fetchOverview(days.value)
  } catch (e) {
    overviewError.value = e && e.status === 403 ? '仅管理员可用，请用 admin 登录' : (e && e.message) || '指标加载失败'
  } finally {
    overviewLoading.value = false
  }
}

const loadRecent = async () => {
  recentLoading.value = true
  recentError.value = ''
  try {
    recent.value = await fetchRecent(30)
  } catch (e) {
    recentError.value = (e && e.message) || '最近对话加载失败'
  } finally {
    recentLoading.value = false
  }
}

const loadSystem = async () => {
  systemLoading.value = true
  systemError.value = ''
  try {
    system.value = await fetchSystemStatus()
  } catch (e) {
    systemError.value = (e && e.message) || '系统状态加载失败'
  } finally {
    systemLoading.value = false
  }
}

const touch = () => {
  updatedAt.value = dayjs().format('HH:mm:ss')
}

const refreshAll = async () => {
  refreshing.value = true
  const jobs = [loadOverview(), loadRecent()]
  if (active.value === 'system') jobs.push(loadSystem())
  if (active.value === 'orders') jobs.push(loadOrders())
  await Promise.allSettled(jobs)
  refreshing.value = false
  touch()
}

watch(active, (key) => {
  if (key === 'system' && !system.value && !systemLoading.value) loadSystem()
  if (key === 'orders') loadOrders()
})

watch(days, () => loadOverview())

onMounted(async () => {
  active.value = readTabFromUrl()
  await Promise.allSettled([loadOverview(), loadRecent()])
  if (active.value === 'system') await loadSystem()
  if (active.value === 'orders') await loadOrders()
  touch()
})

// AdminView 在 KeepAlive 白名单里：从订单详情返回时列表要重拉（可能刚发过货）
let activatedOnce = false
onActivated(() => {
  if (!activatedOnce) {
    activatedOnce = true
    return
  }
  if (active.value === 'orders') loadOrders()
})

/* ------------------------------------------------------------------ *
 * 展示格式：接口给原始值，格式化只发生在这里
 * ------------------------------------------------------------------ */

const pct = (value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  return `${(Number(value) * 100).toFixed(1)}%`
}

const ms = (value) => {
  const n = Number(value || 0)
  if (!n) return '—'
  return n >= 1000 ? `${(n / 1000).toFixed(1)}s` : `${n}ms`
}

const money = (value) => `¥${Number(value || 0).toFixed(2)}`

const quality = computed(() => (overview.value && overview.value.quality) || {})
const totals = computed(() => (overview.value && overview.value.totals) || {})
const latency = computed(() => (overview.value && overview.value.latency) || {})
const cost = computed(() => (overview.value && overview.value.cost) || {})
const guardrail = computed(() => (overview.value && overview.value.guardrail) || {})
const todos = computed(() => (overview.value && overview.value.todos) || [])
const agents = computed(() => (overview.value && overview.value.agents) || [])
const evalInfo = computed(() => (overview.value && overview.value.eval) || {available: false})
const trend = computed(() => (overview.value && overview.value.trend) || [])

const trendMax = computed(() => Math.max(1, ...trend.value.map((item) => item.turns)))

const kindRows = computed(() => Object.entries(guardrail.value.by_kind || {}).sort((a, b) => b[1] - a[1]))
const kindMax = computed(() => Math.max(1, ...kindRows.value.map(([, value]) => value)))
const flagRows = computed(() => Object.entries(guardrail.value.by_flag || {}).sort((a, b) => b[1] - a[1]))

const downFeedback = computed(() =>
  recent.value.filter((row) => (row.feedback || {}).rating === 'down')
)

const pendingTodos = computed(() => todos.value.filter((item) => Number(item.value) > 0))

const DEEP_LINKS = [
  // 药品库：AI 录入 + 上传主图都在这里（之前后台找不到入口）
  {to: '/products', title: '药品库管理', desc: '录入药品、上传主图、改价格库存', icon: Package},
  {to: '/admin/kb', title: '知识库后台', desc: '上传 / 解析 / 切片 / 重建索引', icon: Database},
  {to: '/admin/kb/search-test', title: '检索测试台', desc: '看召回、重排与被丢掉的片段', icon: Search},
  {to: '/admin/prompts', title: 'Prompt 版本', desc: '版本表、灰度、预览与回滚', icon: FileCode2},
  {to: '/admin/observe', title: '完整观测页', desc: '逐日趋势、口径说明、原始记录', icon: Activity}
]

const downloadFeedback = async () => {
  try {
    const rows = await exportFeedback(30, 'down')
    if (!rows.length) {
      showToast('近 30 天没有差评')
      return
    }
    const blob = new Blob([JSON.stringify(rows, null, 2)], {type: 'application/json'})
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `hhyy-feedback-down-${dayjs().format('YYYYMMDD')}.json`
    link.click()
    URL.revokeObjectURL(url)
    showToast(`已导出 ${rows.length} 条`)
  } catch (e) {
    showToast((e && e.message) || '导出失败')
  }
}
</script>

<template>
  <WorkbenchShell
      role="admin"
      role-label="管理员"
      title="管理员工作台"
      subtitle="Agent 运行状况、输出治理与系统依赖，一屏看完。"
      :tabs="TABS"
      :active="active"
      :refreshing="refreshing"
      :updated-at="updatedAt"
      @update:active="setTab"
      @refresh="refreshAll"
  >
    <template #actions>
      <div class="window-picker">
        <button
            v-for="item in WINDOWS"
            :key="item.key"
            type="button"
            class="window-btn"
            :class="{ 'is-active': days === item.key }"
            @click="setWindow(item.key)"
        >
          {{ item.label }}
        </button>
      </div>
    </template>

    <!-- ============================ 总览 ============================ -->
    <template v-if="active === 'overview'">
      <FeatureHint
          title="这块在展示什么"
          text="8 个指标全部由 messages / conversations / handoff_tickets 聚合而来，口径写在完整观测页里；待办点一下就能去处理。"
          :tags="[{label: '输出治理', key: 'guardrail'}, {label: '可评估', key: 'eval'}]"
          storage-key="admin.overview"
          @tag-click="openGuide('thinking')"
      />

      <div class="stat-grid">
        <StatCard label="会话数" :value="totals.conversations ?? '—'" hint="窗口内新建" :loading="overviewLoading" :icon="MessageSquare" tone="primary"/>
        <StatCard label="回答轮次" :value="totals.turns ?? '—'" hint="非空回答" :loading="overviewLoading" :icon="Layers"/>
        <StatCard label="P95 耗时" :value="ms(latency.p95_ms)" :hint="`P50 ${ms(latency.p50_ms)}`" :loading="overviewLoading" :icon="Timer" :tone="(latency.p95_ms || 0) > 15000 ? 'warn' : 'default'"/>
        <StatCard label="拒答率" :value="pct(quality.refusal_rate)" hint="低分/库外" :loading="overviewLoading" :icon="AlertTriangle"/>
        <StatCard label="引用率" :value="pct(quality.citation_rate)" hint="带可溯源引用" :loading="overviewLoading" :icon="BookOpen" tone="ok"/>
        <StatCard label="治理拦截" :value="guardrail.violations ?? 0" hint="改写/裁剪/拒答" :loading="overviewLoading" :icon="ShieldAlert" :tone="(guardrail.violations || 0) > 0 ? 'warn' : 'ok'"/>
        <StatCard label="估算成本" :value="money(cost.cost_cny)" :hint="`均 ${money(cost.avg_cost_per_turn_cny)}/轮`" :loading="overviewLoading" :icon="Wallet"/>
        <StatCard label="差评" :value="quality.feedback_down ?? 0" :hint="`好评 ${quality.feedback_up ?? 0}`" :loading="overviewLoading" :icon="ThumbsDown" :tone="(quality.feedback_down || 0) > 0 ? 'danger' : 'ok'"/>
      </div>

      <div class="two-col">
        <PanelCard
            title="待办"
            desc="只列数量 > 0 的项，点进去就是处理入口"
            :icon="AlertTriangle"
            :loading="overviewLoading"
            :error="overviewError"
            :empty="!pendingTodos.length"
            empty-text="没有待处理事项"
            empty-hint="排队工单、差评、治理拦截、失败文档都是 0"
            @retry="loadOverview"
        >
          <ul class="todo-list">
            <!-- 这行是 li 但行为是跳转：补 role/tabindex/回车支持 + 右侧箭头，
                 否则用户和键盘用户都看不出它能点 -->
            <li
                v-for="item in pendingTodos"
                :key="item.key"
                class="todo-row"
                role="button"
                tabindex="0"
                @click="router.push(item.to)"
                @keydown.enter.prevent="router.push(item.to)"
                @keydown.space.prevent="router.push(item.to)"
            >
              <span class="todo-dot" :class="`tone-${item.tone}`"/>
              <div class="todo-body">
                <strong>{{ item.label }}</strong>
                <small :title="item.note">{{ item.note }}</small>
              </div>
              <span class="todo-value">{{ item.value }}</span>
              <ChevronRight :size="14" class="todo-arrow"/>
            </li>
          </ul>
        </PanelCard>

        <PanelCard
            title="逐日趋势"
            :desc="`近 ${overview?.window_days || days} 天回答轮次（红点为拒答）`"
            :icon="Activity"
            :loading="overviewLoading"
            :error="overviewError"
            :empty="!trend.length"
            empty-text="窗口内没有数据"
            @retry="loadOverview"
        >
          <div class="trend">
            <div v-for="item in trend" :key="item.date" class="trend-col" :title="`${item.date}：${item.turns} 轮 / 拒答 ${item.refusals}`">
              <div class="trend-bar-wrap">
                <div class="trend-bar" :style="{ height: `${Math.max(4, (item.turns / trendMax) * 100)}%` }"/>
                <span v-if="item.refusals" class="trend-dot"/>
              </div>
              <small>{{ item.date.slice(5) }}</small>
            </div>
          </div>
        </PanelCard>
      </div>

      <div class="two-col">
        <PanelCard
            title="各 Agent 表现"
            desc="谁在被用、谁在拒答"
            :icon="Sparkles"
            :loading="overviewLoading"
            :error="overviewError"
            :empty="!agents.length"
            empty-text="窗口内没有 Agent 调用"
            @retry="loadOverview"
        >
          <div class="table-scroll">
            <table class="mini-table">
              <thead>
              <tr>
                <th>Agent</th>
                <th>轮次</th>
                <th>拒答率</th>
                <th>平均耗时</th>
              </tr>
              </thead>
              <tbody>
              <tr v-for="row in agents" :key="row.code">
                <td :title="row.code">{{ row.code }}</td>
                <td>{{ row.turns }}</td>
                <td>{{ pct(row.refusal_rate) }}</td>
                <td>{{ ms(row.avg_latency_ms) }}</td>
              </tr>
              </tbody>
            </table>
          </div>
        </PanelCard>

        <PanelCard
            title="最近一次评估"
            desc="50 条 golden set 的一条命令结果"
            :icon="Gauge"
            :loading="overviewLoading"
            :error="overviewError"
            :empty="!evalInfo.available"
            empty-text="还没有跑过评估"
            empty-hint="在 backend 目录执行 python ../tests/eval/run_eval.py"
            @retry="loadOverview"
        >
          <div class="eval-grid">
            <div class="eval-item"><small>召回@5</small><b>{{ pct(evalInfo.recall_at_5) }}</b></div>
            <div class="eval-item"><small>MRR</small><b>{{ evalInfo.mrr ?? '—' }}</b></div>
            <div class="eval-item"><small>拒答准确率</small><b>{{ pct(evalInfo.refusal_accuracy) }}</b></div>
            <div class="eval-item"><small>引用准确率</small><b>{{ pct(evalInfo.citation_precision) }}</b></div>
            <div class="eval-item"><small>失败用例</small><b>{{ evalInfo.failures ?? '—' }}</b></div>
            <div class="eval-item"><small>用例数</small><b>{{ evalInfo.cases ?? '—' }}</b></div>
          </div>
          <p class="eval-foot">运行于 {{ evalInfo.ran_at ? dayjs(evalInfo.ran_at).format('MM-DD HH:mm') : '—' }}</p>
        </PanelCard>
      </div>

      <PanelCard title="深度操作" desc="这些页面有编辑态与长列表，工作台只给入口和摘要" :icon="Database" :rows="1">
        <div class="deep-grid">
          <!-- 已经是 button，a11y 不用补；但纯图标 + 文字的卡片看不出「会跳走」，
               所以右侧统一给箭头，和纯展示卡片区分开 -->
          <button v-for="item in DEEP_LINKS" :key="item.to" type="button" class="deep-card" @click="router.push(item.to)">
            <component :is="item.icon" :size="16"/>
            <div class="deep-card-body">
              <strong>{{ item.title }}</strong>
              <small :title="item.desc">{{ item.desc }}</small>
            </div>
            <ChevronRight :size="14" class="deep-card-arrow"/>
          </button>
        </div>
      </PanelCard>
    </template>

    <!-- ============================ 质量 ============================ -->
    <template v-else-if="active === 'quality'">
      <FeatureHint
          title="治理层的三个动作"
          text="合规改写（根治 → 缓解）、引用裁剪（编造的角标直接删）、免责声明注入。负向指标不追求 0，而是「拦截了但回答还在」。"
          :tags="[{label: '为什么拒答做在检索层', key: 'refusal'}, {label: '流式改写为什么要扣尾', key: 'stream'}]"
          storage-key="admin.quality"
          @tag-click="openGuide('thinking')"
      />

      <div class="two-col">
        <PanelCard
            title="拦截类型分布"
            desc="按 violation.kind 聚合"
            :icon="ShieldAlert"
            :loading="overviewLoading"
            :error="overviewError"
            :empty="!kindRows.length"
            empty-text="窗口内没有拦截"
            @retry="loadOverview"
        >
          <ul class="bar-list">
            <li v-for="[kind, count] in kindRows" :key="kind">
              <div class="bar-head"><span :title="kind">{{ kind }}</span><b>{{ count }}</b></div>
              <div class="bar-track">
                <span :style="{ width: `${(count / kindMax) * 100}%` }"/>
              </div>
            </li>
          </ul>
          <div v-if="flagRows.length" class="flag-row">
            <span v-for="[flag, count] in flagRows" :key="flag" class="flag-chip" :title="flag">{{ flag }} · {{ count }}</span>
          </div>
        </PanelCard>

        <PanelCard
            title="差评"
            desc="可导出为 golden set 候选"
            :icon="ThumbsDown"
            :loading="recentLoading"
            :error="recentError"
            :empty="!downFeedback.length"
            empty-text="近期没有差评"
            empty-hint="在对话里点 👎 就会出现在这里"
            @retry="loadRecent"
        >
          <template #extra>
            <button type="button" class="ghost-btn" @click="downloadFeedback">
              <Download :size="13"/>
              导出
            </button>
          </template>
          <ul class="feedback-list">
            <li v-for="row in downFeedback.slice(0, 6)" :key="row.message_id">
              <p class="feedback-q" :title="row.question || '（无问题快照）'">Q：{{ row.question || '（无问题快照）' }}</p>
              <p class="feedback-a">{{ (row.answer || '').slice(0, 80) }}…</p>
              <div class="feedback-meta">
                <span>{{ row.agent_code || 'unknown' }}</span>
                <span>{{ row.feedback?.reason || '未填原因' }}</span>
                <span>{{ row.created_at ? dayjs(row.created_at).format('MM-DD HH:mm') : '' }}</span>
              </div>
            </li>
          </ul>
          <p v-if="!downFeedback.length && recentLoading === false" class="hint-note">
            支持在任意 AI 回答底部点 👎 并选择原因，记录会落库到 messages.feedback。
          </p>
        </PanelCard>
      </div>

      <PanelCard
          title="最近的治理记录"
          desc="每条都能定位到具体回答（message_id）"
          :icon="AlertTriangle"
          :loading="recentLoading"
          :error="recentError"
          :empty="!(guardrail.recent || []).length"
          empty-text="窗口内没有被拦截的回答"
          @retry="loadRecent"
          flush
      >
        <ul class="violation-list">
          <li v-for="row in guardrail.recent || []" :key="row.message_id">
            <div class="violation-top">
              <span class="violation-kind" :title="row.violation || 'guardrail'">{{ row.violation || 'guardrail' }}</span>
              <span class="violation-agent" :title="row.agent_code || 'unknown'">{{ row.agent_code || 'unknown' }}</span>
              <span class="violation-time">{{ row.at ? dayjs(row.at).format('MM-DD HH:mm') : '' }}</span>
            </div>
            <div class="violation-flags">
              <span v-for="flag in row.flags || []" :key="flag">{{ flag }}</span>
            </div>
          </li>
        </ul>
      </PanelCard>

      <PanelCard title="指标口径" desc="看板数字和 Langfuse 对不上时，先看这里" :icon="BookOpen" :rows="1">
        <dl class="definition-list">
          <template v-for="(text, key) in overview?.links?.definitions || {}" :key="key">
            <dt>{{ key }}</dt>
            <dd>{{ text }}</dd>
          </template>
        </dl>
      </PanelCard>
    </template>

    <!-- ============================ 系统 ============================ -->
    <template v-else-if="active === 'system'">
      <FeatureHint
          title="这页回答两个问题"
          text="依赖真的通了吗？为什么这台机器的召回是 0.94？——组件状态与配置快照都摊开，不显示假绿灯。"
          :tags="[{label: '为什么三层记忆', key: 'memory'}]"
          storage-key="admin.system"
          @tag-click="openGuide('thinking')"
      />

      <div class="two-col">
        <PanelCard
            title="依赖状态"
            desc="每 30 秒可手动刷新"
            :icon="Server"
            :loading="systemLoading"
            :error="systemError"
            :empty="!system"
            empty-text="没有拿到状态"
            @retry="loadSystem"
        >
          <ul class="component-list">
            <li v-for="item in system?.components || []" :key="item.key">
              <span class="dot" :class="{ ok: item.ok }"/>
              <span class="component-label">{{ item.label }}</span>
              <span class="component-state" :class="{ ok: item.ok }">{{ item.ok ? '正常' : '不可用' }}</span>
            </li>
          </ul>
          <p class="hint-note">Langfuse 没有配置 key 时显示不可用是预期行为，不影响对话。</p>
        </PanelCard>

        <PanelCard
            title="运行时配置"
            desc="模型、维度、阈值、灰度开关"
            :icon="Sparkles"
            :loading="systemLoading"
            :error="systemError"
            :empty="!system"
            empty-text="没有拿到配置"
            @retry="loadSystem"
        >
          <dl class="config-list">
            <template v-for="(value, key) in system?.config || {}" :key="key">
              <dt>{{ key }}</dt>
              <dd>{{ typeof value === 'boolean' ? (value ? '开启' : '关闭') : value }}</dd>
            </template>
          </dl>
        </PanelCard>
      </div>
    </template>
    <template v-else-if="active === 'orders'">
      <!-- ============================ 订单 ============================ -->
      <FeatureHint
          title="这里能做什么"
          text="患者下单后状态是「待发货」，点「模拟发货」变成「待收货」，患者确认收货后归「已完成」。真实项目里发货由 WMS 回调，这里用一个按钮模拟同一条状态机。"
          :tags="[{label: '为什么发货要校验状态', key: 'state'}]"
          storage-key="admin.orders"
          @tag-click="openGuide('thinking')"
      />

      <div class="stat-grid">
        <StatCard label="待发货" :value="pendingShip" unit="单" hint="需要点发货" :loading="ordersLoading" :icon="Package" :tone="pendingShip > 0 ? 'warn' : 'ok'"/>
        <StatCard label="订单总数" :value="ordersTotal" unit="单" hint="全部状态" :loading="ordersLoading" :icon="Layers"/>
        <StatCard label="当前筛选" :value="adminOrders.length" unit="单" hint="列表内条数" :loading="ordersLoading" :icon="Search"/>
        <StatCard label="在途" :value="orderCounts.shipped || 0" unit="单" hint="已发货待收货" :loading="ordersLoading" :icon="Package" tone="ok"/>
      </div>

      <div class="order-filters">
        <button
            v-for="item in ORDER_FILTERS"
            :key="item.key"
            type="button"
            class="filter-btn"
            :class="{ 'is-active': orderFilter === item.key }"
            @click="setOrderFilter(item.key)"
        >
          {{ item.label }}
          <span v-if="item.key !== 'all' && orderCounts[item.key]" class="filter-count">
            {{ orderCounts[item.key] }}
          </span>
        </button>
      </div>

      <PanelCard
          title="全部订单"
          desc="按状态筛选；「模拟发货」只对「待发货」的订单可点"
          :icon="Package"
          :loading="ordersLoading"
          :error="ordersError"
          :empty="adminOrders.length === 0"
          empty-text="没有符合筛选的订单"
          empty-hint="用患者账号下一单，这里就会出现"
          @retry="loadOrders"
      >
        <div class="order-stack">
          <OrderCard
              v-for="order in adminOrders"
              :key="order.id"
              mode="admin"
              show-user
              :order="order"
              :mutating="shippingId === order.id"
              @ship="handleShip"
              @open="router.push(`/orders/${order.id}`)"
          />
        </div>
      </PanelCard>
    </template>
  </WorkbenchShell>
</template>

<style scoped lang="scss">
.window-picker {
  display: inline-flex;
  padding: 2px;
  border: 1px solid #e5e7eb;
  border-radius: 999px;
  background: #fff;

  .window-btn {
    padding: 4px 10px;
    border: none;
    border-radius: 999px;
    background: transparent;
    color: #6b7280;
    font-size: 12px;
    cursor: pointer;

    &.is-active {
      background: #fef2f2;
      color: #b91c1c;
      font-weight: 600;
    }
  }
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.two-col {
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr);
  gap: 14px;
}

/* ---------------- 待办 ---------------- */
.todo-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;

  .todo-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px;
    border-radius: 8px;
    cursor: pointer;
    transition: background 0.16s;

    &:hover {
      background: #f9fafb;
    }

    /* role=button 的 li 必须有可见焦点，键盘用户才知道当前在哪一行 */
    &:focus-visible {
      outline: 2px solid #fca5a5;
      outline-offset: 1px;
    }

    .todo-arrow {
      flex-shrink: 0;
      color: #9ca3af;
    }
  }

  .todo-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #d1d5db;
    flex-shrink: 0;

    &.tone-warn {
      background: #f59e0b;
    }

    &.tone-danger {
      background: #ef4444;
    }

    &.tone-ok {
      background: #10b981;
    }
  }

  .todo-body {
    flex: 1;
    min-width: 0;

    strong {
      display: block;
      font-size: 13px;
      color: #111827;
      overflow-wrap: anywhere;
      word-break: break-word;
    }

    small {
      display: -webkit-box;
      font-size: 11px;
      color: #9ca3af;
      /* 说明文案可能是一整句：最多两行，全文在 title 里 */
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      overflow-wrap: anywhere;
      word-break: break-word;
    }
  }

  .todo-value {
    flex-shrink: 0;
    font-size: 16px;
    font-weight: 700;
    color: #b91c1c;
  }
}

/* ---------------- 趋势 ---------------- */
.trend {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  height: 120px;
  min-width: 0;
  padding-top: 4px;

  .trend-col {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    min-width: 0;
  }

  .trend-bar-wrap {
    position: relative;
    width: 100%;
    height: 92px;
    display: flex;
    align-items: flex-end;
    justify-content: center;
  }

  .trend-bar {
    width: 60%;
    min-height: 4px;
    border-radius: 4px 4px 2px 2px;
    background: linear-gradient(180deg, #fca5a5, #f87171);
    transition: height 0.25s ease;
  }

  .trend-dot {
    position: absolute;
    top: 0;
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: #b91c1c;
  }

  small {
    font-size: 10px;
    color: #9ca3af;
    white-space: nowrap;
  }
}

/* ---------------- 表格 ---------------- */
/* 窄屏不压缩列宽（文字会竖排），改成容器内横向滚动 */
.table-scroll {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: thin;
  scrollbar-color: #d1d5db transparent;

  &::-webkit-scrollbar {
    height: 6px;
  }

  &::-webkit-scrollbar-thumb {
    border-radius: 999px;
    background: #d1d5db;
  }

  &::-webkit-scrollbar-track {
    background: transparent;
  }
}

.mini-table {
  width: 100%;
  min-width: 360px;
  border-collapse: collapse;

  th,
  td {
    padding: 7px 8px;
    text-align: left;
    font-size: 12px;
    border-bottom: 1px solid #f3f4f6;
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  th {
    color: #9ca3af;
    font-weight: 500;
    white-space: nowrap;
  }

  td {
    color: #374151;
  }

  tr:last-child td {
    border-bottom: none;
  }
}

/* ---------------- 评估 ---------------- */
.eval-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;

  .eval-item {
    padding: 8px 10px;
    border-radius: 8px;
    background: #f9fafb;

    small {
      display: block;
      font-size: 11px;
      color: #9ca3af;
      margin-bottom: 2px;
    }

    b {
      font-size: 15px;
      color: #111827;
    }
  }
}

.eval-foot {
  margin: 10px 0 0;
  font-size: 11px;
  color: #9ca3af;
}

/* ---------------- 深度入口 ---------------- */
.deep-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;

  .deep-card {
    display: flex;
    gap: 8px;
    align-items: flex-start;
    min-width: 0;
    padding: 10px 12px;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    background: #fff;
    text-align: left;
    cursor: pointer;
    transition: border-color 0.16s, background 0.16s;

    &:hover {
      border-color: #fecaca;
      background: #fffafa;
    }

    &:focus-visible {
      outline: 2px solid #fca5a5;
      outline-offset: 1px;
    }

    svg {
      color: #dc2626;
      flex-shrink: 0;
      margin-top: 2px;
    }

    .deep-card-body {
      flex: 1;
      min-width: 0;
    }

    .deep-card-arrow {
      margin-left: auto;
      color: #9ca3af;
      transition: transform 0.16s, color 0.16s;
    }

    /* 悬停时箭头右移一点，强化「会跳转」的暗示 */
    &:hover .deep-card-arrow {
      color: #dc2626;
      transform: translateX(2px);
    }

    strong {
      display: block;
      font-size: 12.5px;
      color: #111827;
      overflow-wrap: anywhere;
      word-break: break-word;
    }

    small {
      display: -webkit-box;
      font-size: 11px;
      color: #9ca3af;
      line-height: 1.4;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      overflow-wrap: anywhere;
      word-break: break-word;
    }
  }
}

/* ---------------- 质量 ---------------- */
.bar-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 10px;

  li {
    font-size: 12px;
  }

  .bar-head {
    display: flex;
    justify-content: space-between;
    gap: 10px;
    margin-bottom: 4px;
    color: #4b5563;

    span {
      min-width: 0;
      /* violation.kind 是后端枚举，可能很长；限两行断词，避免把数字挤走 */
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      overflow-wrap: anywhere;
      word-break: break-word;
    }

    b {
      flex-shrink: 0;
      color: #b91c1c;
    }
  }

  .bar-track {
    height: 7px;
    border-radius: 999px;
    background: #f3f4f6;
    overflow: hidden;

    span {
      display: block;
      height: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, #fbbf24, #ef4444);
    }
  }
}

.flag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 12px;

  .flag-chip {
    max-width: 100%;
    padding: 2px 8px;
    border-radius: 999px;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    color: #6b7280;
    font-size: 11px;
    /* flag 名是不带空格的长标识符，必须允许任意位置断行 */
    overflow-wrap: anywhere;
    word-break: break-word;
  }
}

.ghost-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: 1px solid #e5e7eb;
  border-radius: 999px;
  background: #fff;
  color: #4b5563;
  font-size: 11px;
  cursor: pointer;

  &:hover {
    border-color: #fecaca;
    color: #b91c1c;
  }
}

.feedback-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 10px;

  li {
    padding: 10px 12px;
    border-radius: 8px;
    background: #fef2f2;
  }

  .feedback-q {
    margin: 0 0 4px;
    font-size: 12.5px;
    color: #111827;
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  .feedback-a {
    margin: 0 0 6px;
    font-size: 12px;
    color: #6b7280;
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  .feedback-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    font-size: 10.5px;
    color: #9ca3af;

    span {
      min-width: 0;
      max-width: 100%;
      overflow-wrap: anywhere;
      word-break: break-word;
    }
  }
}

.violation-list {
  margin: 0;
  padding: 0;
  list-style: none;

  li {
    padding: 10px 18px;
    border-bottom: 1px solid #f3f4f6;

    &:last-child {
      border-bottom: none;
    }
  }

  .violation-top {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    min-width: 0;
  }

  .violation-kind {
    flex-shrink: 0;
    max-width: 55%;
    padding: 1px 7px;
    border-radius: 6px;
    background: #fef2f2;
    color: #b91c1c;
    font-weight: 600;
    /* violation.kind 来自后端枚举，长名在这里省略号截断（title 给全文），
       否则会把右侧时间挤出行外 */
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .violation-agent {
    flex: 1;
    min-width: 0;
    color: #4b5563;
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  .violation-time {
    flex-shrink: 0;
    margin-left: auto;
    color: #9ca3af;
    font-size: 11px;
  }

  .violation-flags {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 5px;

    span {
      max-width: 100%;
      font-size: 10.5px;
      color: #9ca3af;
      overflow-wrap: anywhere;
      word-break: break-word;
    }
  }
}

.definition-list,
.config-list {
  display: grid;
  grid-template-columns: minmax(120px, 200px) 1fr;
  gap: 6px 14px;
  margin: 0;
  font-size: 12px;

  dt {
    min-width: 0;
    color: #6b7280;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    /* 配置键/口径名是无空格长串，必须允许断词 */
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  dd {
    min-width: 0;
    margin: 0;
    color: #374151;
    line-height: 1.6;
    overflow-wrap: anywhere;
    word-break: break-word;
  }
}

.component-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 8px;

  li {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    font-size: 12.5px;
  }

  .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #ef4444;
    flex-shrink: 0;

    &.ok {
      background: #10b981;
    }
  }

  .component-label {
    flex: 1;
    min-width: 0;
    color: #374151;
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  .component-state {
    flex-shrink: 0;
    font-size: 11px;
    color: #b91c1c;

    &.ok {
      color: #047857;
    }
  }
}

.hint-note {
  margin: 10px 0 0;
  font-size: 11px;
  color: #9ca3af;
  line-height: 1.6;
  overflow-wrap: anywhere;
  word-break: break-word;
}

/* 内部滚动列表：拦截记录 / 待办 / 差评 / 定义与配置 / 组件状态超过约 8 行就自己滚，
   页面高度不再线性增长；overscroll-behavior 防止滚到底带动整页。 */
.todo-list,
.feedback-list,
.bar-list,
.violation-list,
.definition-list,
.config-list,
.component-list {
  max-height: 320px;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: 4px;
  scrollbar-width: thin;
  scrollbar-color: #d1d5db transparent;

  &::-webkit-scrollbar {
    width: 6px;
  }

  &::-webkit-scrollbar-thumb {
    border-radius: 999px;
    background: #d1d5db;
  }

  &::-webkit-scrollbar-track {
    background: transparent;
  }
}

/* flush 面板里的列表自己带左右内边距，滚动条容器的 padding 不能把分隔线挤歪 */
.violation-list {
  padding-right: 2px;
}

@media (max-width: 900px) {
  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .two-col {
    grid-template-columns: minmax(0, 1fr);
  }

  .deep-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .stat-grid {
    gap: 8px;
  }

  .eval-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .deep-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  /* 近 30 天有 30 根柱子，手机上一根只剩几像素根本看不清。
     这里选择「容器内横向滚动」而不是减少天数：数据逻辑不动，日期仍连续可读。 */
  .trend {
    height: 136px;
    overflow-x: auto;
    overscroll-behavior-x: contain;
    padding-bottom: 2px;
    scrollbar-width: thin;
    scrollbar-color: #d1d5db transparent;

    &::-webkit-scrollbar {
      height: 6px;
    }

    &::-webkit-scrollbar-thumb {
      border-radius: 999px;
      background: #d1d5db;
    }

    &::-webkit-scrollbar-track {
      background: transparent;
    }

    .trend-col {
      flex: 0 0 28px;
    }

    small {
      font-size: 9px;
    }
  }

  /* 窄屏下时间窗按钮整体换行，按钮文字不折行、不溢出标题区 */
  .window-picker {
    max-width: 100%;

    .window-btn {
      padding: 4px 8px;
      font-size: 11px;
      white-space: nowrap;
    }
  }

  /* 可点的行留足手指高度，避免 20px 高的行点不中 */
  .todo-list .todo-row {
    min-height: 44px;
    padding: 9px 10px;
  }

  .deep-grid .deep-card {
    padding: 10px;
  }

  .feedback-list li {
    padding: 10px;
  }

  .violation-list li {
    padding: 10px 14px;
  }

  .definition-list,
  .config-list {
    grid-template-columns: minmax(0, 1fr);
    gap: 2px;

    dd {
      margin-bottom: 8px;
    }
  }
}

/* ------------------------------ 订单管理 ------------------------------ */
.order-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;

  .filter-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    height: 32px;
    padding: 0 12px;
    border: 1px solid #e5e7eb;
    border-radius: 999px;
    background: #fff;
    color: #4b5563;
    font-size: 12.5px;
    cursor: pointer;
    transition: border-color 0.16s ease, background-color 0.16s ease, color 0.16s ease;

    &:hover {
      border-color: #fecaca;
      color: #b91c1c;
    }

    &.is-active {
      border-color: #dc2626;
      background: #fef2f2;
      color: #b91c1c;
      font-weight: 600;
    }
  }

  .filter-count {
    padding: 0 5px;
    border-radius: 999px;
    background: #fee2e2;
    color: #b91c1c;
    font-size: 11px;
    line-height: 16px;
  }
}

.order-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 56vh;
  overflow-y: auto;
  padding-right: 4px;
  scrollbar-width: thin;
  scrollbar-color: #e5e7eb transparent;
}
</style>
