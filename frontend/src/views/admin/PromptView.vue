<script setup>
/**
 * Prompt 版本管理（M4，路由 /admin/prompts，仅 admin）。
 *
 * 左：code 列表（版本数 + 线上版本）；右：该 code 的版本表。
 * 「设为 production」= 上线 / 回滚：PUT status=production 后后端会把同 code 的其它
 * production 归档，所以列表必须整体重新拉，不能在本地改一行了事。
 * 另有灰度演示（resolve）与变量预览（preview）两个只读操作。
 */
import {computed, onMounted, ref} from 'vue'
import {useRouter} from 'vue-router'
import dayjs from 'dayjs'
import {showToast} from 'vant'
import {
  ArrowLeft,
  Eye,
  FileCode2,
  Pencil,
  Plus,
  Rocket,
  ShieldAlert,
  X
} from 'lucide-vue-next'
import Navbar from '../../components/Navbar.vue'
import {
  createPrompt,
  listPrompts,
  previewPrompt,
  resolvePrompt,
  updatePrompt
} from '../../api/prompts'

const router = useRouter()

const PROMPT_STATUS = {
  draft: {text: '草稿', color: '#6b7280', bg: '#f3f4f6'},
  testing: {text: '测试', color: '#d97706', bg: '#fffbeb'},
  production: {text: '线上', color: '#059669', bg: '#ecfdf5'},
  archived: {text: '归档', color: '#9ca3af', bg: '#f9fafb'}
}

const CODE_RE = /^[a-z0-9_]{2,64}$/

// 预览默认变量：故意不带 today，方便演示「缺少变量」提示
const DEFAULT_VARIABLES = '{\n  "agent_name": "AI 药师",\n  "role": "patient"\n}'

const prompts = ref([])
const loading = ref(true)
const error = ref('')
const forbidden = ref(false)
const selectedCode = ref('')

const acting = ref('')

/* ------------------------------------------------------------------ *
 * 列表聚合
 * ------------------------------------------------------------------ */

const codes = computed(() => {
  const map = new Map()
  prompts.value.forEach((item) => {
    if (!item || !item.code) return
    if (!map.has(item.code)) {
      map.set(item.code, {
        code: item.code,
        count: 0,
        productionVersion: null,
        latestUpdatedAt: null,
        versions: []
      })
    }
    const entry = map.get(item.code)
    entry.count += 1
    entry.versions.push(item.version)
    if (item.status === 'production') entry.productionVersion = item.version
    if (!entry.latestUpdatedAt || dayjs(item.updated_at).valueOf() > dayjs(entry.latestUpdatedAt).valueOf()) {
      entry.latestUpdatedAt = item.updated_at
    }
  })
  return [...map.values()].sort((a, b) => String(a.code).localeCompare(String(b.code)))
})

const versions = computed(() => (
  prompts.value
    .filter((item) => item && item.code === selectedCode.value)
    .slice()
    .sort((a, b) => Number(b.version) - Number(a.version))
))

const currentCode = computed(() => (
  codes.value.find((item) => item.code === selectedCode.value) || null
))

const statusMeta = (status) => PROMPT_STATUS[status] || {text: status || '未知', color: '#6b7280', bg: '#f3f4f6'}

const formatTime = (value) => {
  if (!value) return '-'
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('MM-DD HH:mm') : '-'
}

const rolloutText = (value) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? `${Math.round(parsed)}%` : '-'
}

const excerpt = (content) => {
  const text = String(content || '').replace(/\s+/g, ' ').trim()
  return text.length > 80 ? `${text.slice(0, 80)}…` : text
}

/* ------------------------------------------------------------------ *
 * 加载
 * ------------------------------------------------------------------ */

const loadPrompts = async ({silent = false} = {}) => {
  if (!silent) loading.value = true
  try {
    const data = await listPrompts()
    prompts.value = Array.isArray(data) ? data : []
    error.value = ''
    // 选中的 code 被删空 / 首次进入：回落到第一个 code
    if (!codes.value.some((item) => item.code === selectedCode.value)) {
      selectedCode.value = codes.value.length ? codes.value[0].code : ''
    }
  } catch (e) {
    if (e && (e.status === 403 || e.status === 401)) {
      forbidden.value = true
      prompts.value = []
    } else if (!silent) {
      error.value = (e && e.message) || 'Prompt 列表加载失败，请稍后重试'
    } else {
      showToast({type: 'fail', message: (e && e.message) || '刷新失败'})
    }
  } finally {
    loading.value = false
  }
}

/* ------------------------------------------------------------------ *
 * 新建 / 编辑
 * ------------------------------------------------------------------ */

const formVisible = ref(false)
const isEdit = ref(false)
const editingId = ref('')
const saving = ref(false)
const formError = ref('')

const emptyForm = () => ({
  code: '',
  content: '',
  labels: '',
  rollout: '100',
  status: 'testing',
  model: ''
})

const form = ref(emptyForm())

const openCreate = () => {
  isEdit.value = false
  editingId.value = ''
  form.value = {...emptyForm(), code: selectedCode.value || ''}
  formError.value = ''
  formVisible.value = true
}

const openEdit = (row) => {
  isEdit.value = true
  editingId.value = row.id
  form.value = {
    code: row.code,
    content: row.content || '',
    labels: Array.isArray(row.labels) ? row.labels.join(',') : '',
    rollout: String(row.rollout ?? 100),
    status: row.status || 'draft',
    model: row.model || ''
  }
  formError.value = ''
  formVisible.value = true
}

// 逗号（中英文都认）分隔 → 去空去重
const parseLabels = (text) => {
  const parts = String(text || '')
    .split(/[,，]/)
    .map((item) => item.trim())
    .filter((item) => item.length > 0)
  return [...new Set(parts)]
}

const validateForm = () => {
  const code = (form.value.code || '').trim().toLowerCase()
  if (!CODE_RE.test(code)) return 'code 只能包含 2 ~ 64 位小写字母、数字或下划线'
  if (!(form.value.content || '').trim()) return '模板内容不能为空'
  const rollout = Number(form.value.rollout)
  if (form.value.rollout === '' || !Number.isInteger(rollout) || rollout < 0 || rollout > 100) {
    return '灰度比例需要是 0 ~ 100 的整数'
  }
  return ''
}

const submitForm = async () => {
  if (saving.value) return
  const message = validateForm()
  if (message) {
    formError.value = message
    return
  }
  formError.value = ''

  const code = (form.value.code || '').trim().toLowerCase()
  const content = form.value.content.trim()
  const labels = parseLabels(form.value.labels)
  const rollout = Number(form.value.rollout)
  const model = (form.value.model || '').trim()

  saving.value = true
  try {
    if (isEdit.value) {
      const payload = {content, labels, rollout, status: form.value.status}
      if (model) payload.model = model
      await updatePrompt(editingId.value, payload)
    } else {
      const payload = {code, content, labels, rollout, status: form.value.status}
      if (model) payload.model = model
      await createPrompt(payload)
    }
    formVisible.value = false
    showToast({type: 'success', message: isEdit.value ? '已保存修改' : `已新建 ${code} 版本`})
    selectedCode.value = code
    await loadPrompts({silent: true})
  } catch (e) {
    // 后端 detail 直接展示在弹窗里，改完能接着提交
    formError.value = (e && e.message) || '保存失败，请稍后重试'
  } finally {
    saving.value = false
  }
}

/* ------------------------------------------------------------------ *
 * 设为 production（上线 / 回滚）
 * ------------------------------------------------------------------ */

const setProduction = async (row) => {
  if (!row || acting.value) return
  if (row.status === 'production') return
  acting.value = row.id
  try {
    await updatePrompt(row.id, {status: 'production'})
    showToast({type: 'success', message: `v${row.version} 已上线，同 code 其它线上版本已归档`})
    await loadPrompts({silent: true})
  } catch (e) {
    showToast({type: 'fail', message: (e && e.message) || '上线失败，请稍后重试'})
  } finally {
    acting.value = ''
  }
}

/* ------------------------------------------------------------------ *
 * 预览
 * ------------------------------------------------------------------ */

const previewTarget = ref(null)
const variablesText = ref(DEFAULT_VARIABLES)
const previewRendered = ref(null)
const previewMissing = ref([])
const previewUsed = ref([])
const previewLoading = ref(false)
const previewError = ref('')

const closePreview = () => {
  previewTarget.value = null
  previewRendered.value = null
  previewMissing.value = []
  previewUsed.value = []
  previewError.value = ''
}

const openPreview = (row) => {
  previewTarget.value = row
  previewRendered.value = null
  previewMissing.value = []
  previewUsed.value = []
  previewError.value = ''
  // 换一个版本时给一份干净的变量示例，避免上一次的残缺 JSON 一直报错
  if (!variablesText.value.trim()) variablesText.value = DEFAULT_VARIABLES
}

const runPreview = async () => {
  if (!previewTarget.value || previewLoading.value) return
  let variables = {}
  const text = variablesText.value.trim()
  if (text) {
    try {
      variables = JSON.parse(text)
    } catch (e) {
      previewError.value = '变量需要是合法 JSON，例如 {"agent_name": "AI 药师"}'
      return
    }
    if (!variables || typeof variables !== 'object' || Array.isArray(variables)) {
      previewError.value = '变量需要是一个 JSON 对象'
      return
    }
  }

  previewLoading.value = true
  previewError.value = ''
  try {
    const data = await previewPrompt(previewTarget.value.id, variables)
    previewRendered.value = data && data.rendered !== undefined ? String(data.rendered) : ''
    previewMissing.value = Array.isArray(data && data.missing) ? data.missing : []
    previewUsed.value = Array.isArray(data && data.used) ? data.used : []
  } catch (e) {
    previewError.value = (e && e.message) || '预览失败，请稍后重试'
  } finally {
    previewLoading.value = false
  }
}

/* ------------------------------------------------------------------ *
 * 灰度演示
 * ------------------------------------------------------------------ */

const userKey = ref('patient-1')
const resolveLoading = ref(false)
const resolveResult = ref(null)
const resolveError = ref('')

const runResolve = async () => {
  if (!selectedCode.value || resolveLoading.value) return
  const key = userKey.value.trim()
  if (!key) {
    resolveError.value = '先填一个 user_key，例如 patient-1'
    return
  }
  resolveLoading.value = true
  resolveError.value = ''
  resolveResult.value = null
  try {
    const data = await resolvePrompt(selectedCode.value, key)
    resolveResult.value = data || null
  } catch (e) {
    resolveError.value = (e && e.message) || '解析失败，请稍后重试'
  } finally {
    resolveLoading.value = false
  }
}

const resolveResultText = computed(() => {
  const data = resolveResult.value
  if (!data) return ''
  const parts = [
    `命中 v${data.version ?? '-'}`,
    `状态 ${statusMeta(data.status).text}`,
    `灰度 ${rolloutText(data.rollout)}`
  ]
  if (data.reason) parts.push(`原因：${data.reason}`)
  return parts.join(' · ')
})

// 切换 code：清掉上一个 code 的预览 / 灰度结果，避免结果串到别的版本上
const selectCode = (code) => {
  selectedCode.value = code
  closePreview()
  resolveResult.value = null
  resolveError.value = ''
}

onMounted(loadPrompts)
</script>

<template>
  <div class="prompt-page">
    <Navbar/>

    <div class="page-container">
      <!-- 页头 -->
      <div class="page-header">
        <div class="title-block">
          <button class="back-link" @click="router.push('/admin')">
            <ArrowLeft :size="16"/>
            返回工作台
          </button>
          <h2>Prompt 版本</h2>
          <p>按 code 管理模板版本：灰度发布、上线 / 回滚，以及上线前的变量预览。</p>
        </div>
        <van-button type="danger" round size="small" icon="plus" @click="openCreate">
          新建版本
        </van-button>
      </div>

      <!-- 无权访问 -->
      <section v-if="forbidden" class="state-card">
        <ShieldAlert :size="30" color="#ef4444"/>
        <h3>仅管理员可用</h3>
        <p>当前账号没有管理 Prompt 的权限（需要 admin 角色）。</p>
        <button type="button" class="ghost-btn" @click="router.push('/')">返回首页</button>
      </section>

      <!-- 错误态 -->
      <section v-else-if="error" class="state-card is-error">
        <ShieldAlert :size="26" color="#ef4444"/>
        <h3>列表加载失败</h3>
        <p>{{ error }}</p>
        <button type="button" class="ghost-btn" :disabled="loading" @click="loadPrompts()">重试</button>
      </section>

      <div v-else-if="loading" class="loading-wrap">
        <van-loading size="22">加载中…</van-loading>
      </div>

      <!-- 空态 -->
      <section v-else-if="codes.length === 0" class="state-card">
        <FileCode2 :size="30" color="#9ca3af"/>
        <h3>还没有 Prompt 模板</h3>
        <p>新建第一个版本，后台就会按 code + version 管理起来。</p>
        <button type="button" class="primary-btn" @click="openCreate">
          <Plus :size="13"/>
          新建版本
        </button>
      </section>

      <!-- 主体：左 code 列表 + 右 版本表 -->
      <div v-else class="prompt-panel">
        <aside class="code-panel">
          <div class="panel-head">
            <h3>Prompt Code</h3>
            <span class="muted">{{ codes.length }} 个</span>
          </div>

          <ul class="code-list">
            <li
                v-for="item in codes"
                :key="item.code"
                class="code-item"
                :class="{ active: item.code === selectedCode }"
                @click="selectCode(item.code)"
            >
              <div class="code-name">{{ item.code }}</div>
              <div class="code-meta">
                <span>{{ item.count }} 个版本</span>
                <span v-if="item.productionVersion !== null" class="prod-tag">
                  线上 v{{ item.productionVersion }}
                </span>
                <span v-else class="muted-tag">无线上版本</span>
              </div>
            </li>
          </ul>
        </aside>

        <section class="version-panel">
          <div class="panel-head">
            <h3>{{ selectedCode }} 的版本</h3>
            <span class="muted">
              {{ versions.length }} 个版本
              <template v-if="currentCode && currentCode.productionVersion !== null">
                · 线上 v{{ currentCode.productionVersion }}
              </template>
            </span>
          </div>

          <div class="panel-body">
            <div v-if="versions.length === 0" class="panel-empty">
              <p>这个 code 还没有版本</p>
            </div>

            <div v-else class="table-wrap">
              <table class="version-table">
                <thead>
                <tr>
                  <th>版本</th>
                  <th>状态</th>
                  <th>灰度</th>
                  <th>更新时间</th>
                  <th class="ops-col">操作</th>
                </tr>
                </thead>
                <tbody>
                <tr v-for="row in versions" :key="row.id">
                  <td>
                    <div class="version-name">
                      v{{ row.version }}
                      <span v-if="Array.isArray(row.labels) && row.labels.length" class="label-tags">
                        <span v-for="label in row.labels" :key="label" class="label-tag">{{ label }}</span>
                      </span>
                    </div>
                    <div class="version-excerpt" :title="row.content">{{ excerpt(row.content) }}</div>
                  </td>
                  <td>
                    <span
                        class="badge"
                        :style="{color: statusMeta(row.status).color, backgroundColor: statusMeta(row.status).bg}"
                    >
                      {{ statusMeta(row.status).text }}
                    </span>
                  </td>
                  <td class="num">{{ rolloutText(row.rollout) }}</td>
                  <td class="num">{{ formatTime(row.updated_at) }}</td>
                  <td class="ops-col">
                    <div class="ops">
                      <button
                          type="button"
                          class="op-btn primary"
                          :disabled="row.status === 'production' || acting === row.id"
                          :title="row.status === 'production' ? '这个版本已经是线上版本' : '上线 / 回滚到这一版'"
                          @click="setProduction(row)"
                      >
                        <Rocket :size="14"/>
                        {{ acting === row.id ? '上线中…' : '设为 production' }}
                      </button>
                      <button type="button" class="op-btn" @click="openEdit(row)">
                        <Pencil :size="14"/>编辑
                      </button>
                      <button type="button" class="op-btn" @click="openPreview(row)">
                        <Eye :size="14"/>预览
                      </button>
                    </div>
                  </td>
                </tr>
                </tbody>
              </table>
            </div>

            <!-- 灰度演示 -->
            <div class="resolve-block">
              <div class="block-head">
                <h4>灰度演示</h4>
                <span class="muted">按 user_id hash 落桶，输入任意字符串看命中哪一版</span>
              </div>
              <div class="resolve-row">
                <input
                    v-model="userKey"
                    class="text-input"
                    type="text"
                    placeholder="随便填，例如 patient-1"
                    @keyup.enter="runResolve"
                />
                <button
                    type="button"
                    class="primary-btn"
                    :disabled="resolveLoading || !selectedCode"
                    @click="runResolve"
                >
                  {{ resolveLoading ? '解析中…' : '解析命中版本' }}
                </button>
              </div>
              <div v-if="resolveResult" class="resolve-result">✓ {{ resolveResultText }}</div>
              <p v-if="resolveError" class="error-text">{{ resolveError }}</p>
            </div>

            <!-- 预览结果 -->
            <div v-if="previewTarget" class="preview-block">
              <div class="block-head">
                <h4>预览 v{{ previewTarget.version }} · {{ previewTarget.code }}</h4>
                <button type="button" class="icon-btn" @click="closePreview">
                  <X :size="16"/>
                </button>
              </div>
              <p class="hint">变量用 JSON 填，未提供的变量会在下面提示「缺少变量」。</p>
              <textarea v-model="variablesText" class="variables-input" rows="4" spellcheck="false"></textarea>
              <div class="preview-actions">
                <button
                    type="button"
                    class="primary-btn"
                    :disabled="previewLoading"
                    @click="runPreview"
                >
                  {{ previewLoading ? '渲染中…' : '渲染预览' }}
                </button>
                <span v-if="previewMissing.length" class="warning-text">
                  缺少变量：{{ previewMissing.join('、') }}
                </span>
              </div>
              <p v-if="previewError" class="error-text">{{ previewError }}</p>
              <pre v-if="previewRendered !== null" class="preview-rendered">{{ previewRendered }}</pre>
              <p v-if="previewUsed.length" class="hint">已使用变量：{{ previewUsed.join('、') }}</p>
            </div>
          </div>
        </section>
      </div>
    </div>

    <!-- 新建 / 编辑弹窗 -->
    <van-popup
        v-model:show="formVisible"
        position="center"
        round
        :close-on-click-overlay="false"
        :style="{width: '92%', maxWidth: '640px', maxHeight: '90vh'}"
    >
      <div class="prompt-form">
        <div class="form-header">
          <h3>{{ isEdit ? '编辑版本' : '新建版本' }}</h3>
          <button type="button" class="icon-btn" @click="formVisible = false">
            <X :size="18"/>
          </button>
        </div>

        <div class="form-body">
          <van-field
              v-model="form.code"
              label="code"
              label-width="72"
              placeholder="如：drug_consult"
              maxlength="64"
              :disabled="isEdit"
              required
          />
          <p class="field-hint">
            {{ isEdit ? 'code 创建后不可修改。' : '新 code 会从 v1 开始；已有 code 会自动 +1 版本。' }}
          </p>

          <div class="field-block">
            <label class="field-label">模板内容</label>
            <textarea
                v-model="form.content"
                class="content-input"
                rows="10"
                spellcheck="false"
                placeholder="支持 {variable} 占位符，例如：你是{agent_name}，请用{role}能懂的话回答。"
            ></textarea>
          </div>

          <van-field v-model="form.labels" label="labels" label-width="72" placeholder="逗号分隔，如：v2,stable"/>
          <p class="field-hint">labels 用于标记版本用途，逗号分隔即可（选填）。</p>

          <van-field v-model="form.rollout" label="灰度" label-width="72" type="number" placeholder="0 ~ 100"/>
          <p class="field-hint">0 ~ 100 的整数，按 user_id hash 灰度；只有 production 版本会真正影响线上。</p>

          <van-field label="状态" label-width="72">
            <template #input>
              <van-radio-group v-model="form.status" direction="horizontal" class="radio-group">
                <van-radio name="draft">草稿</van-radio>
                <van-radio name="testing">测试</van-radio>
                <van-radio name="production">线上</van-radio>
                <van-radio name="archived">归档</van-radio>
              </van-radio-group>
            </template>
          </van-field>
          <p class="field-hint">新建建议先「测试」；选「线上」等于立即上线，同 code 其它线上版本会被归档。</p>

          <van-field v-model="form.model" label="模型" label-width="72" placeholder="选填，如 gpt-4o-mini"/>

          <p v-if="formError" class="form-error">{{ formError }}</p>
        </div>

        <div class="form-footer">
          <van-button plain round @click="formVisible = false">取消</van-button>
          <van-button type="danger" round :loading="saving" @click="submitForm">
            {{ isEdit ? '保存修改' : '创建版本' }}
          </van-button>
        </div>
      </div>
    </van-popup>
  </div>
</template>

<style scoped lang="scss">
.prompt-page {
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
      max-width: 440px;
    }
  }

  .loading-wrap {
    padding: 48px 0;
    display: flex;
    justify-content: center;
    background: #fff;
    border-radius: 12px;
  }

  .primary-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
    height: 30px;
    padding: 0 14px;
    border: none;
    border-radius: 8px;
    background: linear-gradient(135deg, #ef4444, #b91c1c);
    color: #fff;
    font-size: 12.5px;
    font-weight: 600;
    white-space: nowrap;
    cursor: pointer;

    &:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }
  }

  .ghost-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
    height: 28px;
    padding: 0 12px;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    background: #fff;
    color: #6b7280;
    font-size: 12px;
    cursor: pointer;

    &:hover:not(:disabled) {
      border-color: #fecaca;
      color: #b91c1c;
    }
  }

  .prompt-panel {
    display: grid;
    grid-template-columns: 248px 1fr;
    align-items: start;
    gap: 16px;
  }

  .code-panel,
  .version-panel {
    background: #fff;
    border-radius: 12px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    overflow: hidden;
  }

  .code-panel {
    position: sticky;
    top: 80px;
  }

  .panel-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 8px;
    padding: 14px 16px;
    border-bottom: 1px solid #f3f4f6;

    h3 {
      font-size: 14px;
      color: #374151;
    }
  }

  .muted {
    font-size: 12px;
    color: #9ca3af;
  }

  .code-list {
    list-style: none;
    margin: 0;
    padding: 8px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    max-height: 60vh;
    overflow-y: auto;
  }

  .code-item {
    padding: 9px 10px;
    border-radius: 8px;
    border: 1px solid transparent;
    cursor: pointer;
    transition: background-color 0.15s ease, border-color 0.15s ease;

    &:hover {
      background: #f9fafb;
    }

    &.active {
      background: #fff7f7;
      border-color: #fecaca;
    }

    .code-name {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12.5px;
      font-weight: 600;
      color: #111827;
      word-break: break-all;
    }

    .code-meta {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      margin-top: 4px;
      font-size: 11px;
      color: #9ca3af;
    }

    .prod-tag {
      padding: 0 6px;
      border-radius: 5px;
      background: #ecfdf5;
      color: #047857;
      font-size: 10.5px;
      line-height: 16px;
    }

    .muted-tag {
      color: #9ca3af;
    }
  }

  .version-panel {
    min-width: 0;
  }

  .panel-body {
    padding: 16px;
  }

  .panel-empty {
    padding: 32px 12px;
    text-align: center;
    font-size: 13px;
    color: #9ca3af;
  }

  .table-wrap {
    overflow-x: auto;
  }

  .version-table {
    width: 100%;
    border-collapse: collapse;
    min-width: 640px;

    th,
    td {
      text-align: left;
      padding: 11px 10px;
      border-bottom: 1px solid #f3f4f6;
      font-size: 13px;
      color: #374151;
      vertical-align: top;
    }

    th {
      font-weight: 500;
      color: #6b7280;
      font-size: 12px;
      background: #f9fafb;
    }

    tbody tr:hover {
      background: #fafafa;
    }

    .num {
      color: #111827;
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }
  }

  .version-name {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    font-weight: 600;
    color: #111827;
  }

  .label-tags {
    display: inline-flex;
    flex-wrap: wrap;
    gap: 4px;
  }

  .label-tag {
    padding: 0 5px;
    border-radius: 4px;
    background: #eff6ff;
    color: #1d4ed8;
    font-size: 10px;
    line-height: 15px;
    font-weight: 400;
  }

  .version-excerpt {
    margin-top: 4px;
    max-width: 380px;
    font-size: 11.5px;
    line-height: 1.6;
    color: #9ca3af;
    word-break: break-word;
  }

  .badge {
    display: inline-block;
    font-size: 11.5px;
    padding: 1px 8px;
    border-radius: 10px;
    white-space: nowrap;
  }

  .ops-col {
    width: 250px;
  }

  .ops {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .op-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    border: 1px solid #e5e7eb;
    background: #fff;
    color: #4b5563;
    font-size: 12px;
    padding: 4px 8px;
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.15s;
    white-space: nowrap;

    &:hover:not(:disabled) {
      border-color: #d1d5db;
      background: #f9fafb;
    }

    &.primary {
      color: #b91c1c;
      border-color: #fecaca;

      &:hover:not(:disabled) {
        background: #fef2f2;
      }
    }

    &:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }
  }

  .resolve-block,
  .preview-block {
    margin-top: 18px;
    padding-top: 16px;
    border-top: 1px dashed #e5e7eb;
  }

  .block-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
    margin-bottom: 10px;

    h4 {
      font-size: 13.5px;
      color: #374151;
    }
  }

  .resolve-row {
    display: flex;
    gap: 8px;

    .text-input {
      flex: 1;
      min-width: 0;
      height: 30px;
      padding: 0 10px;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      background: #f9fafb;
      color: #374151;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12.5px;
      outline: none;

      &:focus {
        border-color: #fca5a5;
        background: #fff;
      }
    }
  }

  .resolve-result {
    margin-top: 10px;
    padding: 8px 12px;
    border-radius: 8px;
    background: #ecfdf5;
    border: 1px solid #a7f3d0;
    color: #047857;
    font-size: 12.5px;
    line-height: 1.6;
    word-break: break-word;
  }

  .hint {
    font-size: 12px;
    color: #9ca3af;
    line-height: 1.6;
  }

  .variables-input,
  .content-input {
    width: 100%;
    padding: 8px 10px;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    background: #f9fafb;
    color: #374151;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 12.5px;
    line-height: 1.6;
    resize: vertical;
    outline: none;

    &:focus {
      border-color: #fca5a5;
      background: #fff;
    }
  }

  .variables-input {
    margin: 8px 0;
    min-height: 84px;
  }

  .preview-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
  }

  .warning-text {
    font-size: 12px;
    color: #b45309;
  }

  .error-text {
    margin-top: 8px;
    font-size: 12.5px;
    color: #b91c1c;
    line-height: 1.6;
  }

  .preview-rendered {
    margin: 10px 0 0;
    padding: 12px 14px;
    max-height: 340px;
    overflow: auto;
    border-radius: 8px;
    background: #0f172a;
    color: #e2e8f0;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 12.5px;
    line-height: 1.7;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .prompt-form {
    display: flex;
    flex-direction: column;
    max-height: 90vh;

    .form-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 16px 20px;
      border-bottom: 1px solid #f3f4f6;

      h3 {
        font-size: 16px;
        color: #111827;
      }
    }

    .form-body {
      padding: 8px 12px 0;
      overflow-y: auto;
    }

    .field-block {
      padding: 8px 16px 0;

      .field-label {
        display: block;
        margin-bottom: 6px;
        font-size: 13px;
        color: #374151;
      }
    }

    .field-hint {
      font-size: 12px;
      color: #9ca3af;
      line-height: 1.5;
      padding: 0 16px 10px;
      margin-top: -4px;
    }

    .form-error {
      margin: 4px 16px 8px;
      font-size: 13px;
      color: #dc2626;
      background: #fef2f2;
      border-radius: 6px;
      padding: 8px 10px;
    }

    .form-footer {
      display: flex;
      justify-content: flex-end;
      gap: 10px;
      padding: 12px 20px 16px;
      border-top: 1px solid #f3f4f6;
    }
  }

  .icon-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 4px;
    border: none;
    background: transparent;
    color: #9ca3af;
    cursor: pointer;

    &:hover {
      color: #4b5563;
    }
  }

  @media (max-width: 900px) {
    .prompt-panel {
      grid-template-columns: 1fr;
    }

    .code-panel {
      position: static;
    }

    .code-list {
      flex-direction: row;
      flex-wrap: wrap;
      max-height: none;

      .code-item {
        flex: 1 1 160px;
      }
    }
  }

  @media (max-width: 768px) {
    .page-container {
      padding: 12px;
    }

    .page-header h2 {
      font-size: 19px;
    }

    .panel-body {
      padding: 12px;
    }

    .resolve-row {
      flex-direction: column;
    }
  }
}

// van-radio 是子组件，需要 :deep 才能影响内部间距
.radio-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;

  :deep(.van-radio) {
    margin-right: 14px;
    margin-bottom: 4px;
  }
}
</style>
