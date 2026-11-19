<script setup>
// KeepAlive 依赖组件名（App.vue 的 CACHED 白名单按 name 匹配）
defineOptions({name: 'SearchTestView'})

import {ref, reactive, computed, onMounted} from 'vue'
import {useRouter} from 'vue-router'
import {showToast} from 'vant'
import {ArrowLeft, Search, ShieldCheck, ShieldX, FlaskConical} from 'lucide-vue-next'
import Navbar from '../../components/Navbar.vue'
import {getKbListApi, searchTestApi} from '../../api/kb'

const router = useRouter()

// 知识库下拉里「全部库」的哨兵值
const ALL_KB = '__all__'

const ROLE_OPTIONS = [
  {text: '患者 patient', value: 'patient'},
  {text: '医生 doctor', value: 'doctor'},
  {text: '客服 support', value: 'support'},
  {text: '管理员 admin', value: 'admin'},
  {text: '访客 visitor', value: 'visitor'}
]

// 快捷用例：一键把「问题 + 角色 + 库范围」都摆好并直接检索。
// 面试演示时最怕现场拼组合（这个角色配哪个库、阈值填多少），预置几条
// 能把「ACL 在检索层生效」和「阈值拒答」两个重点一次讲全。
const QUICK_PRESETS = [
  {
    label: '企业介绍',
    role: 'admin',
    query: '介绍一下企业',
    hint: '泛问句也能命中：看 top_score 0.29 / 阈值 0.15，命中《花红药业企业简介》'
  },
  {
    label: '药品禁忌',
    role: 'patient',
    query: '哺乳期可以吃花红片吗',
    hint: '命中说明书【禁忌】段落，分数接近 0.95 —— 这是「该答就答」的对照组'
  },
  {
    label: '售后政策',
    role: 'patient',
    query: '七天无理由退货吗',
    hint: '患者能进售后库，命中《退换货政策》'
  },
  {
    label: '游客问售后',
    role: 'visitor',
    query: '七天无理由退货吗',
    hint: '同一句话换游客：售后库被 ACL 过滤掉 → 分数不够 → low_score 拒答'
  },
  {
    label: '越权查 SOP',
    role: 'patient',
    query: '投诉怎么处理',
    kbCode: 'kb_sop',
    hint: '患者指定内部 SOP 库：no_permission —— 注意这是「被拒绝」，不是「没搜到」'
  },
  {
    label: '无关问题',
    role: 'admin',
    query: '今天天气怎么样',
    hint: '召回有候选但分数低于阈值：命中区标「仅供参考」，能看到差多少分'
  }
]

const kbs = ref([])
const kbLoading = ref(true)
const firstKbId = ref('')
// 空字符串表示「全部库」：路径仍用第一个库的 id 兜底，body 里 kb_ids 传 null
const selectedKbId = ref('')

const form = reactive({
  query: '',
  role: 'patient',
  threshold: ''
})

const submitting = ref(false)
const result = ref(null)
const lastRequest = ref(null)
const activePreset = ref('')

const activePresetHint = computed(() => (
    QUICK_PRESETS.find((preset) => preset.label === activePreset.value)?.hint
    || '点一条用例直接跑：问题、角色、库范围会一起摆好，结果区会标出该看哪一项。'
))

const rolePickerShow = ref(false)
const kbPickerShow = ref(false)

// Vant Picker 的 modelValue 是数组，这里用 computed 保持选中项与表单同步
const rolePickerValues = computed(() => [form.role])
const kbPickerValues = computed(() => [selectedKbId.value || ALL_KB])

const roleLabel = computed(() => ROLE_OPTIONS.find((role) => role.value === form.role)?.text || form.role)

const kbColumns = computed(() => [
  {text: '全部库（不限定 kb_ids）', value: ALL_KB},
  ...kbs.value.map((kb) => ({text: `${kb.name}（${kb.code}）`, value: kb.id}))
])

const kbLabel = computed(() => {
  if (!selectedKbId.value) return '全部库（不限定 kb_ids）'
  const kb = kbs.value.find((item) => item.id === selectedKbId.value)
  return kb ? `${kb.name}（${kb.code}）` : selectedKbId.value
})

const shortId = (id) => (id ? String(id).slice(0, 8) : '—')
const kbName = (kb) => (kb && (kb.name || kb.code)) || (kb && kb.kb_id) || '未知'

// 拒答原因说人话：这四种的处置动作完全不同，混成一句「没有命中」等于没提示
const REASON_TEXT = {
  no_kb: '没有可检索的知识库（库被归档，或向量化/向量库不可用）',
  no_permission: '当前角色对这些库没有读权限（ACL 默认拒绝，不是没搜到）',
  no_hit: '召回为空：向量库里没有任何匹配的片段',
  low_score: '召回到了片段，但最高分低于判定阈值'
}

const reasonText = computed(() => {
  if (!result.value) return ''
  return REASON_TEXT[result.value.reason] || result.value.reason || '没有命中任何可用的知识片段'
})

const scoreHint = computed(() => {
  const r = result.value
  if (!r || r.reason !== 'low_score') return ''
  const source = r.score_source === 'rerank' ? '重排分' : '余弦相似度'
  return `top_score ${r.top_score} < 阈值 ${r.threshold_used}（${source}）`
})

const loadKbs = async () => {
  kbLoading.value = true
  try {
    const list = await getKbListApi()
    kbs.value = Array.isArray(list) ? list : []
    if (kbs.value.length > 0) {
      firstKbId.value = kbs.value[0].id
      // 默认「全部库」：默认选中列表第一个库时，很可能正好是当前角色无权访问的
      // 内部库（例如 kb_sop），一进页面就是「无权限 → 一律拒答」，白白吓自己一跳
      selectedKbId.value = ''
    }
  } catch (e) {
    // 拦截器已提示
  } finally {
    kbLoading.value = false
  }
}

const openRolePicker = () => {
  rolePickerShow.value = true
}

const onRoleConfirm = ({selectedOptions}) => {
  const value = selectedOptions && selectedOptions[0] && selectedOptions[0].value
  if (value) form.role = value
  rolePickerShow.value = false
}

const openKbPicker = () => {
  if (kbs.value.length === 0) {
    showToast('还没有知识库，请先创建')
    return
  }
  kbPickerShow.value = true
}

const onKbConfirm = ({selectedOptions}) => {
  const value = selectedOptions && selectedOptions[0] && selectedOptions[0].value
  selectedKbId.value = value === ALL_KB || !value ? '' : value
  kbPickerShow.value = false
}

const handleSearch = async () => {
  const query = form.query.trim()
  if (!query) {
    showToast('请输入检索问题')
    return
  }
  if (kbs.value.length === 0) {
    showToast('还没有知识库，请先创建并上传文档')
    return
  }

  // 路径必须带某个库的 id：优先用户所选，否则用第一个库兜底
  const pathKbId = selectedKbId.value || firstKbId.value
  if (!pathKbId) {
    showToast('暂无可用的知识库')
    return
  }

  let threshold
  if (form.threshold !== '' && form.threshold !== null && form.threshold !== undefined) {
    threshold = Number(form.threshold)
    if (Number.isNaN(threshold) || threshold < 0 || threshold > 1) {
      showToast('阈值需在 0 ~ 1 之间')
      return
    }
  }

  const payload = {
    query,
    role: form.role,
    kb_ids: selectedKbId.value ? [selectedKbId.value] : null
  }
  if (threshold !== undefined) payload.threshold = threshold

  submitting.value = true
  try {
    result.value = await searchTestApi(pathKbId, payload)
    lastRequest.value = {pathKbId, kbIds: payload.kb_ids}
  } catch (e) {
    // 拦截器已提示
  } finally {
    submitting.value = false
  }
}

// 一条用例 = 问题 + 角色 + 库范围，点完立刻检索，省掉现场拼组合
const applyPreset = async (preset) => {
  if (submitting.value) return
  if (kbs.value.length === 0) {
    showToast('还没有知识库，请先跑 dev.ps1 kb')
    return
  }

  let kbId = ''
  if (preset.kbCode) {
    const kb = kbs.value.find((item) => item.code === preset.kbCode)
    if (!kb) {
      showToast(`用例需要知识库 ${preset.kbCode}，请先跑 dev.ps1 kb`)
      return
    }
    kbId = kb.id
  }

  form.query = preset.query
  form.role = preset.role
  form.threshold = ''
  selectedKbId.value = kbId
  activePreset.value = preset.label
  await handleSearch()
}

onMounted(loadKbs)
</script>

<template>
  <div class="search-test-page">
    <Navbar/>

    <div class="page-container">
      <button class="back-link" @click="router.push('/admin')">
        <ArrowLeft :size="16"/>
        返回工作台
      </button>

      <div class="page-header">
        <h2>
          <FlaskConical :size="22"/>
          检索测试台
        </h2>
        <p>
          同一条 query，换一个角色，可检索的库、命中的片段和最终上下文都可能不同。
          ACL 在检索前就下推到向量库过滤，而不是「先召回再过滤」。
        </p>
      </div>

      <!-- 表单 -->
      <div class="panel form-panel">
        <div class="quick-row">
          <span class="quick-label">快捷用例</span>
          <button
              v-for="preset in QUICK_PRESETS"
              :key="preset.label"
              class="quick-chip"
              :class="{ active: activePreset === preset.label }"
              :disabled="submitting"
              @click="applyPreset(preset)"
          >
            {{ preset.label }}
          </button>
        </div>
        <p class="quick-hint">{{ activePresetHint }}</p>

        <van-field
            v-model="form.query"
            type="textarea"
            rows="2"
            autosize
            maxlength="500"
            show-word-limit
            placeholder="输入要检索的问题，例如：这个药怎么吃？"
            class="query-field"
        />

        <div class="form-grid">
          <van-field
              :model-value="roleLabel"
              label="检索身份"
              readonly
              is-link
              @click="openRolePicker"
          />
          <van-field
              :model-value="kbLabel"
              label="知识库范围"
              readonly
              is-link
              @click="openKbPicker"
          />
          <van-field
              v-model="form.threshold"
              label="阈值覆盖"
              type="number"
              placeholder="0 ~ 1，留空用库默认值"
          />
        </div>
        <p class="form-hint">
          选「全部库」时 kb_ids 传 null，检索范围 = 该角色能看的全部库；指定单个库时取两者的交集，
          交集为空就是 no_permission。无论选哪种范围，ACL 都在向量检索层生效。
        </p>

        <div class="form-actions">
          <span v-if="kbLoading" class="muted">正在加载知识库…</span>
          <span v-else-if="kbs.length === 0" class="muted">还没有知识库，请先到「知识库管理」创建</span>
          <span v-else class="muted">共 {{ kbs.length }} 个知识库可选</span>
          <van-button type="danger" round :loading="submitting" loading-text="检索中…" @click="handleSearch">
            <Search :size="16"/>
            开始检索
          </van-button>
        </div>
      </div>

      <!-- 结果 -->
      <template v-if="result">
        <div class="result-meta">
          <span>角色 <strong>{{ result.role }}</strong></span>
          <span>耗时 {{ result.latency_ms }} ms</span>
          <span>
            top_score {{ result.top_score }}
            <template v-if="result.threshold_used !== null && result.threshold_used !== undefined">
              / 阈值 {{ result.threshold_used }}
            </template>
          </span>
          <span v-if="result.score_source">
            打分口径 <strong>{{ result.score_source === 'rerank' ? '重排分' : '余弦相似度' }}</strong>
          </span>
          <span v-if="result.rewritten_query && result.rewritten_query !== result.query">
            改写后：{{ result.rewritten_query }}
          </span>
          <span v-if="lastRequest">
            请求：POST /admin/kb/{{ shortId(lastRequest.pathKbId) }}/search-test ·
            kb_ids {{ lastRequest.kbIds ? shortId(lastRequest.kbIds[0]) : 'null（全部可检索库）' }}
          </span>
        </div>

        <!-- 权限概览：本页的演示重点 -->
        <div class="panel">
          <div class="panel-header">
            <h3>
              <ShieldCheck :size="16"/>
              权限概览
            </h3>
            <span class="muted">角色 {{ result.role }}</span>
          </div>

          <div class="acl-row">
            <span class="acl-label allowed">可检索 {{ result.allowed_kbs.length }} 个</span>
            <div class="tags">
              <span v-if="result.allowed_kbs.length === 0" class="empty-text">没有可检索的知识库</span>
              <span v-for="kb in result.allowed_kbs" :key="kb.kb_id" class="tag allowed">
                {{ kbName(kb) }}
              </span>
            </div>
          </div>

          <div class="acl-row">
            <span class="acl-label filtered">被过滤 {{ result.filtered_out_kbs.length }} 个</span>
            <div class="tags">
              <span v-if="result.filtered_out_kbs.length === 0" class="empty-text">没有库被过滤</span>
              <span v-for="kb in result.filtered_out_kbs" :key="kb.kb_id" class="tag filtered">
                被过滤：{{ kbName(kb) }}
              </span>
            </div>
          </div>
        </div>

        <!-- 拒答提示 -->
        <div v-if="result.refused" class="refused-banner">
          <ShieldX :size="20"/>
          <div>
            <strong>已拒答</strong>
            <p>{{ reasonText }}</p>
            <p v-if="scoreHint" class="score-hint">{{ scoreHint }}</p>
          </div>
        </div>
        <div v-else-if="result.reason" class="reason-banner">
          <span>提示：{{ result.reason }}</span>
        </div>

        <!-- 命中 -->
        <div class="panel">
          <div class="panel-header">
            <h3>命中片段</h3>
            <span class="muted">
              共 {{ result.hits.length }} 条 · 已按分数倒序
              <template v-if="result.hits_are_rejected"> · 未达阈值，仅供参考</template>
            </span>
          </div>

          <van-notice-bar
              v-if="result.hits_are_rejected"
              wrapable
              :scrollable="false"
              text="这些片段通过了 ACL 过滤和召回，但分数没过阈值。要么问题本身太泛（考虑调低阈值），要么知识库里确实没有对应内容（考虑补文档）。"
              class="near-miss-tip"
          />

          <van-empty v-if="result.hits.length === 0" description="没有命中任何片段（零召回）"/>

          <div v-else class="hit-list">
            <div v-for="hit in result.hits" :key="hit.index" class="hit-card">
              <div class="hit-head">
                <span class="hit-index">{{ hit.index }}</span>
                <span class="hit-title">{{ hit.doc_title }}</span>
                <span v-if="hit.section" class="hit-section">{{ hit.section }}</span>
                <span v-if="hit.page !== null && hit.page !== undefined" class="hit-page">第 {{ hit.page }} 页</span>
                <span class="hit-score">{{ Number(hit.score).toFixed(4) }}</span>
              </div>
              <p class="hit-snippet">{{ hit.snippet }}</p>
            </div>
          </div>
        </div>

        <!-- 最终上下文 -->
        <div class="panel">
          <div class="panel-header">
            <h3>最终上下文</h3>
            <span class="muted">将交给大模型的内容</span>
          </div>
          <pre v-if="result.context" class="context-pre">{{ result.context }}</pre>
          <p v-else class="empty-text">没有可用上下文（零召回或被拒答）。</p>
        </div>
      </template>

      <van-empty v-else-if="!submitting" description="填写问题并选择身份，查看 ACL 过滤后的检索结果"/>
    </div>

    <!-- 角色选择 -->
    <van-popup v-model:show="rolePickerShow" position="bottom" round destroy-on-close>
      <van-picker
          :model-value="rolePickerValues"
          :columns="ROLE_OPTIONS"
          title="选择检索身份"
          @confirm="onRoleConfirm"
          @cancel="rolePickerShow = false"
      />
    </van-popup>

    <!-- 知识库选择 -->
    <van-popup v-model:show="kbPickerShow" position="bottom" round destroy-on-close>
      <van-picker
          :model-value="kbPickerValues"
          :columns="kbColumns"
          title="选择知识库范围"
          @confirm="onKbConfirm"
          @cancel="kbPickerShow = false"
      />
    </van-popup>
  </div>
</template>

<style scoped lang="scss">
.search-test-page {
  min-height: 100vh;
  background: #f3f4f6;
  padding-top: 64px;
  padding-bottom: 32px;

  .page-container {
    max-width: 1000px;
    margin: 0 auto;
    padding: 24px;
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
    margin-bottom: 12px;
    cursor: pointer;

    &:hover {
      color: #ef4444;
    }
  }

  .page-header {
    margin-bottom: 16px;

    h2 {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 22px;
      color: #111827;
      margin-bottom: 8px;
    }

    p {
      font-size: 13px;
      color: #6b7280;
      line-height: 1.7;
      max-width: 820px;
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
      align-items: center;
      gap: 12px;
      margin-bottom: 14px;

      h3 {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 16px;
        color: #374151;
      }
    }

    .muted {
      font-size: 12px;
      color: #9ca3af;
    }
  }

  .form-panel {
    .quick-row {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 8px;

      .quick-label {
        font-size: 12px;
        color: #9ca3af;
        margin-right: 2px;
      }

      .quick-chip {
        border: 1px solid #fecaca;
        background: #fff7f7;
        color: #b91c1c;
        border-radius: 999px;
        padding: 5px 12px;
        font-size: 12px;
        line-height: 1.4;
        cursor: pointer;
        transition: background-color 0.15s ease, color 0.15s ease;

        &:hover {
          background: #fee2e2;
        }

        &.active {
          background: #ef4444;
          border-color: #ef4444;
          color: #fff;
        }

        &:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
      }
    }

    .quick-hint {
      font-size: 12px;
      color: #6b7280;
      line-height: 1.6;
      margin-bottom: 14px;
    }

    .query-field {
      background: #f9fafb;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      margin-bottom: 12px;
    }

    .form-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 4px 12px;
    }

    .form-hint {
      font-size: 12px;
      color: #9ca3af;
      margin-top: 8px;
      line-height: 1.6;
    }

    .form-actions {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-top: 12px;
    }
  }

  .result-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 16px;
    font-size: 12px;
    color: #6b7280;
    background: #fff;
    border-radius: 10px;
    padding: 10px 16px;
    margin-bottom: 16px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);

    strong {
      color: #111827;
    }
  }

  .acl-row {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 10px 0;
    border-top: 1px dashed #f3f4f6;

    &:first-of-type {
      border-top: none;
      padding-top: 0;
    }

    .acl-label {
      flex-shrink: 0;
      font-size: 12px;
      font-weight: 600;
      border-radius: 10px;
      padding: 2px 8px;
      margin-top: 2px;

      &.allowed {
        color: #059669;
        background: #ecfdf5;
      }

      &.filtered {
        color: #6b7280;
        background: #f3f4f6;
      }
    }

    .tags {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .tag {
      font-size: 12px;
      border-radius: 10px;
      padding: 2px 10px;
      line-height: 1.6;

      &.allowed {
        color: #047857;
        background: #d1fae5;
      }

      &.filtered {
        color: #6b7280;
        background: #f3f4f6;
        text-decoration: line-through;
        text-decoration-color: #d1d5db;
      }
    }
  }

  .refused-banner {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    background: #fef2f2;
    border: 1px solid #fecaca;
    color: #dc2626;
    border-radius: 10px;
    padding: 14px 16px;
    margin-bottom: 16px;

    strong {
      display: block;
      font-size: 14px;
      margin-bottom: 4px;
    }

    p {
      font-size: 13px;
      line-height: 1.6;
      color: #b91c1c;
    }

    .score-hint {
      margin-top: 4px;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
      color: #991b1b;
    }
  }

  .near-miss-tip {
    margin-bottom: 12px;
    border-radius: 8px;
  }

  .reason-banner {
    background: #fffbeb;
    border: 1px solid #fde68a;
    color: #b45309;
    border-radius: 10px;
    padding: 10px 14px;
    font-size: 13px;
    margin-bottom: 16px;
  }

  .hit-list {
    .hit-card {
      border: 1px solid #f3f4f6;
      border-radius: 10px;
      padding: 12px 14px;
      margin-bottom: 10px;
      background: #fcfcfd;

      &:last-child {
        margin-bottom: 0;
      }

      .hit-head {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 8px;
        margin-bottom: 8px;

        .hit-index {
          width: 20px;
          height: 20px;
          line-height: 20px;
          text-align: center;
          border-radius: 50%;
          background: #ef4444;
          color: #fff;
          font-size: 11px;
          flex-shrink: 0;
        }

        .hit-title {
          font-size: 14px;
          font-weight: 600;
          color: #111827;
        }

        .hit-section,
        .hit-page {
          font-size: 11px;
          color: #2563eb;
          background: #eff6ff;
          border-radius: 8px;
          padding: 1px 7px;
        }

        .hit-page {
          color: #6b7280;
          background: #f3f4f6;
        }

        .hit-score {
          margin-left: auto;
          font-size: 12px;
          font-weight: 700;
          color: #059669;
          background: #ecfdf5;
          border-radius: 8px;
          padding: 1px 8px;
          font-variant-numeric: tabular-nums;
        }
      }

      .hit-snippet {
        font-size: 13px;
        line-height: 1.7;
        color: #4b5563;
        word-break: break-word;
      }
    }
  }

  .context-pre {
    margin: 0;
    max-height: 420px;
    overflow: auto;
    background: #0f172a;
    color: #e2e8f0;
    border-radius: 8px;
    padding: 14px 16px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 12.5px;
    line-height: 1.7;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .empty-text {
    font-size: 13px;
    color: #9ca3af;
  }

  @media (max-width: 768px) {
    .page-container {
      padding: 12px;
    }

    .form-panel .form-grid {
      grid-template-columns: 1fr;
    }

    .form-actions {
      flex-direction: column;
      align-items: stretch;
      gap: 10px;
    }

    .panel {
      padding: 16px 12px;
    }

    .page-header h2 {
      font-size: 19px;
    }
  }
}
</style>
