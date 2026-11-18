<script setup>
import {ref, reactive, computed, onMounted, onUnmounted, watch} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import {showToast, showConfirmDialog} from 'vant'
import {
  ArrowLeft, Upload, Link2, Type, RefreshCw, RotateCcw, Trash2, Eye,
  Layers, Loader2, Database
} from 'lucide-vue-next'
import Navbar from '../../components/Navbar.vue'
import {
  getKbDetailApi,
  getKbDocumentsApi,
  uploadKbDocumentApi,
  reindexKbDocumentApi,
  retryKbDocumentApi,
  deleteKbDocumentApi,
  getKbChunksApi,
  updateKbChunkApi
} from '../../api/kb'

const route = useRoute()
const router = useRouter()

const kbId = computed(() => route.params.id)

// 页面状态
const kb = ref(null)
const kbLoading = ref(true)
const documents = ref([])
const docLoading = ref(true)

// 上传表单（三种方式共用标题 / 生效期）
const uploadMode = ref('file')
const fileList = ref([])
const uploading = ref(false)
const uploadForm = reactive({
  url: '',
  text: '',
  title: '',
  effective_from: '',
  effective_to: ''
})

// 分段弹窗
const chunkPopupVisible = ref(false)
const chunkDoc = ref(null)
const chunks = ref([])
const chunkLoading = ref(false)
const editingChunkId = ref(null)
const savingChunkId = ref(null)
const chunkEditForm = reactive({section: '', content: ''})

const ACTIVE_STATUSES = ['pending', 'parsing', 'chunking', 'embedding']

const UPLOAD_MODES = [
  {value: 'file', label: '文件上传', icon: Upload},
  {value: 'url', label: 'URL 抓取', icon: Link2},
  {value: 'text', label: '粘贴正文', icon: Type}
]

const SOURCE_TEXT = {pdf: 'PDF', docx: 'Word', md: 'Markdown', txt: 'TXT', url: 'URL', manual: '手工录入'}
const CHUNK_STRATEGY_TEXT = {structured: '结构化', recursive: '递归'}
const KB_STATUS = {
  draft: {text: '草稿', color: '#d97706', bg: '#fffbeb'},
  active: {text: '启用', color: '#059669', bg: '#ecfdf5'},
  archived: {text: '归档', color: '#6b7280', bg: '#f3f4f6'}
}
const DOC_STATUS = {
  pending: {text: '排队中', color: '#6b7280', bg: '#f3f4f6'},
  parsing: {text: '解析中', color: '#2563eb', bg: '#eff6ff'},
  chunking: {text: '分段中', color: '#7c3aed', bg: '#f5f3ff'},
  embedding: {text: '向量化', color: '#d97706', bg: '#fffbeb'},
  ready: {text: '已就绪', color: '#059669', bg: '#ecfdf5'},
  failed: {text: '失败', color: '#dc2626', bg: '#fef2f2'}
}

const statusMeta = (status) => KB_STATUS[status] || {text: status || '未知', color: '#6b7280', bg: '#f3f4f6'}
const docStatusMeta = (status) => DOC_STATUS[status] || {text: status || '未知', color: '#6b7280', bg: '#f3f4f6'}
const sourceText = (type) => SOURCE_TEXT[type] || type || '未知'
const visibilityText = (visibility) => (visibility === 'public' ? '公开' : '私有')
const isActiveStatus = (status) => ACTIVE_STATUSES.includes(status)

const activeCount = computed(() => documents.value.filter((doc) => isActiveStatus(doc.status)).length)

// 当前打开分段的文档是否已就绪（就绪才允许编辑正文）
const chunkDocReady = computed(() => {
  if (!chunkDoc.value) return false
  const latest = documents.value.find((doc) => doc.id === chunkDoc.value.id)
  return (latest || chunkDoc.value).status === 'ready'
})

const loadKb = async () => {
  try {
    kb.value = await getKbDetailApi(kbId.value)
  } catch (e) {
    kb.value = null
  } finally {
    kbLoading.value = false
  }
}

const loadDocuments = async (silent = false) => {
  if (!silent) docLoading.value = true
  try {
    const list = await getKbDocumentsApi(kbId.value)
    documents.value = Array.isArray(list) ? list : []
  } catch (e) {
    // 轮询时静默失败，等待下一轮
  } finally {
    if (!silent) docLoading.value = false
  }
}

// ---------------------------------------------------------------- 索引状态轮询
// 只要还有 pending/parsing/chunking/embedding 的文档，就每 2500ms 拉一次列表；
// 全部进入 ready/failed 后自动停表，onUnmounted 再兜底清理一次。
let pollTimer = null
let pollBusy = false

const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const ensurePolling = () => {
  if (activeCount.value === 0) {
    stopPolling()
    return
  }
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    if (pollBusy) return
    pollBusy = true
    try {
      const list = await getKbDocumentsApi(kbId.value)
      documents.value = Array.isArray(list) ? list : []
      if (activeCount.value === 0) {
        stopPolling()
        // 索引结束后刷新库级统计（文档数 / 分段数）
        await loadKb()
      }
    } catch (e) {
      // 单次轮询失败不打断，下一轮继续
    } finally {
      pollBusy = false
    }
  }, 2500)
}

const initPage = async () => {
  kbLoading.value = true
  docLoading.value = true
  try {
    await Promise.all([loadKb(), loadDocuments()])
  } catch (e) {
    // 两个子调用内部已兜底，这里只防意外的未捕获异常
  } finally {
    ensurePolling()
  }
}

// ---------------------------------------------------------------- 上传
const canSubmit = computed(() => {
  if (uploadMode.value === 'file') return fileList.value.length > 0
  if (uploadMode.value === 'url') return uploadForm.url.trim().length > 0
  return uploadForm.text.trim().length > 0
})

const resetUploadForm = () => {
  fileList.value = []
  uploadForm.url = ''
  uploadForm.text = ''
  uploadForm.title = ''
  uploadForm.effective_from = ''
  uploadForm.effective_to = ''
}

const handleUpload = async () => {
  if (uploading.value) return
  if (!canSubmit.value) {
    showToast('请先选择文件或填写内容')
    return
  }
  if (uploadForm.effective_from && uploadForm.effective_to && uploadForm.effective_from > uploadForm.effective_to) {
    showToast('生效结束日期不能早于开始日期')
    return
  }

  const formData = new FormData()
  if (uploadMode.value === 'file') {
    const item = fileList.value[0]
    const rawFile = item && (item.file || item)
    if (!rawFile) {
      showToast('文件读取失败，请重新选择')
      return
    }
    formData.append('file', rawFile)
  } else if (uploadMode.value === 'url') {
    formData.append('url', uploadForm.url.trim())
  } else {
    formData.append('text', uploadForm.text)
  }
  if (uploadForm.title.trim()) formData.append('title', uploadForm.title.trim())
  if (uploadForm.effective_from) formData.append('effective_from', uploadForm.effective_from)
  if (uploadForm.effective_to) formData.append('effective_to', uploadForm.effective_to)

  uploading.value = true
  try {
    const res = await uploadKbDocumentApi(kbId.value, formData)
    showToast({
      type: 'success',
      message: res && res.queued === false ? '已入库，未进入索引队列' : '已提交，正在后台索引',
      duration: 2500
    })
    resetUploadForm()
    await loadDocuments()
    ensurePolling()
    await loadKb()
  } catch (e) {
    // 拦截器已 toast，保留表单内容方便重试
  } finally {
    uploading.value = false
  }
}

// ---------------------------------------------------------------- 文档操作
const refreshAfterAction = async () => {
  await loadDocuments()
  ensurePolling()
  await loadKb()
}

const handleReindex = async (doc) => {
  try {
    await showConfirmDialog({
      title: '重新解析',
      message: `将清空「${doc.title}」的旧向量并全量重建，确定继续？`,
      confirmButtonText: '开始重建'
    })
  } catch (e) {
    return
  }
  try {
    await reindexKbDocumentApi(kbId.value, doc.id)
    showToast({type: 'success', message: '已重新排入索引队列'})
    await refreshAfterAction()
  } catch (e) {
    // 拦截器已提示
  }
}

const handleRetry = async (doc) => {
  try {
    await retryKbDocumentApi(kbId.value, doc.id)
    showToast({type: 'success', message: '已从断点继续索引'})
    await refreshAfterAction()
  } catch (e) {
    // 409（已就绪）等错误由拦截器提示
  }
}

const handleDeleteDoc = async (doc) => {
  try {
    await showConfirmDialog({
      title: '删除文档',
      message: `确定删除「${doc.title}」？其分段与向量会一并清理，操作不可恢复。`,
      confirmButtonText: '确认删除',
      confirmButtonColor: '#ee0a24'
    })
  } catch (e) {
    return
  }
  try {
    const res = await deleteKbDocumentApi(kbId.value, doc.id)
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
    if (chunkDoc.value && chunkDoc.value.id === doc.id) {
      chunkPopupVisible.value = false
    }
    await refreshAfterAction()
  } catch (e) {
    // 拦截器已提示
  }
}

// ---------------------------------------------------------------- 分段
const openChunks = async (doc) => {
  chunkDoc.value = doc
  chunkPopupVisible.value = true
  chunkLoading.value = true
  chunks.value = []
  editingChunkId.value = null
  try {
    const list = await getKbChunksApi(kbId.value, doc.id)
    chunks.value = Array.isArray(list) ? list : []
  } catch (e) {
    // 拦截器已提示
  } finally {
    chunkLoading.value = false
  }
}

const startEditChunk = (chunk) => {
  if (!chunkDocReady.value) {
    showToast('文档索引完成后才能编辑分段')
    return
  }
  editingChunkId.value = chunk.id
  chunkEditForm.section = chunk.section || ''
  chunkEditForm.content = chunk.content || ''
}

const cancelEditChunk = () => {
  editingChunkId.value = null
}

const saveChunk = async (chunk) => {
  if (!chunkEditForm.content.trim()) {
    showToast('分段正文不能为空')
    return
  }
  savingChunkId.value = chunk.id
  try {
    const updated = await updateKbChunkApi(kbId.value, chunk.id, {
      content: chunkEditForm.content,
      // 传空字符串而不是 null：后端用 `is not None` 判断是否更新，null 会被当成「不修改」
      section: chunkEditForm.section.trim()
    })
    const index = chunks.value.findIndex((item) => item.id === chunk.id)
    if (index !== -1 && updated) {
      chunks.value[index] = updated
    }
    editingChunkId.value = null
    showToast({type: 'success', message: '已重建该条向量', duration: 2500})
  } catch (e) {
    // 409：文档未就绪；503：向量库不可用，均由拦截器提示
  } finally {
    savingChunkId.value = null
  }
}

const closeChunks = () => {
  chunkPopupVisible.value = false
  editingChunkId.value = null
  chunkDoc.value = null
  chunks.value = []
}

onMounted(initPage)

onUnmounted(() => {
  stopPolling()
})

// 同一个组件在 /admin/kb/:id 之间切换时复用，需要重置并重新拉取
watch(() => route.params.id, (newId, oldId) => {
  if (!newId || newId === oldId) return
  stopPolling()
  closeChunks()
  kb.value = null
  documents.value = []
  resetUploadForm()
  uploadMode.value = 'file'
  initPage()
})
</script>

<template>
  <div class="kb-detail-page">
    <Navbar/>

    <div class="page-container">
      <button class="back-link" @click="router.push('/admin/kb')">
        <ArrowLeft :size="16"/>
        返回知识库列表
      </button>

      <div v-if="kbLoading" class="loading-wrap">
        <van-loading size="22">加载知识库…</van-loading>
      </div>

      <template v-else-if="kb">
        <!-- 库信息 -->
        <div class="panel kb-head">
          <div class="head-main">
            <div class="title-line">
              <h2>{{ kb.name }}</h2>
              <code class="kb-code">{{ kb.code }}</code>
              <span class="badge" :style="{color: statusMeta(kb.status).color, backgroundColor: statusMeta(kb.status).bg}">
                {{ statusMeta(kb.status).text }}
              </span>
              <span class="badge" :class="{public: kb.visibility === 'public'}">
                {{ visibilityText(kb.visibility) }}
              </span>
            </div>
            <p class="description">{{ kb.description || '暂无描述' }}</p>
            <div class="meta-line">
              <span><Database :size="13"/> {{ kb.embedding_model }} · {{ kb.dim }} 维</span>
              <span><Layers :size="13"/> {{ CHUNK_STRATEGY_TEXT[kb.chunk_strategy] || kb.chunk_strategy }}</span>
              <span>阈值 {{ Number(kb.score_threshold).toFixed(2) }}</span>
              <span>{{ kb.document_count }} 篇文档 / {{ kb.chunk_count }} 个分段</span>
              <span v-if="kb.status !== 'active'" class="warn-tip">未启用，当前不会被检索到</span>
            </div>
          </div>
        </div>

        <!-- 上传 -->
        <div class="panel upload-panel">
          <div class="panel-header">
            <h3>上传文档</h3>
            <span class="muted">支持 PDF / Word / Markdown / TXT，也可抓取 URL 或直接粘贴正文</span>
          </div>

          <div class="mode-tabs">
            <button
                v-for="mode in UPLOAD_MODES"
                :key="mode.value"
                class="mode-tab"
                :class="{active: uploadMode === mode.value}"
                @click="uploadMode = mode.value"
            >
              <component :is="mode.icon" :size="15"/>
              {{ mode.label }}
            </button>
          </div>

          <div class="mode-body">
            <van-uploader
                v-if="uploadMode === 'file'"
                v-model="fileList"
                :max-count="1"
                accept=".pdf,.doc,.docx,.md,.markdown,.txt"
            />
            <van-field
                v-else-if="uploadMode === 'url'"
                v-model="uploadForm.url"
                placeholder="https://example.com/guide.html"
                class="plain-field"
                clearable
            />
            <van-field
                v-else
                v-model="uploadForm.text"
                type="textarea"
                rows="5"
                autosize
                maxlength="20000"
                show-word-limit
                placeholder="直接粘贴正文，提交后会落盘为 txt 并进入索引队列"
                class="plain-field"
            />
          </div>

          <div class="meta-grid">
            <van-field v-model="uploadForm.title" label="标题" placeholder="选填，默认取文件名 / URL / 正文首行"/>
            <van-field label="生效期">
              <template #input>
                <div class="date-range">
                  <input v-model="uploadForm.effective_from" type="date" class="native-date"/>
                  <span class="date-sep">至</span>
                  <input v-model="uploadForm.effective_to" type="date" class="native-date"/>
                </div>
              </template>
            </van-field>
          </div>
          <p class="field-hint">生效期选填：留空表示永久有效；用于让过期资料不参与检索。</p>

          <div class="upload-actions">
            <van-button type="danger" round :loading="uploading" loading-text="提交中…" @click="handleUpload">
              提交并开始索引
            </van-button>
          </div>
        </div>

        <!-- 文档列表 -->
        <div class="panel">
          <div class="panel-header">
            <h3>文档列表</h3>
            <div class="header-right">
              <span v-if="activeCount > 0" class="polling-tip">
                <Loader2 :size="13" class="spin"/>
                {{ activeCount }} 个文档正在索引，每 2.5s 自动刷新
              </span>
              <button class="op-btn" @click="refreshAfterAction">刷新</button>
            </div>
          </div>

          <div v-if="docLoading" class="loading-wrap">
            <van-loading size="22">加载文档…</van-loading>
          </div>

          <van-empty v-else-if="documents.length === 0" description="还没有文档，先上传一份吧"/>

          <div v-else class="table-wrap">
            <table class="doc-table">
              <thead>
              <tr>
                <th>文档</th>
                <th>来源</th>
                <th>状态</th>
                <th>分段</th>
                <th class="ops-col">操作</th>
              </tr>
              </thead>
              <tbody>
              <tr v-for="doc in documents" :key="doc.id">
                <td>
                  <div class="doc-title">{{ doc.title }}</div>
                  <div class="doc-meta">
                    <span>v{{ doc.version }}</span>
                    <span>游标 {{ doc.last_indexed_offset }}</span>
                    <span v-if="doc.effective_from || doc.effective_to">
                      生效 {{ doc.effective_from || '不限' }} ~ {{ doc.effective_to || '不限' }}
                    </span>
                    <a
                        v-if="doc.source_type === 'url' && doc.source_url"
                        :href="doc.source_url"
                        target="_blank"
                        rel="noopener"
                        class="source-link"
                    >原文链接</a>
                  </div>
                  <div v-if="doc.status === 'failed' && doc.error_msg" class="doc-error">
                    {{ doc.error_msg }}
                  </div>
                </td>
                <td><span class="source-badge">{{ sourceText(doc.source_type) }}</span></td>
                <td>
                  <span class="badge" :style="{color: docStatusMeta(doc.status).color, backgroundColor: docStatusMeta(doc.status).bg}">
                    {{ docStatusMeta(doc.status).text }}
                  </span>
                  <div v-if="isActiveStatus(doc.status)" class="indexing-line">
                    <Loader2 :size="12" class="spin"/>处理中
                  </div>
                </td>
                <td class="num">{{ doc.chunk_count }}</td>
                <td class="ops-col">
                  <div class="ops">
                    <button class="op-btn" @click="openChunks(doc)">
                      <Eye :size="14"/>查看分段
                    </button>
                    <button class="op-btn" @click="handleReindex(doc)">
                      <RefreshCw :size="14"/>重新解析
                    </button>
                    <button v-if="doc.status === 'failed'" class="op-btn" @click="handleRetry(doc)">
                      <RotateCcw :size="14"/>失败重试
                    </button>
                    <button class="op-btn danger" @click="handleDeleteDoc(doc)">
                      <Trash2 :size="14"/>删除
                    </button>
                  </div>
                </td>
              </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>

      <van-empty v-else description="知识库不存在或已被删除">
        <van-button round size="small" @click="router.push('/admin/kb')">返回列表</van-button>
      </van-empty>
    </div>

    <!-- 分段抽屉 -->
    <van-popup
        v-model:show="chunkPopupVisible"
        position="bottom"
        round
        closeable
        :style="{height: '85%'}"
    >
      <div class="chunk-popup">
        <div class="chunk-header">
          <div>
            <h3>文档分段</h3>
            <p>{{ chunkDoc ? chunkDoc.title : '' }}</p>
          </div>
          <span class="chunk-count">共 {{ chunks.length }} 段</span>
        </div>

        <div class="chunk-body">
          <div v-if="chunkLoading" class="loading-wrap">
            <van-loading size="22">加载分段…</van-loading>
          </div>

          <van-empty v-else-if="chunks.length === 0" description="该文档还没有分段"/>

          <template v-else>
            <div v-if="!chunkDocReady" class="not-ready-tip">
              文档尚未索引完成，分段可能不完整，暂不支持编辑。
            </div>

            <div v-for="chunk in chunks" :key="chunk.id" class="chunk-card">
              <div class="chunk-card-head">
                <span class="chunk-index">#{{ chunk.chunk_index }}</span>
                <span class="section-tag">{{ chunk.section || '无小节' }}</span>
                <span class="chunk-stat">{{ chunk.token_count ?? '—' }} 字</span>
                <span class="chunk-stat">命中 {{ chunk.hit_count }} 次</span>
                <span v-if="chunk.page !== null && chunk.page !== undefined" class="chunk-stat">第 {{ chunk.page }} 页</span>
                <button
                    v-if="editingChunkId !== chunk.id"
                    class="op-btn"
                    :disabled="!chunkDocReady"
                    @click="startEditChunk(chunk)"
                >
                  编辑正文
                </button>
              </div>

              <div v-if="editingChunkId === chunk.id" class="chunk-edit">
                <van-field v-model="chunkEditForm.section" label="小节" placeholder="选填，如：用法用量" maxlength="128"/>
                <van-field
                    v-model="chunkEditForm.content"
                    label="正文"
                    type="textarea"
                    rows="6"
                    autosize
                    maxlength="20000"
                    show-word-limit
                />
                <p class="edit-hint">保存后只重建这一条向量，命中次数会保留。</p>
                <div class="chunk-edit-actions">
                  <van-button size="small" plain round @click="cancelEditChunk">取消</van-button>
                  <van-button
                      size="small"
                      type="danger"
                      round
                      :loading="savingChunkId === chunk.id"
                      @click="saveChunk(chunk)"
                  >
                    保存并重建向量
                  </van-button>
                </div>
              </div>
              <pre v-else class="chunk-content">{{ chunk.content }}</pre>
            </div>
          </template>
        </div>
      </div>
    </van-popup>
  </div>
</template>

<style scoped lang="scss">
.kb-detail-page {
  min-height: 100vh;
  background: #f3f4f6;
  padding-top: 64px;
  padding-bottom: 32px;

  .page-container {
    max-width: 1200px;
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

  .loading-wrap {
    padding: 48px 0;
    display: flex;
    justify-content: center;
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
      align-items: center;
      gap: 12px;
      margin-bottom: 16px;

      h3 {
        font-size: 16px;
        color: #374151;
      }

      .muted {
        font-size: 12px;
        color: #9ca3af;
      }

      .header-right {
        display: flex;
        align-items: center;
        gap: 12px;
      }

      .polling-tip {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        font-size: 12px;
        color: #d97706;
        background: #fffbeb;
        border-radius: 10px;
        padding: 3px 8px;
      }
    }
  }

  .kb-head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;

    .title-line {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
      margin-bottom: 8px;

      h2 {
        font-size: 22px;
        color: #111827;
      }

      .kb-code {
        background: #f3f4f6;
        color: #6b7280;
        border-radius: 4px;
        padding: 2px 8px;
        font-size: 12px;
      }
    }

    .description {
      font-size: 13px;
      color: #6b7280;
      margin-bottom: 10px;
      max-width: 760px;
      line-height: 1.6;
    }

    .meta-line {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 14px;
      font-size: 12px;
      color: #6b7280;

      span {
        display: inline-flex;
        align-items: center;
        gap: 4px;
      }

      .warn-tip {
        color: #d97706;
        background: #fffbeb;
        border-radius: 10px;
        padding: 2px 8px;
      }
    }

    .badge {
      font-size: 12px;
      padding: 2px 8px;
      border-radius: 10px;
      white-space: nowrap;

      &.public {
        color: #059669;
        background: #ecfdf5;
      }

      &:not(.public) {
        color: #6b7280;
        background: #f3f4f6;
      }
    }
  }

  .mode-tabs {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 12px;

    .mode-tab {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 8px 14px;
      border: 1px solid #e5e7eb;
      background: #fff;
      border-radius: 8px;
      color: #4b5563;
      font-size: 13px;
      cursor: pointer;
      transition: all 0.15s;

      &:hover {
        background: #f9fafb;
      }

      &.active {
        border-color: #fca5a5;
        background: #fef2f2;
        color: #dc2626;
        font-weight: 600;
      }
    }
  }

  .mode-body {
    background: #f9fafb;
    border: 1px dashed #e5e7eb;
    border-radius: 8px;
    padding: 14px;
    margin-bottom: 12px;

    .plain-field {
      background: #fff;
      border-radius: 6px;
      padding: 8px 12px;
    }
  }

  .meta-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 4px 12px;

    .date-range {
      display: flex;
      align-items: center;
      gap: 8px;

      .native-date {
        border: 1px solid #dcdfe6;
        border-radius: 4px;
        padding: 4px 6px;
        font-size: 13px;
        color: #374151;
        background: #fff;
        outline: none;

        &:focus {
          border-color: #ef4444;
        }
      }

      .date-sep {
        color: #9ca3af;
        font-size: 13px;
      }
    }
  }

  .field-hint {
    font-size: 12px;
    color: #9ca3af;
    margin: 2px 0 12px;
    padding-left: 12px;
  }

  .upload-actions {
    display: flex;
    justify-content: flex-end;
  }

  .table-wrap {
    overflow-x: auto;
  }

  .doc-table {
    width: 100%;
    border-collapse: collapse;
    min-width: 880px;

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
      font-size: 13px;
      font-weight: 500;
      color: #6b7280;
      background: #f9fafb;
    }

    tbody tr:hover {
      background: #fafafa;
    }

    .doc-title {
      font-weight: 600;
      color: #111827;
      margin-bottom: 4px;
      word-break: break-all;
    }

    .doc-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      font-size: 12px;
      color: #9ca3af;

      .source-link {
        color: #3b82f6;
        text-decoration: none;

        &:hover {
          text-decoration: underline;
        }
      }
    }

    .doc-error {
      margin-top: 6px;
      font-size: 12px;
      color: #dc2626;
      background: #fef2f2;
      border-radius: 6px;
      padding: 6px 8px;
      line-height: 1.5;
      word-break: break-all;
    }

    .badge {
      display: inline-block;
      font-size: 12px;
      padding: 2px 8px;
      border-radius: 10px;
      white-space: nowrap;
    }

    .source-badge {
      display: inline-block;
      font-size: 12px;
      color: #4b5563;
      background: #f3f4f6;
      border-radius: 4px;
      padding: 2px 8px;
      white-space: nowrap;
    }

    .indexing-line {
      display: flex;
      align-items: center;
      gap: 4px;
      font-size: 11px;
      color: #d97706;
      margin-top: 4px;
    }

    .num {
      font-variant-numeric: tabular-nums;
    }

    .ops-col {
      width: 280px;
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

    &:hover:not(:disabled) {
      border-color: #d1d5db;
      background: #f9fafb;
    }

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    &.danger {
      color: #dc2626;
      border-color: #fecaca;

      &:hover:not(:disabled) {
        background: #fef2f2;
      }
    }
  }

  .chunk-popup {
    display: flex;
    flex-direction: column;
    height: 100%;
    background: #f7f8fa;

    .chunk-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      padding: 16px 48px 16px 20px;
      background: #fff;
      border-bottom: 1px solid #f3f4f6;
      flex-shrink: 0;

      h3 {
        font-size: 16px;
        color: #111827;
        margin-bottom: 4px;
      }

      p {
        font-size: 12px;
        color: #9ca3af;
        word-break: break-all;
      }

      .chunk-count {
        font-size: 12px;
        color: #6b7280;
        background: #f3f4f6;
        border-radius: 10px;
        padding: 2px 8px;
        white-space: nowrap;
      }
    }

    .chunk-body {
      flex: 1;
      overflow-y: auto;
      padding: 16px 20px 28px;
    }

    .not-ready-tip {
      font-size: 13px;
      color: #d97706;
      background: #fffbeb;
      border-radius: 8px;
      padding: 8px 12px;
      margin-bottom: 12px;
    }

    .chunk-card {
      background: #fff;
      border-radius: 10px;
      padding: 14px;
      margin-bottom: 12px;
      box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);

      .chunk-card-head {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 8px;
        margin-bottom: 10px;

        .chunk-index {
          font-size: 12px;
          font-weight: 700;
          color: #ef4444;
          background: #fef2f2;
          border-radius: 10px;
          padding: 2px 8px;
        }

        .section-tag {
          font-size: 12px;
          color: #2563eb;
          background: #eff6ff;
          border-radius: 10px;
          padding: 2px 8px;
        }

        .chunk-stat {
          font-size: 12px;
          color: #9ca3af;
        }
      }

      .chunk-content {
        margin: 0;
        font-size: 13px;
        line-height: 1.7;
        color: #374151;
        white-space: pre-wrap;
        word-break: break-word;
        max-height: 180px;
        overflow-y: auto;
        background: #f9fafb;
        border-radius: 6px;
        padding: 10px 12px;
      }

      .chunk-edit {
        .edit-hint {
          font-size: 12px;
          color: #9ca3af;
          padding: 4px 16px;
        }

        .chunk-edit-actions {
          display: flex;
          justify-content: flex-end;
          gap: 8px;
          padding: 8px 4px 0;
        }
      }
    }
  }

  @media (max-width: 768px) {
    .page-container {
      padding: 12px;
    }

    .panel {
      padding: 16px 12px;

      .panel-header {
        align-items: flex-start;
        flex-direction: column;
        gap: 8px;

        .header-right {
          width: 100%;
          justify-content: space-between;
        }
      }
    }

    .kb-head .title-line h2 {
      font-size: 19px;
    }

    .meta-grid {
      grid-template-columns: 1fr;
    }

    .chunk-popup .chunk-body {
      padding: 12px;
    }
  }
}

.spin {
  animation: kb-spin 1s linear infinite;
}

@keyframes kb-spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
