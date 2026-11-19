<script setup>
// KeepAlive 依赖组件名（App.vue 的 CACHED 白名单按 name 匹配）
defineOptions({name: 'ObserveView'})

/**
 * 观测与评估看板（M4，路由 /admin/observe，仅 admin）。
 *
 * 数据全部来自 GET /api/admin/observe/overview 与 /recent：
 * 8 个核心指标卡 + 成本 + 合规拦截 + 离线评估 + 最近对话。
 * eval.available=false 时只显示「还没跑过评估」，不算错误；接口 403 才算无权访问。
 */
import {computed, onMounted, ref} from 'vue'
import {useRouter} from 'vue-router'
import dayjs from 'dayjs'
import {showToast} from 'vant'
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  ChevronDown,
  ExternalLink,
  FlaskConical,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  ThumbsDown,
  ThumbsUp
} from 'lucide-vue-next'
import Navbar from '../../components/Navbar.vue'
import {fetchOverview, fetchRecent} from '../../api/observe'

const router = useRouter()

const WINDOWS = [7, 14, 30]
const RECENT_LIMIT = 20

// 合规 flag → 中文名（认不出的 flag 原样显示，绝不吞掉信息）
const GUARDRAIL_LABELS = {
  compliance_rewritten: '合规改写',
  emergency_notice: '急诊提示',
  disclaimer_injected: '免责声明注入',
  blocked: '安全拦截',
  refusal: '拒答',
  sensitive: '敏感内容',
  pii_redacted: '隐私脱敏',
  dosage_warning: '剂量警示',
  medical_disclaimer: '医疗免责声明'
}

const days = ref(7)
const overview = ref(null)
const recent = ref([])
const loading = ref(false)
const error = ref('')
const forbidden = ref(false)
const expandedKey = ref('')

/* ------------------------------------------------------------------ *
 * 格式化
 * ------------------------------------------------------------------ */

const num = (value) => {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

const percentText = (value) => {
  const parsed = num(value)
  return parsed === null ? '-' : `${(parsed * 100).toFixed(1)}%`
}

const intText = (value) => {
  const parsed = num(value)
  return parsed === null ? '-' : String(Math.round(parsed))
}

const secondsText = (value) => {
  const parsed = num(value)
  return parsed === null ? '-' : `${(parsed / 1000).toFixed(1)}s`
}

const moneyText = (value) => {
  const parsed = num(value)
  if (parsed === null) return '-'
  return `¥${parsed.toFixed(parsed !== 0 && Math.abs(parsed) < 0.01 ? 4 : 2)}`
}

const tokenText = (value) => {
  const parsed = num(value)
  return parsed === null ? '-' : parsed.toLocaleString('zh-CN')
}

const formatTime = (value) => {
  if (!value) return '-'
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('MM-DD HH:mm') : '-'
}

const flagLabel = (flag) => GUARDRAIL_LABELS[flag] || flag || '未知'

/* ------------------------------------------------------------------ *
 * 指标
 * ------------------------------------------------------------------ */

const metrics = computed(() => {
  const data = overview.value || {}
  const latency = data.latency || {}
  const quality = data.quality || {}
  const cost = data.cost || {}
  const totals = data.totals || {}

  const p95 = num(latency.p95_ms)
  const p50 = num(latency.p50_ms)
  const refusal = num(quality.refusal_rate)
  const citation = num(quality.citation_rate)
  const handoff = num(quality.handoff_rate)
  const errorRate = num(quality.error_rate)
  const avgCost = num(cost.avg_cost_per_turn_cny)
  const sample = num(latency.count)

  return [
    {
      key: 'p95',
      title: '端到端 p95',
      value: secondsText(p95),
      hint: p95 === null ? '目标 ≤6s' : `目标 ≤6s · 采样 ${intText(sample)} 轮`,
      bad: p95 !== null && p95 > 6000
    },
    {
      key: 'p50',
      title: '端到端 p50',
      value: secondsText(p50),
      hint: '目标 ≤3s · 一半用户的等待上限',
      bad: p50 !== null && p50 > 3000
    },
    {
      key: 'turns',
      title: '对话轮次',
      value: intText(totals.turns),
      hint: `${intText(totals.conversations)} 个会话 · ${intText(totals.messages)} 条消息`,
      bad: false
    },
    {
      key: 'refusal',
      title: '拒答率',
      value: percentText(refusal),
      hint: '目标 ≤30% · 偏高说明知识缺口',
      bad: refusal !== null && refusal > 0.3
    },
    {
      key: 'citation',
      title: '引用率',
      value: percentText(citation),
      hint: '目标 ≥80% · 带引用的回答更可信',
      bad: citation !== null && citation < 0.8
    },
    {
      key: 'handoff',
      title: '转人工率',
      value: percentText(handoff),
      hint: '目标 ≤15% · 偏高说明 AI 解不了',
      bad: handoff !== null && handoff > 0.15
    },
    {
      key: 'cost',
      title: '平均单轮成本',
      value: moneyText(avgCost),
      hint: '目标 ≤¥0.02 · 单轮 token 花费',
      bad: avgCost !== null && avgCost > 0.02
    },
    {
      key: 'error',
      title: '错误率',
      value: percentText(errorRate),
      hint: '目标 ≤1% · 生成失败 / 链路异常',
      bad: errorRate !== null && errorRate > 0.01
    }
  ]
})

/* ------------------------------------------------------------------ *
 * 成本
 * ------------------------------------------------------------------ */

const costStats = computed(() => {
  const cost = (overview.value && overview.value.cost) || {}
  const input = num(cost.input_tokens)
  const output = num(cost.output_tokens)
  const total = input === null && output === null ? null : (input || 0) + (output || 0)
  return [
    {label: '输入 token', value: tokenText(input)},
    {label: '输出 token', value: tokenText(output)},
    {label: 'token 总量', value: tokenText(total)},
    {label: '估算成本', value: moneyText(cost.cost_cny)},
    {label: '平均单轮', value: moneyText(cost.avg_cost_per_turn_cny)}
  ]
})

/* ------------------------------------------------------------------ *
 * 合规拦截
 * ------------------------------------------------------------------ */

const guardrail = computed(() => (overview.value && overview.value.guardrail) || {})

const guardrailBars = computed(() => {
  const byFlag = guardrail.value.by_flag
  if (!byFlag || typeof byFlag !== 'object') return []
  const items = Object.keys(byFlag)
    .map((flag) => ({flag, label: flagLabel(flag), count: num(byFlag[flag]) || 0}))
    .filter((item) => item.count > 0)
    .sort((a, b) => b.count - a.count)
  const sum = items.reduce((acc, item) => acc + item.count, 0)
  const max = items.reduce((acc, item) => Math.max(acc, item.count), 0)
  return items.map((item) => ({
    ...item,
    // 条形长度按「相对最高的一档」画，占比按「总拦截次数」算
    width: max > 0 ? Math.max(4, Math.round((item.count / max) * 100)) : 0,
    share: sum > 0 ? `${((item.count / sum) * 100).toFixed(0)}%` : '-'
  }))
})

const guardrailRecent = computed(() => {
  const list = guardrail.value.recent
  return Array.isArray(list) ? list.slice(0, 10) : []
})

/* ------------------------------------------------------------------ *
 * 评估
 * ------------------------------------------------------------------ */

const evalData = computed(() => (overview.value && overview.value.eval) || null)
const evalAvailable = computed(() => !!(evalData.value && evalData.value.available))

const evalRows = computed(() => {
  const data = evalData.value || {}
  return [
    {label: 'Recall@5', value: percentText(data.recall_at_5), key: 'recall_at_5'},
    {label: 'MRR', value: percentText(data.mrr), key: 'mrr'},
    {label: '拒答准确率', value: percentText(data.refusal_accuracy), key: 'refusal_accuracy'},
    {label: '引用准确率', value: percentText(data.citation_precision), key: 'citation_precision'},
    {label: 'Faithfulness', value: percentText(data.faithfulness), key: 'faithfulness'}
  ]
})

/* ------------------------------------------------------------------ *
 * 最近对话
 * ------------------------------------------------------------------ */

const rowKey = (item, index) => (item && item.message_id) || `row-${index}`

const toggleRow = (item, index) => {
  const key = rowKey(item, index)
  expandedKey.value = expandedKey.value === key ? '' : key
}

const isExpanded = (item, index) => expandedKey.value === rowKey(item, index)

const rowFlags = (item) => {
  const data = (item && item.guardrail) || {}
  return Array.isArray(data.flags) ? data.flags : []
}

const rowViolations = (item) => {
  const data = (item && item.guardrail) || {}
  return Array.isArray(data.violations) ? data.violations : []
}

/* ------------------------------------------------------------------ *
 * 加载
 * ------------------------------------------------------------------ */

const langfuseUrl = computed(() => {
  const links = (overview.value && overview.value.links) || {}
  return links.langfuse || ''
})

const loadAll = async () => {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    const [overviewRes, recentRes] = await Promise.allSettled([
      fetchOverview(days.value),
      fetchRecent(RECENT_LIMIT)
    ])

    const denied = [overviewRes, recentRes].find((item) => (
      item.status === 'rejected'
      && item.reason
      && (item.reason.status === 403 || item.reason.status === 401)
    ))
    if (denied) {
      forbidden.value = true
      overview.value = null
      recent.value = []
      return
    }

    // 概览是页面主体：它挂了就整页错误态（可重试）
    if (overviewRes.status === 'rejected') {
      overview.value = null
      error.value = (overviewRes.reason && overviewRes.reason.message) || '观测数据加载失败，请稍后重试'
      return
    }

    overview.value = overviewRes.value || null
    if (recentRes.status === 'fulfilled') {
      recent.value = Array.isArray(recentRes.value) ? recentRes.value : []
    } else {
      recent.value = []
      showToast({
        type: 'fail',
        message: (recentRes.reason && recentRes.reason.message) || '最近对话加载失败'
      })
    }
  } catch (e) {
    overview.value = null
    error.value = (e && e.message) || '观测数据加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

const switchDays = async (value) => {
  if (loading.value || days.value === value) return
  days.value = value
  expandedKey.value = ''
  await loadAll()
}

const retry = async () => {
  forbidden.value = false
  await loadAll()
}

const generatedText = computed(() => {
  const at = overview.value && overview.value.generated_at
  if (!at) return ''
  return `数据生成于 ${formatTime(at)} · 近 ${overview.value.window_days || days.value} 天`
})

onMounted(loadAll)
</script>

<template>
  <div class="observe-page">
    <Navbar/>

    <div class="page-container">
      <!-- 页头 -->
      <div class="page-header">
        <div class="title-block">
          <button class="back-link" @click="router.push('/admin')">
            <ArrowLeft :size="16"/>
            返回工作台
          </button>
          <h2>观测与评估</h2>
          <p>延迟、质量、成本、合规拦截与离线评估，一页看完线上 Agent 的健康度。</p>
          <p v-if="generatedText" class="generated-at">{{ generatedText }}</p>
        </div>

        <div class="head-controls">
          <div class="window-switch">
            <button
                v-for="value in WINDOWS"
                :key="value"
                type="button"
                class="window-btn"
                :class="{ active: days === value }"
                :disabled="loading"
                @click="switchDays(value)"
            >
              近 {{ value }} 天
            </button>
          </div>

          <button type="button" class="ghost-btn" :disabled="loading" @click="loadAll">
            <RefreshCw :size="14" :class="{ spinning: loading }"/>
            刷新
          </button>

          <a
              v-if="langfuseUrl"
              class="ghost-btn langfuse-link"
              :href="langfuseUrl"
              target="_blank"
              rel="noopener noreferrer"
          >
            <ExternalLink :size="14"/>
            Langfuse
          </a>
          <span v-else class="ghost-btn is-disabled" title="后端未配置 Langfuse 项目地址">
            <ExternalLink :size="14"/>
            Langfuse
          </span>
        </div>
      </div>

      <!-- 无权访问 -->
      <section v-if="forbidden" class="state-card">
        <ShieldAlert :size="30" color="#ef4444"/>
        <h3>仅管理员可用</h3>
        <p>当前账号没有查看观测看板的权限（需要 admin 角色）。</p>
        <button type="button" class="ghost-btn" @click="router.push('/')">返回首页</button>
      </section>

      <template v-else>
        <!-- 加载骨架 -->
        <div v-if="loading && !overview" class="skeleton-area">
          <div class="skeleton-grid">
            <div v-for="n in 8" :key="n" class="skeleton-card"></div>
          </div>
          <div class="skeleton-panel"></div>
          <div class="skeleton-panel short"></div>
        </div>

        <!-- 错误态 -->
        <section v-else-if="error" class="state-card is-error">
          <AlertTriangle :size="28" color="#ef4444"/>
          <h3>看板加载失败</h3>
          <p>{{ error }}</p>
          <button type="button" class="ghost-btn" :disabled="loading" @click="retry">重试</button>
        </section>

        <template v-else>
          <!-- 8 个核心指标 -->
          <div class="metric-grid">
            <div
                v-for="item in metrics"
                :key="item.key"
                class="metric-card"
                :class="{ 'is-bad': item.bad }"
            >
              <!-- title 挂全文：卡片里只显示两行，鼠标悬停仍能读到完整口径 -->
              <div class="metric-title" :title="item.title">{{ item.title }}</div>
              <div class="metric-value" :class="{ 'is-bad': item.bad }">{{ item.value }}</div>
              <div class="metric-hint" :title="item.hint">{{ item.hint }}</div>
            </div>
          </div>

          <!-- 成本 -->
          <div class="panel cost-panel">
            <div class="panel-header">
              <h3>成本</h3>
              <span class="muted">按 token 单价估算，仅供参考</span>
            </div>
            <div class="cost-grid">
              <div v-for="item in costStats" :key="item.label" class="cost-item">
                <div class="cost-label">{{ item.label }}</div>
                <div class="cost-value">{{ item.value }}</div>
              </div>
            </div>
          </div>

          <!-- 合规拦截 -->
          <div class="panel guardrail-panel">
            <div class="panel-header">
              <h3>合规拦截</h3>
              <span class="muted">
                共 {{ intText(guardrail.violations) }} 次 · 展示 top flag
              </span>
            </div>

            <div v-if="guardrailBars.length === 0" class="panel-empty">
              <ShieldCheck :size="20" color="#10b981"/>
              <p>窗口内没有触发合规拦截</p>
            </div>

            <div v-else class="bar-list">
              <div v-for="bar in guardrailBars" :key="bar.flag" class="bar-row">
                <span class="bar-label" :title="bar.label">{{ bar.label }}</span>
                <div class="bar-track">
                  <div class="bar-fill" :style="{ width: `${bar.width}%` }"></div>
                </div>
                <span class="bar-count">{{ bar.count }} 次</span>
                <span class="bar-share">{{ bar.share }}</span>
              </div>
            </div>

            <div v-if="guardrailRecent.length" class="recent-flags">
              <div class="sub-title">最近触发</div>
              <ul>
                <li v-for="(item, index) in guardrailRecent" :key="index">
                  <span class="flag-time">{{ formatTime(item.at) }}</span>
                  <span class="flag-name" :title="flagLabel(item.flag)">{{ flagLabel(item.flag) }}</span>
                  <code v-if="item.agent_code" class="agent-code" :title="item.agent_code">{{ item.agent_code }}</code>
                </li>
              </ul>
            </div>
          </div>

          <!-- 离线评估 -->
          <div class="panel eval-panel">
            <div class="panel-header">
              <h3>离线评估</h3>
              <span v-if="evalAvailable" class="muted">
                {{ formatTime(evalData.ran_at) }} 跑测 · {{ intText(evalData.cases) }} 个用例
              </span>
              <span v-else class="muted">未跑测</span>
            </div>

            <div v-if="!evalAvailable" class="panel-empty">
              <FlaskConical :size="22" color="#9ca3af"/>
              <p>还没跑过评估</p>
              <p class="empty-hint">
                跑一次 <code>python tests/eval/run_eval.py</code> 就能看到数字
              </p>
            </div>

            <div v-else class="eval-table-wrap">
              <table class="eval-table">
                <thead>
                <tr>
                  <th>指标</th>
                  <th class="value-col">当前值</th>
                </tr>
                </thead>
                <tbody>
                <tr v-for="row in evalRows" :key="row.key">
                  <td>{{ row.label }}</td>
                  <td class="value-col">{{ row.value }}</td>
                </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- 最近对话 -->
          <div class="panel recent-panel">
            <div class="panel-header">
              <h3>最近对话</h3>
              <span class="muted">共 {{ recent.length }} 条 · 点一行展开完整回答</span>
            </div>

            <div v-if="recent.length === 0" class="panel-empty">
              <Activity :size="20" color="#9ca3af"/>
              <p>窗口内还没有对话</p>
            </div>

            <ul v-else class="recent-list">
              <li
                  v-for="(item, index) in recent"
                  :key="rowKey(item, index)"
                  class="recent-row"
                  :class="{ expanded: isExpanded(item, index) }"
                  role="button"
                  tabindex="0"
                  :aria-expanded="isExpanded(item, index)"
                  @click="toggleRow(item, index)"
                  @keydown.enter.prevent="toggleRow(item, index)"
                  @keydown.space.prevent="toggleRow(item, index)"
              >
                <div class="row-head">
                  <span class="row-question" :title="item.question || '（无问题文本）'">{{ item.question || '（无问题文本）' }}</span>
                  <span class="row-time">{{ formatTime(item.created_at) }}</span>
                  <!-- 展开/收起用 ChevronDown + 翻转，比右箭头更准确表达「同一行内展开」 -->
                  <ChevronDown :size="14" class="row-arrow"/>
                </div>

                <div class="row-answer" :class="{ 'is-full': isExpanded(item, index) }">
                  {{ item.answer || '（无回答文本）' }}
                </div>

                <div class="row-meta">
                  <code v-if="item.agent_code" class="agent-code" :title="item.agent_code">{{ item.agent_code }}</code>
                  <span class="meta-item">
                    耗时 {{ secondsText(item.latency_ms) }}
                  </span>
                  <span
                      v-for="flag in rowFlags(item)"
                      :key="`flag-${flag}`"
                      class="tag is-flag"
                  >
                    {{ flagLabel(flag) }}
                  </span>
                  <span
                      v-for="flag in rowViolations(item)"
                      :key="`violation-${flag}`"
                      class="tag is-violation"
                  >
                    {{ flagLabel(flag) }}
                  </span>

                  <span v-if="item.feedback && item.feedback.rating" class="tag feedback-chip" :title="item.feedback.reason || ''">
                    <ThumbsUp v-if="item.feedback.rating === 'up'" :size="11"/>
                    <ThumbsDown v-else :size="11"/>
                    {{ item.feedback.rating === 'up' ? '有用' : '没用' }}
                    <template v-if="item.feedback.reason">· {{ item.feedback.reason }}</template>
                  </span>
                  <span v-else class="meta-item muted">未反馈</span>
                </div>
              </li>
            </ul>
          </div>
        </template>
      </template>
    </div>
  </div>
</template>

<style scoped lang="scss">
.observe-page {
  min-height: 100vh;
  background: #f3f4f6;
  padding-top: 64px;
  padding-bottom: 32px;

  .page-container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 24px;
  }

  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    flex-wrap: wrap;
    gap: 16px;
    margin-bottom: 20px;

    .title-block {
      min-width: 0;

      h2 {
        font-size: 22px;
        color: #111827;
        margin-bottom: 6px;
      }

      p {
        font-size: 13px;
        color: #6b7280;
      }

      .generated-at {
        margin-top: 4px;
        font-size: 12px;
        color: #9ca3af;
      }
    }

    .back-link {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      border: none;
      background: transparent;
      color: #6b7280;
      font-size: 13px;
      padding: 0;
      margin-bottom: 8px;
      cursor: pointer;

      &:hover {
        color: #ef4444;
      }
    }

    .head-controls {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
    }
  }

  .window-switch {
    display: inline-flex;
    padding: 2px;
    border-radius: 8px;
    background: #e5e7eb;

    .window-btn {
      padding: 4px 10px;
      border: none;
      border-radius: 6px;
      background: transparent;
      color: #6b7280;
      font-size: 12px;
      cursor: pointer;
      transition: all 0.15s;

      &.active {
        background: #fff;
        color: #b91c1c;
        font-weight: 600;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
      }

      &:disabled {
        cursor: not-allowed;
        opacity: 0.6;
      }
    }
  }

  .ghost-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
    height: 28px;
    padding: 0 10px;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    background: #fff;
    color: #6b7280;
    font-size: 12px;
    text-decoration: none;
    white-space: nowrap;
    cursor: pointer;

    &:hover:not(:disabled):not(.is-disabled) {
      border-color: #fecaca;
      color: #b91c1c;
    }

    &:disabled,
    &.is-disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }

    .spinning {
      animation: observe-spin 0.9s linear infinite;
    }
  }

  .state-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    padding: 44px 24px;
    background: #fff;
    border-radius: 12px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    text-align: center;

    h3 {
      font-size: 16px;
      color: #111827;
    }

    p {
      font-size: 13px;
      line-height: 1.7;
      color: #6b7280;
      max-width: 420px;
    }
  }

  .metric-grid {
    display: grid;
    /* minmax(0, 1fr) 而不是 1fr：1fr 的最小尺寸是 auto，长文本会把列撑宽导致整页横向滚动 */
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 14px;
    margin-bottom: 16px;
  }

  .metric-card {
    /* 卡片是 grid/flex 子项，默认 min-width:auto 会被长内容撑破，必须显式归零 */
    min-width: 0;
    background: #fff;
    border-radius: 12px;
    padding: 16px 18px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    border: 1px solid transparent;

    &.is-bad {
      border-color: #fecaca;
      background: #fffafa;
    }

    .metric-title {
      font-size: 13px;
      color: #6b7280;
    }

    .metric-value {
      margin: 6px 0 4px;
      font-size: 26px;
      font-weight: 700;
      line-height: 1.2;
      color: #111827;
      font-variant-numeric: tabular-nums;
      /* 极端长数字/百分号也不许顶出卡片 */
      overflow-wrap: anywhere;

      &.is-bad {
        color: #dc2626;
      }
    }

    .metric-hint {
      font-size: 11.5px;
      line-height: 1.5;
      color: #9ca3af;
    }

    /* 标题与口径说明可能很长（例如带采样数、目标值），统一任意位置断词 + 最多两行，
       完整文案由模板上的 title 提供，不靠撑宽卡片来「显示全」 */
    .metric-title,
    .metric-hint {
      min-width: 0;
      overflow-wrap: anywhere;
      word-break: break-word;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
  }

  .panel {
    background: #fff;
    border-radius: 12px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    padding: 20px 24px;
    margin-bottom: 16px;

    .panel-header {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      flex-wrap: wrap;
      gap: 6px;
      margin-bottom: 14px;
      min-width: 0;

      h3 {
        font-size: 16px;
        color: #374151;
      }
    }

    .muted {
      min-width: 0;
      font-size: 12px;
      color: #9ca3af;
      overflow-wrap: anywhere;
      word-break: break-word;
    }

    .panel-empty {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
      padding: 22px 12px;
      text-align: center;
      color: #9ca3af;

      p {
        font-size: 13px;
        line-height: 1.7;
        color: #6b7280;
      }

      .empty-hint {
        font-size: 12px;
        color: #9ca3af;

        code {
          padding: 1px 5px;
          border-radius: 4px;
          background: #f3f4f6;
          color: #4b5563;
          font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
          font-size: 12px;
        }
      }
    }
  }

  .cost-grid {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 12px;

    .cost-item {
      min-width: 0;
      padding: 10px 12px;
      border-radius: 10px;
      background: #f9fafb;
    }

    .cost-label {
      font-size: 12px;
      color: #9ca3af;
      overflow-wrap: anywhere;
      word-break: break-word;
    }

    .cost-value {
      margin-top: 4px;
      font-size: 17px;
      font-weight: 600;
      color: #111827;
      font-variant-numeric: tabular-nums;
      overflow-wrap: anywhere;
    }
  }

  .bar-list {
    display: flex;
    flex-direction: column;
    gap: 8px;

    .bar-row {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 12.5px;
    }

    .bar-label {
      flex: 0 0 96px;
      width: 96px;
      min-width: 0;
      color: #4b5563;
      /* flag 名可能很长（例如 medical_disclaimer），固定宽度下必须断词 + 限两行，
         否则要么被裁掉要么把条形图挤没 */
      overflow-wrap: anywhere;
      word-break: break-word;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }

    .bar-track {
      flex: 1;
      /* 轨道允许被压缩，但留 24px 下限，窄屏也能看出长度差异 */
      min-width: 24px;
      height: 8px;
      border-radius: 999px;
      background: #f3f4f6;
      overflow: hidden;
    }

    .bar-fill {
      height: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, #f87171, #dc2626);
      transition: width 0.3s ease;
    }

    .bar-count {
      flex-shrink: 0;
      width: 54px;
      text-align: right;
      color: #111827;
      font-variant-numeric: tabular-nums;
    }

    .bar-share {
      flex-shrink: 0;
      width: 40px;
      text-align: right;
      color: #9ca3af;
      font-variant-numeric: tabular-nums;
    }
  }

  .recent-flags {
    margin-top: 16px;
    padding-top: 12px;
    border-top: 1px dashed #f3f4f6;

    .sub-title {
      font-size: 12px;
      color: #9ca3af;
      margin-bottom: 6px;
    }

    ul {
      list-style: none;
      margin: 0;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    li {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      font-size: 12px;
      color: #4b5563;
    }

    .flag-time {
      width: 88px;
      flex-shrink: 0;
      color: #9ca3af;
      font-variant-numeric: tabular-nums;
    }

    .flag-name {
      flex: 1;
      min-width: 0;
      overflow-wrap: anywhere;
      word-break: break-word;
      /* 中文标签一般一行足够，长英文 flag 限两行，悬停 title 看全文 */
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
  }

  .agent-code {
    max-width: 100%;
    min-width: 0;
    padding: 0 6px;
    border-radius: 4px;
    background: #f3f4f6;
    color: #6b7280;
    font-size: 11px;
    line-height: 18px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    /* code 是一整串无空格标识符：必须允许任意位置断行，而不是 nowrap 撑出容器 */
    white-space: normal;
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  .eval-table-wrap {
    /* 窄屏表格横向滚动，而不是把列压到文字竖排 */
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    /* 细滚动条：横向滚动条不抢内容高度 */
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

  .eval-table {
    width: 100%;
    min-width: 300px;
    max-width: 520px;
    border-collapse: collapse;

    th,
    td {
      text-align: left;
      padding: 9px 10px;
      border-bottom: 1px solid #f3f4f6;
      font-size: 13px;
      color: #374151;
      overflow-wrap: anywhere;
      word-break: break-word;
    }

    th {
      background: #f9fafb;
      color: #6b7280;
      font-weight: 500;
      font-size: 12px;
    }

    .value-col {
      width: 120px;
      font-variant-numeric: tabular-nums;
      color: #111827;
    }
  }

  /* 内部滚动列表：内容超过约 8 行就自己滚，页面高度不再被 20 条最近记录/全部 flag 拉长。
     overscroll-behavior: contain 保证滚到底时不会把整页一起带着滚。 */
  .bar-list,
  .recent-flags ul,
  .recent-list {
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

  .recent-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .recent-row {
    padding: 10px 12px;
    border: 1px solid #f3f4f6;
    border-radius: 10px;
    background: #fcfcfd;
    cursor: pointer;
    transition: border-color 0.15s ease, background-color 0.15s ease;

    &:hover {
      border-color: #fecaca;
      background: #fff7f7;
    }

    /* 键盘 Tab 过来要有可见焦点：role=button 的行不能只靠 hover 区分 */
    &:focus-visible {
      outline: 2px solid #fca5a5;
      outline-offset: 1px;
      border-color: #fca5a5;
    }

    &.expanded {
      border-color: #fecaca;
      background: #fff;
    }

    .row-head {
      display: flex;
      align-items: flex-start;
      gap: 10px;
    }

    .row-question {
      flex: 1;
      min-width: 0;
      font-size: 13px;
      font-weight: 600;
      line-height: 1.6;
      color: #111827;
      overflow-wrap: anywhere;
      word-break: break-word;
      /* 问题一行最多两行，避免一条超长提问把整行顶开；全文在 title 里 */
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }

    .row-time {
      flex-shrink: 0;
      font-size: 11px;
      color: #9ca3af;
      font-variant-numeric: tabular-nums;
    }

    .row-arrow {
      flex-shrink: 0;
      margin-top: 2px;
      color: #9ca3af;
      transition: transform 0.15s ease;
    }

    &.expanded .row-arrow {
      transform: rotate(180deg);
    }

    .row-answer {
      margin-top: 5px;
      font-size: 12.5px;
      line-height: 1.7;
      color: #6b7280;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      overflow-wrap: anywhere;
      word-break: break-word;

      &.is-full {
        display: block;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
        word-break: break-word;
        color: #374151;
      }
    }

    .row-meta {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      margin-top: 8px;
      font-size: 11.5px;
      color: #9ca3af;

      .meta-item {
        font-variant-numeric: tabular-nums;

        &.muted {
          color: #9ca3af;
        }
      }
    }
  }

  .tag {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    max-width: 100%;
    padding: 0 6px;
    border-radius: 6px;
    font-size: 10.5px;
    line-height: 17px;
    /* 反馈原因等标签可能很长：允许折行而不是 nowrap 顶出卡片 */
    white-space: normal;
    overflow-wrap: anywhere;
    word-break: break-word;

    &.is-flag {
      background: #f3f4f6;
      color: #6b7280;
    }

    &.is-violation {
      background: #fef2f2;
      border: 1px solid #fecaca;
      color: #b91c1c;
    }

    &.feedback-chip {
      background: #eff6ff;
      color: #1d4ed8;
    }
  }

  .skeleton-area {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .skeleton-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 14px;
  }

  .skeleton-card,
  .skeleton-panel {
    background: linear-gradient(90deg, #fff 25%, #f3f4f6 37%, #fff 63%);
    background-size: 400% 100%;
    border-radius: 12px;
    animation: observe-shimmer 1.4s ease infinite;
  }

  .skeleton-card {
    height: 96px;
  }

  .skeleton-panel {
    height: 150px;

    &.short {
      height: 110px;
    }
  }

  @media (max-width: 1000px) {
    .metric-grid,
    .skeleton-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .cost-grid {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
  }

  @media (max-width: 768px) {
    .page-container {
      padding: 12px;
      /* 兜底：万一有漏网的长内容，也不让整页能左右拖动。
         用 clip 而不是 hidden，避免多造一层纵向滚动容器 */
      overflow-x: clip;
    }

    .page-header {
      h2 {
        font-size: 19px;
      }

      .title-block p {
        font-size: 12px;
      }

      /* 窄屏把时间窗 + 刷新/外链整体换行，按钮自身不缩、不溢出 */
      .head-controls {
        width: 100%;
        gap: 6px;
      }

      .window-switch {
        flex-wrap: wrap;
      }

      .window-btn {
        padding: 5px 8px;
      }

      .ghost-btn {
        height: 30px;
      }
    }

    .panel {
      padding: 16px 14px;
    }

    .metric-grid,
    .skeleton-grid {
      gap: 10px;
    }

    .metric-card {
      padding: 12px;

      .metric-value {
        font-size: 21px;
      }

      /* 手机上信息密度高，口径说明只留一行，避免指标卡又高又挤 */
      .metric-hint {
        -webkit-line-clamp: 1;
      }
    }

    .cost-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .bar-list {
      .bar-row {
        gap: 8px;
        align-items: flex-start;
      }

      .bar-label {
        flex-basis: 68px;
        width: 68px;
      }

      .bar-count {
        width: 46px;
      }

      .bar-share {
        width: 34px;
      }
    }

    /* 窄屏一行放不下「时间 + flag 名 + agent code」时，让 code 换行到第二行 */
    .recent-flags li {
      flex-wrap: wrap;
      row-gap: 2px;
    }
  }
}

@keyframes observe-spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes observe-shimmer {
  0% {
    background-position: 100% 50%;
  }

  100% {
    background-position: 0 50%;
  }
}
</style>
