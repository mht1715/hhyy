<script setup>
// KeepAlive 依赖组件名（App.vue 的 CACHED 白名单按 name 匹配）
defineOptions({name: 'KbListView'})

import {ref, computed, onMounted} from 'vue'
import {useRouter} from 'vue-router'
import {showToast, showConfirmDialog} from 'vant'
import {ArrowLeft, Eye, Pencil, Trash2, X, Database, FileText, Layers, Search} from 'lucide-vue-next'
import Navbar from '../../components/Navbar.vue'
import {getKbListApi, getKbStatsApi, createKbApi, updateKbApi, deleteKbApi} from '../../api/kb'

const router = useRouter()

const kbs = ref([])
const stats = ref(null)
const loading = ref(true)

// 新建 / 编辑弹窗
const formVisible = ref(false)
const isEdit = ref(false)
const editingId = ref(null)
const saving = ref(false)
const formError = ref('')
const strategyPickerShow = ref(false)
const visibilityPickerShow = ref(false)
// 分段策略 / 可见性 / 状态的中文文案
const CHUNK_STRATEGY_TEXT = {structured: '结构化', recursive: '递归'}
const KB_STATUS = {
  draft: {text: '草稿', color: '#d97706', bg: '#fffbeb'},
  active: {text: '启用', color: '#059669', bg: '#ecfdf5'},
  archived: {text: '归档', color: '#6b7280', bg: '#f3f4f6'}
}

const emptyForm = () => ({
  code: '',
  name: '',
  description: '',
  chunk_strategy: 'structured',
  visibility: 'private',
  score_threshold: '0.3',
  status: 'draft'
})

const form = ref(emptyForm())

const statusMeta = (status) => KB_STATUS[status] || {text: status || '未知', color: '#6b7280', bg: '#f3f4f6'}
const visibilityText = (visibility) => (visibility === 'public' ? '公开' : '私有')

const STRATEGY_OPTIONS = [
  {text: '结构化：按标题 / 段落切分', value: 'structured'},
  {text: '递归：按长度递归切分', value: 'recursive'}
]
const VISIBILITY_OPTIONS = [
  {text: '私有：仅显式授权的角色可检索', value: 'private'},
  {text: '公开：所有角色（含访客）可见', value: 'public'}
]

const strategyLabel = computed(() => CHUNK_STRATEGY_TEXT[form.value.chunk_strategy] || form.value.chunk_strategy || '—')
const visibilityLabel = computed(() => visibilityText(form.value.visibility))
const strategyPickerValues = computed(() => [form.value.chunk_strategy])
const visibilityPickerValues = computed(() => [form.value.visibility])

const onStrategyConfirm = ({selectedOptions}) => {
  const value = selectedOptions && selectedOptions[0] && selectedOptions[0].value
  if (value) form.value.chunk_strategy = value
  strategyPickerShow.value = false
}

const onVisibilityConfirm = ({selectedOptions}) => {
  const value = selectedOptions && selectedOptions[0] && selectedOptions[0].value
  if (value) form.value.visibility = value
  visibilityPickerShow.value = false
}

// 顶部统计卡片
const statCards = computed(() => {
  const s = stats.value || {}
  return [
    {title: '知识库', value: s.kb_count ?? '—', icon: Database, color: '#3b82f6', bg: '#eff6ff', sub: '含草稿 / 归档'},
    {title: '文档', value: s.document_count ?? '—', icon: FileText, color: '#10b981', bg: '#ecfdf5', sub: '全部来源文档'},
    {title: '向量分段', value: s.chunk_count ?? '—', icon: Layers, color: '#8b5cf6', bg: '#f5f3ff', sub: '可被检索的最小单元'},
    {
      title: '近 7 日检索',
      value: s.searches_7d ?? '—',
      icon: Search,
      color: '#ef4444',
      bg: '#fef2f2',
      sub: `拒答 ${s.refused_7d ?? 0} 次`
    }
  ]
})

// 列表 + 统计一起加载；互不阻塞，任一失败不影响另一块展示
const loadAll = async () => {
  loading.value = true
  try {
    const [listRes, statsRes] = await Promise.allSettled([getKbListApi(), getKbStatsApi()])
    if (listRes.status === 'fulfilled') {
      kbs.value = Array.isArray(listRes.value) ? listRes.value : []
    }
    if (statsRes.status === 'fulfilled') {
      stats.value = statsRes.value || null
    }
  } catch (e) {
    // 拦截器已提示，静默兜底
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  isEdit.value = false
  editingId.value = null
  form.value = emptyForm()
  formError.value = ''
  formVisible.value = true
}

const openEdit = (kb) => {
  isEdit.value = true
  editingId.value = kb.id
  form.value = {
    code: kb.code,
    name: kb.name || '',
    description: kb.description || '',
    chunk_strategy: kb.chunk_strategy || 'structured',
    visibility: kb.visibility || 'private',
    score_threshold: String(kb.score_threshold ?? 0.3),
    status: kb.status || 'draft'
  }
  formError.value = ''
  formVisible.value = true
}

const validate = () => {
  const code = (form.value.code || '').trim().toLowerCase()
  if (!/^[a-z0-9_]{2,64}$/.test(code)) {
    return '编码只能包含 2 ~ 64 位小写字母、数字或下划线'
  }
  if ((form.value.name || '').trim().length < 2) {
    return '名称至少需要 2 个字符'
  }
  const threshold = Number(form.value.score_threshold)
  if (form.value.score_threshold === '' || Number.isNaN(threshold) || threshold < 0 || threshold > 1) {
    return '召回阈值需在 0 ~ 1 之间'
  }
  return ''
}

const submitForm = async () => {
  if (saving.value) return
  const message = validate()
  if (message) {
    formError.value = message
    return
  }
  formError.value = ''

  const payload = {
    name: form.value.name.trim(),
    description: (form.value.description || '').trim() || null,
    chunk_strategy: form.value.chunk_strategy,
    visibility: form.value.visibility,
    score_threshold: Number(form.value.score_threshold)
  }
  if (isEdit.value) {
    payload.status = form.value.status
  } else {
    payload.code = form.value.code.trim().toLowerCase()
  }

  saving.value = true
  try {
    if (isEdit.value) {
      await updateKbApi(editingId.value, payload)
    } else {
      await createKbApi(payload)
    }
    formVisible.value = false
    showToast({
      type: 'success',
      message: isEdit.value ? '已保存' : '已创建（默认草稿，启用后才可被检索）',
      duration: 2500
    })
    await loadAll()
  } catch (e) {
    // 拦截器已 toast，保留弹窗让用户修改
  } finally {
    saving.value = false
  }
}

const handleDelete = async (kb) => {
  // 取消会抛出 'cancel'，单独吃掉
  try {
    await showConfirmDialog({
      title: '删除知识库',
      message: `确定删除「${kb.name}」？其文档、分段与向量都会被清理，操作不可恢复。`,
      confirmButtonText: '确认删除',
      confirmButtonColor: '#ee0a24'
    })
  } catch (e) {
    return
  }

  try {
    const res = await deleteKbApi(kb.id)
    if (res && res.vector_error) {
      showToast({
        type: 'fail',
        message: `元数据已删除，但向量清理失败：${res.vector_error}`,
        duration: 5000,
        wordBreak: 'break-all'
      })
    } else {
      showToast({type: 'success', message: '已删除'})
    }
    await loadAll()
  } catch (e) {
    // 拦截器已提示
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="kb-page">
    <Navbar/>

    <div class="page-container">
      <!-- 页头 -->
      <div class="page-header">
        <div class="title-block">
          <button class="back-link" @click="router.push('/admin')">
            <ArrowLeft :size="16"/>
            返回工作台
          </button>
          <h2>知识库管理</h2>
          <p>维护知识库与文档，配置完成后到「检索测试台」验证 ACL 与召回效果。</p>
        </div>
        <van-button type="danger" round size="small" icon="plus" @click="openCreate">
          新建知识库
        </van-button>
      </div>

      <!-- 统计卡片 -->
      <div class="stats-grid">
        <div class="stat-card" v-for="item in statCards" :key="item.title">
          <div class="icon-box" :style="{backgroundColor: item.bg, color: item.color}">
            <component :is="item.icon" :size="22"/>
          </div>
          <div class="stat-info">
            <div class="stat-title">{{ item.title }}</div>
            <div class="stat-value">{{ item.value }}</div>
            <div class="stat-sub">{{ item.sub }}</div>
          </div>
        </div>
      </div>

      <!-- 知识库列表 -->
      <div class="panel">
        <div class="panel-header">
          <h3>全部知识库</h3>
          <span class="muted">共 {{ kbs.length }} 个</span>
        </div>

        <div v-if="loading" class="loading-wrap">
          <van-loading size="22">加载中…</van-loading>
        </div>

        <van-empty v-else-if="kbs.length === 0" description="还没有知识库，先新建一个吧"/>

        <div v-else class="table-wrap">
          <table class="kb-table">
            <thead>
            <tr>
              <th>知识库</th>
              <th>状态</th>
              <th>文档</th>
              <th>分段</th>
              <th>可见性</th>
              <th>阈值</th>
              <th class="ops-col">操作</th>
            </tr>
            </thead>
            <tbody>
            <tr v-for="kb in kbs" :key="kb.id">
              <td>
                <div class="kb-name">{{ kb.name }}</div>
                <div class="kb-meta">
                  <code>{{ kb.code }}</code>
                  <span>{{ CHUNK_STRATEGY_TEXT[kb.chunk_strategy] || kb.chunk_strategy }}</span>
                  <span>{{ String(kb.created_at || '').slice(0, 10) }}</span>
                </div>
                <div v-if="kb.description" class="kb-desc">{{ kb.description }}</div>
              </td>
              <td>
                <span class="badge" :style="{color: statusMeta(kb.status).color, backgroundColor: statusMeta(kb.status).bg}">
                  {{ statusMeta(kb.status).text }}
                </span>
              </td>
              <td class="num">{{ kb.document_count }}</td>
              <td class="num">{{ kb.chunk_count }}</td>
              <td>
                <span class="visibility" :class="{public: kb.visibility === 'public'}">
                  {{ visibilityText(kb.visibility) }}
                </span>
              </td>
              <td class="num">{{ Number(kb.score_threshold).toFixed(2) }}</td>
              <td class="ops-col">
                <div class="ops">
                  <button class="op-btn" @click="router.push(`/admin/kb/${kb.id}`)">
                    <Eye :size="14"/>详情
                  </button>
                  <button class="op-btn" @click="openEdit(kb)">
                    <Pencil :size="14"/>编辑
                  </button>
                  <button class="op-btn danger" @click="handleDelete(kb)">
                    <Trash2 :size="14"/>删除
                  </button>
                </div>
              </td>
            </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 零召回榜：直接指导「该补哪篇文档」 -->
      <div v-if="stats && stats.zero_recall && stats.zero_recall.length" class="panel">
        <div class="panel-header">
          <h3>近 7 日零召回问题</h3>
          <span class="muted">累计 {{ stats.zero_recall_7d }} 次</span>
        </div>
        <p class="panel-hint">这些问题一条都没召回，出现次数越多越说明知识库缺内容。</p>
        <div class="table-wrap">
          <table class="zero-table">
            <thead>
            <tr>
              <th class="rank-col">#</th>
              <th>问题</th>
              <th class="count-col">次数</th>
            </tr>
            </thead>
            <tbody>
            <tr v-for="(item, index) in stats.zero_recall" :key="index">
              <td class="rank-col">{{ index + 1 }}</td>
              <td>{{ item.query }}</td>
              <td class="count-col"><span class="count-pill">{{ item.count }}</span></td>
            </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- 新建 / 编辑弹窗 -->
    <van-popup
        v-model:show="formVisible"
        position="center"
        round
        :close-on-click-overlay="false"
        :style="{width: '92%', maxWidth: '540px', maxHeight: '90vh'}"
    >
      <div class="kb-form">
        <div class="form-header">
          <h3>{{ isEdit ? '编辑知识库' : '新建知识库' }}</h3>
          <button class="icon-btn" @click="formVisible = false">
            <X :size="18"/>
          </button>
        </div>

        <div class="form-body">
          <van-field
              v-model="form.code"
              label="编码"
              label-width="84"
              placeholder="如：drug_manual"
              maxlength="64"
              :disabled="isEdit"
              required
          />
          <p class="field-hint">编码会拼进检索表达式，只能用 2 ~ 64 位小写字母、数字、下划线，创建后不可修改。</p>

          <van-field v-model="form.name" label="名称" label-width="84" placeholder="如：药品说明书库" maxlength="128" required/>

          <van-field
              v-model="form.description"
              label="描述"
              label-width="84"
              type="textarea"
              rows="2"
              autosize
              maxlength="500"
              show-word-limit
              placeholder="这个库放什么内容、给谁用（选填）"
          />

          <van-field
              :model-value="strategyLabel"
              label="分段策略"
              label-width="84"
              readonly
              is-link
              @click="strategyPickerShow = true"
          />

          <van-field
              :model-value="visibilityLabel"
              label="可见性"
              label-width="84"
              readonly
              is-link
              @click="visibilityPickerShow = true"
          />
          <p class="field-hint">公开库对访客也可见；私有库必须在「权限矩阵」里逐角色授权。</p>

          <van-field
              v-model="form.score_threshold"
              label="召回阈值"
              label-width="84"
              type="number"
              placeholder="0 ~ 1，默认 0.30"
          />
          <p class="field-hint">低于该分数的召回会被视为不相关，可在检索测试台临时覆盖。</p>

          <van-field v-if="isEdit" label="状态" label-width="84">
            <template #input>
              <van-radio-group v-model="form.status" direction="horizontal" class="radio-group">
                <van-radio name="draft">草稿</van-radio>
                <van-radio name="active">启用</van-radio>
                <van-radio name="archived">归档</van-radio>
              </van-radio-group>
            </template>
          </van-field>
          <p v-if="isEdit" class="field-hint">只有「启用」的库参与检索；归档保留数据但对所有角色下线。</p>

          <p v-if="formError" class="form-error">{{ formError }}</p>
        </div>

        <div class="form-footer">
          <van-button plain round @click="formVisible = false">取消</van-button>
          <van-button type="danger" round :loading="saving" @click="submitForm">
            {{ isEdit ? '保存修改' : '创建' }}
          </van-button>
        </div>
      </div>
    </van-popup>

    <!-- 分段策略 / 可见性下拉 -->
    <van-popup v-model:show="strategyPickerShow" position="bottom" round teleport="body" destroy-on-close>
      <van-picker
          :model-value="strategyPickerValues"
          :columns="STRATEGY_OPTIONS"
          title="选择分段策略"
          @confirm="onStrategyConfirm"
          @cancel="strategyPickerShow = false"
      />
    </van-popup>

    <van-popup v-model:show="visibilityPickerShow" position="bottom" round teleport="body" destroy-on-close>
      <van-picker
          :model-value="visibilityPickerValues"
          :columns="VISIBILITY_OPTIONS"
          title="选择可见性"
          @confirm="onVisibilityConfirm"
          @cancel="visibilityPickerShow = false"
      />
    </van-popup>
  </div>
</template>

<style scoped lang="scss">
.kb-page {
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

  .stats-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 20px;

    .stat-card {
      display: flex;
      align-items: center;
      gap: 14px;
      background: #fff;
      border-radius: 12px;
      padding: 18px;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);

      .icon-box {
        width: 42px;
        height: 42px;
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
      }

      .stat-title {
        font-size: 13px;
        color: #6b7280;
      }

      .stat-value {
        font-size: 22px;
        font-weight: 700;
        color: #111827;
        line-height: 1.3;
      }

      .stat-sub {
        font-size: 12px;
        color: #9ca3af;
      }
    }
  }

  .panel {
    background: #fff;
    border-radius: 12px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    padding: 20px 24px;
    margin-bottom: 20px;

    .panel-header {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 16px;

      h3 {
        font-size: 16px;
        color: #374151;
      }
    }

    .panel-hint {
      font-size: 13px;
      color: #9ca3af;
      margin: -8px 0 14px;
    }

    .muted {
      font-size: 13px;
      color: #9ca3af;
    }

    .loading-wrap {
      padding: 40px 0;
      display: flex;
      justify-content: center;
    }
  }

  .table-wrap {
    overflow-x: auto;
  }

  .kb-table {
    width: 100%;
    border-collapse: collapse;
    min-width: 860px;

    th,
    td {
      text-align: left;
      padding: 12px 10px;
      border-bottom: 1px solid #f3f4f6;
      font-size: 14px;
      color: #374151;
      vertical-align: top;
    }

    th {
      font-weight: 500;
      color: #6b7280;
      font-size: 13px;
      background: #f9fafb;
    }

    tbody tr:hover {
      background: #fafafa;
    }

    .num {
      color: #111827;
      font-variant-numeric: tabular-nums;
    }

    .kb-name {
      font-weight: 600;
      color: #111827;
      margin-bottom: 4px;
    }

    .kb-meta {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      color: #9ca3af;

      code {
        background: #f3f4f6;
        color: #6b7280;
        border-radius: 4px;
        padding: 1px 6px;
        font-size: 12px;
      }
    }

    .kb-desc {
      margin-top: 6px;
      font-size: 12px;
      color: #9ca3af;
      max-width: 420px;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }

    .badge {
      display: inline-block;
      font-size: 12px;
      padding: 2px 8px;
      border-radius: 10px;
      white-space: nowrap;
    }

    .visibility {
      font-size: 13px;
      color: #6b7280;

      &.public {
        color: #10b981;
        font-weight: 600;
      }
    }

    .ops-col {
      width: 210px;
    }

    .ops {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
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

    &:hover {
      border-color: #d1d5db;
      background: #f9fafb;
    }

    &.danger {
      color: #dc2626;
      border-color: #fecaca;

      &:hover {
        background: #fef2f2;
      }
    }
  }

  .zero-table {
    width: 100%;
    border-collapse: collapse;
    min-width: 420px;

    th,
    td {
      text-align: left;
      padding: 10px 12px;
      border-bottom: 1px solid #f3f4f6;
      font-size: 13px;
      color: #374151;
    }

    th {
      background: #f9fafb;
      color: #6b7280;
      font-weight: 500;
    }

    .rank-col {
      width: 48px;
      color: #9ca3af;
    }

    .count-col {
      width: 90px;
    }

    .count-pill {
      display: inline-block;
      min-width: 28px;
      text-align: center;
      padding: 1px 8px;
      border-radius: 10px;
      background: #fef2f2;
      color: #dc2626;
      font-size: 12px;
      font-weight: 600;
    }
  }

  .kb-form {
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

      .icon-btn {
        border: none;
        background: transparent;
        color: #9ca3af;
        cursor: pointer;
        display: flex;
        padding: 4px;

        &:hover {
          color: #4b5563;
        }
      }
    }

    .form-body {
      padding: 8px 12px 0;
      overflow-y: auto;
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

  @media (max-width: 900px) {
    .stats-grid {
      grid-template-columns: repeat(2, 1fr);
    }
  }

  @media (max-width: 768px) {
    .page-container {
      padding: 12px;
    }

    .page-header {
      flex-direction: column;
      align-items: stretch;

      h2 {
        font-size: 19px;
      }
    }

    .stats-grid {
      gap: 10px;

      .stat-card {
        padding: 12px;
        gap: 10px;

        .stat-value {
          font-size: 18px;
        }
      }
    }

    .panel {
      padding: 16px 12px;
    }
  }
}

// van-radio 是子组件，需要 :deep 才能影响内部间距
.radio-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;

  :deep(.van-radio) {
    margin-right: 16px;
    margin-bottom: 4px;
  }
}
</style>
