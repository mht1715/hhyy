<script setup>
/**
 * 我的记忆（契约 §3 / §7.2，路由 /me/memory，需登录）。
 *
 * 只做前端该做的三件事：看、删、关。所有读写都由后端按 token 里的 user_id 过滤。
 * 接口挂掉时走 toast + 空态 / 错误态，绝不白屏。
 */
import {computed, onMounted, ref} from 'vue'
import {useRouter} from 'vue-router'
import {Brain, RefreshCw, ShieldOff, Trash2} from 'lucide-vue-next'
import dayjs from 'dayjs'
import {showConfirmDialog, showToast} from 'vant'
import Navbar from '../components/Navbar.vue'
import {clearMemory, deleteMemory, fetchMemory, setMemoryEnabled} from '../api/memory'

const router = useRouter()

const TYPE_META = {
  fact: {label: '事实', desc: '基本情况、病史、过敏史'},
  preference: {label: '偏好', desc: '剂型、口味、沟通方式'},
  episode: {label: '情节', desc: '某次对话里发生过的事'},
  risk: {label: '禁忌', desc: '需要长期注意的风险'},
  other: {label: '其他', desc: '暂未归类的记忆'}
}
const TYPE_ORDER = ['fact', 'preference', 'episode', 'risk', 'other']

const loading = ref(false)
const error = ref('')
const enabled = ref(true)
const profile = ref(null)
const items = ref([])
const stats = ref({total: 0, byType: {}})
const switching = ref(false)
const deletingId = ref('')
const clearing = ref(false)

const normalizeType = (type) => (TYPE_ORDER.includes(type) ? type : 'other')

const normalizeStats = (raw) => {
  const byType = {}
  TYPE_ORDER.forEach((type) => {
    const value = raw && raw.by_type ? raw.by_type[type] : 0
    byType[type] = Number.isFinite(Number(value)) ? Number(value) : 0
  })
  const total = raw && Number.isFinite(Number(raw.total))
    ? Number(raw.total)
    : Object.values(byType).reduce((sum, value) => sum + value, 0)
  return {total, byType}
}

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const data = await fetchMemory()
    enabled.value = !data || data.enabled !== false
    profile.value = (data && data.profile) || null
    items.value = Array.isArray(data && data.items) ? data.items : []
    stats.value = normalizeStats(data && data.stats)
  } catch (e) {
    if (e && e.status === 401) {
      error.value = '登录已过期，请重新登录后查看记忆'
    } else {
      error.value = (e && e.message) || '记忆加载失败，请稍后重试'
    }
  } finally {
    loading.value = false
  }
}

const groups = computed(() => (
  TYPE_ORDER
    .map((type) => ({
      type,
      label: TYPE_META[type].label,
      desc: TYPE_META[type].desc,
      count: (items.value || []).filter((item) => normalizeType(item.type) === type).length,
      items: (items.value || []).filter((item) => normalizeType(item.type) === type)
    }))
    .filter((group) => group.items.length > 0)
))

const total = computed(() => stats.value.total)

const statChips = computed(() => (
  TYPE_ORDER
    .filter((type) => type !== 'other')
    .map((type) => ({
      type,
      label: TYPE_META[type].label,
      count: Number(stats.value.byType[type]) || 0
    }))
))

const profileSummary = computed(() => (
  profile.value && profile.value.summary ? String(profile.value.summary) : ''
))

const formatTime = (value) => {
  if (!value) return ''
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('YYYY-MM-DD HH:mm') : String(value)
}

const sourceText = (item) => {
  if (item.source_message_id) return '来自对话消息'
  if (item.source_conversation_id) return '来自会话记录'
  return '来源未知'
}

const handleToggle = async (value) => {
  if (switching.value) return
  const next = !!value
  switching.value = true
  try {
    const data = await setMemoryEnabled(next)
    enabled.value = data && typeof data.enabled === 'boolean' ? data.enabled : next
    showToast(enabled.value ? '已开启记忆' : '已关闭记忆')
  } catch (e) {
    // 受控开关：失败时保持原值，不回显错误状态
    showToast({type: 'fail', message: (e && e.message) || '设置失败，请稍后重试'})
  } finally {
    switching.value = false
  }
}

const handleDelete = async (item) => {
  try {
    await showConfirmDialog({
      title: '删除这条记忆？',
      message: item.content || '删除后 AI 不会再记得这条信息。',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      confirmButtonColor: '#ef4444'
    })
  } catch (e) {
    return
  }

  deletingId.value = item.id
  try {
    const data = await deleteMemory(item.id)
    // 契约：别人的 id 一律 deleted:false（不区分不存在 / 不是你的）
    if (data && data.deleted === false) {
      showToast('这条记忆不存在或已被删除')
      return
    }
    items.value = items.value.filter((row) => row.id !== item.id)
    const type = normalizeType(item.type)
    stats.value = {
      total: Math.max(0, stats.value.total - 1),
      byType: {
        ...stats.value.byType,
        [type]: Math.max(0, (Number(stats.value.byType[type]) || 0) - 1)
      }
    }
    showToast('已删除')
  } catch (e) {
    showToast({type: 'fail', message: (e && e.message) || '删除失败，请稍后重试'})
  } finally {
    deletingId.value = ''
  }
}

const handleClear = async () => {
  if (total.value <= 0) {
    showToast('暂无记忆可清空')
    return
  }
  try {
    await showConfirmDialog({
      title: '清空全部记忆？',
      message: `将删除全部 ${total.value} 条记忆，AI 之后不会再记得这些信息，且不可恢复。`,
      confirmButtonText: '清空',
      cancelButtonText: '取消',
      confirmButtonColor: '#ef4444'
    })
  } catch (e) {
    return
  }

  clearing.value = true
  try {
    const data = await clearMemory()
    items.value = []
    profile.value = null
    stats.value = {total: 0, byType: {}}
    showToast(`已清空 ${Number(data && data.deleted) || 0} 条记忆`)
  } catch (e) {
    showToast({type: 'fail', message: (e && e.message) || '清空失败，请稍后重试'})
  } finally {
    clearing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="memory-page">
    <Navbar/>

    <main class="memory-body">
      <header class="page-head">
        <div class="head-text">
          <div class="head-title">
            <span class="head-icon">
              <Brain :size="17" color="#fff"/>
            </span>
            <h1>我的记忆</h1>
          </div>
          <p class="head-desc">AI 从对话中记住的关于你的信息，只用于让回答更贴合你的情况。</p>
        </div>

        <div class="head-actions">
          <button
              type="button"
              class="ghost-btn"
              :disabled="clearing || total === 0"
              @click="handleClear"
          >
            <Trash2 :size="14"/>
            <span>{{ clearing ? '清空中…' : '一键清空' }}</span>
          </button>
        </div>
      </header>

      <section class="switch-card">
        <div class="switch-text">
          <strong>允许 AI 记录我的信息</strong>
          <span>关闭后不再写入新记忆，也不再注入对话；已有条目仍可删除。</span>
        </div>
        <van-switch
            :model-value="enabled"
            :loading="switching"
            size="24px"
            active-color="#ef4444"
            @update:model-value="handleToggle"
        />
      </section>

      <div v-if="!enabled" class="banner">
        <ShieldOff :size="15"/>
        <span>已关闭记忆，AI 不再记录你的信息</span>
      </div>

      <section v-if="profileSummary" class="profile-card">
        <span class="profile-label">AI 对你的印象</span>
        <p class="profile-text">{{ profileSummary }}</p>
      </section>

      <section v-if="!loading && !error" class="stats-row">
        <div class="stat-total">
          <strong>{{ total }}</strong>
          <span>条记忆</span>
        </div>
        <div class="stat-chips">
          <span
              v-for="chip in statChips"
              :key="chip.type"
              class="stat-chip"
              :class="`type-${chip.type}`"
          >
            {{ chip.label }} {{ chip.count }}
          </span>
        </div>
      </section>

      <section v-if="loading" class="state-box">
        <span class="state-text">正在加载记忆…</span>
      </section>

      <section v-else-if="error" class="state-box is-error">
        <p class="state-text">{{ error }}</p>
        <button type="button" class="ghost-btn" @click="load">
          <RefreshCw :size="13"/>
          <span>重试</span>
        </button>
      </section>

      <section v-else-if="items.length === 0" class="state-box is-empty">
        <div class="empty-avatar">
          <Brain :size="22" color="#ef4444"/>
        </div>
        <p class="state-text">还没有记住任何信息</p>
        <p class="state-hint">和 AI 聊几句，它会自动记住对你有用的内容</p>
        <button type="button" class="primary-btn" @click="router.push('/agents')">去 Agent 广场</button>
      </section>

      <template v-else>
        <section v-for="group in groups" :key="group.type" class="memory-group">
          <div class="group-head">
            <span class="group-label">{{ group.label }}</span>
            <span class="group-count">{{ group.count }}</span>
            <span class="group-desc">{{ group.desc }}</span>
          </div>

          <ul class="memory-list">
            <li v-for="item in group.items" :key="item.id" class="memory-item">
              <div class="item-main">
                <p class="item-content">{{ item.content }}</p>
                <div class="item-meta">
                  <span class="meta-time">{{ formatTime(item.created_at) }}</span>
                  <span class="meta-source" :title="item.source_message_id || ''">
                    {{ sourceText(item) }}
                  </span>
                  <span v-if="item.sensitive" class="meta-sensitive">敏感</span>
                </div>
              </div>

              <button
                  type="button"
                  class="delete-btn"
                  :disabled="deletingId === item.id"
                  title="删除这条记忆"
                  @click="handleDelete(item)"
              >
                <Trash2 :size="14"/>
              </button>
            </li>
          </ul>
        </section>
      </template>
    </main>
  </div>
</template>

<style scoped lang="scss">
.memory-page {
  min-height: 100vh;
  background: #f3f4f6;
  padding-top: 64px;

  .memory-body {
    width: 100%;
    max-width: 720px;
    margin: 0 auto;
    padding: 16px 16px 40px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .page-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;

    .head-title {
      display: flex;
      align-items: center;
      gap: 8px;

      h1 {
        font-size: 17px;
        font-weight: 600;
        color: #111827;
        line-height: 1.4;
      }
    }

    .head-icon {
      width: 30px;
      height: 30px;
      flex-shrink: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 9px;
      background: linear-gradient(135deg, #ef4444, #b91c1c);
    }

    .head-desc {
      margin-top: 4px;
      font-size: 12px;
      line-height: 1.6;
      color: #6b7280;
    }

    .head-actions {
      flex-shrink: 0;
    }
  }

  .switch-card,
  .profile-card {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 12px 14px;
    background: #fff;
    border: 1px solid #f3f4f6;
    border-radius: 12px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
  }

  .switch-card {
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
  }

  .profile-card {
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;

    .profile-label {
      font-size: 11px;
      color: #9ca3af;
    }

    .profile-text {
      font-size: 13px;
      line-height: 1.7;
      color: #374151;
    }
  }

  .banner {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 12px;
    border-radius: 10px;
    background: #fffbeb;
    border: 1px solid #fde68a;
    color: #92400e;
    font-size: 12px;
    line-height: 1.5;
  }

  .stats-row {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    padding: 0 2px;

    .stat-total {
      display: inline-flex;
      align-items: baseline;
      gap: 4px;

      strong {
        font-size: 20px;
        font-weight: 700;
        color: #b91c1c;
        line-height: 1.2;
      }

      span {
        font-size: 11.5px;
        color: #9ca3af;
      }
    }

    .stat-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    .stat-chip {
      padding: 0 8px;
      border-radius: 8px;
      font-size: 11px;
      line-height: 20px;
      background: #f3f4f6;
      color: #6b7280;

      &.type-fact {
        background: #eff6ff;
        color: #2563eb;
      }

      &.type-preference {
        background: #ecfdf5;
        color: #047857;
      }

      &.type-episode {
        background: #f5f3ff;
        color: #6d28d9;
      }

      &.type-risk {
        background: #fef2f2;
        color: #b91c1c;
      }
    }
  }

  .memory-group {
    background: #fff;
    border: 1px solid #f3f4f6;
    border-radius: 12px;
    overflow: hidden;

    .group-head {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 14px;
      background: #fcfcfd;
      border-bottom: 1px solid #f3f4f6;

      .group-label {
        font-size: 13px;
        font-weight: 600;
        color: #111827;
      }

      .group-count {
        min-width: 18px;
        padding: 0 5px;
        border-radius: 9px;
        background: #fef2f2;
        color: #ef4444;
        font-size: 11px;
        line-height: 18px;
        text-align: center;
      }

      .group-desc {
        flex: 1;
        min-width: 0;
        font-size: 11px;
        color: #9ca3af;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
    }

    .memory-list {
      list-style: none;
      padding: 0;
      margin: 0;
    }

    .memory-item {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 12px 14px;
      border-bottom: 1px solid #f9fafb;

      &:last-child {
        border-bottom: none;
      }

      .item-main {
        flex: 1;
        min-width: 0;
      }

      .item-content {
        font-size: 13.5px;
        line-height: 1.65;
        color: #374151;
        word-break: break-word;
      }

      .item-meta {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 8px;
        margin-top: 5px;
        font-size: 11px;
        color: #9ca3af;

        .meta-sensitive {
          padding: 0 6px;
          border-radius: 6px;
          background: #fef2f2;
          border: 1px solid #fecaca;
          color: #b91c1c;
          line-height: 16px;
        }
      }

      .delete-btn {
        flex-shrink: 0;
        width: 28px;
        height: 28px;
        display: flex;
        align-items: center;
        justify-content: center;
        border: none;
        border-radius: 8px;
        background: #f9fafb;
        color: #9ca3af;
        cursor: pointer;
        transition: background-color 0.15s ease, color 0.15s ease;

        &:hover:not(:disabled) {
          background: #fef2f2;
          color: #ef4444;
        }

        &:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
      }
    }
  }

  .state-box {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 40px 16px;
    background: #fff;
    border: 1px solid #f3f4f6;
    border-radius: 12px;
    text-align: center;

    .state-text {
      font-size: 13px;
      line-height: 1.7;
      color: #6b7280;
    }

    .state-hint {
      font-size: 11.5px;
      color: #9ca3af;
    }

    .empty-avatar {
      width: 48px;
      height: 48px;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 14px;
      background: #fff7f7;
      border: 1px solid #fecaca;
      margin-bottom: 2px;
    }

    &.is-error {
      background: #fef2f2;
      border-color: #fecaca;

      .state-text {
        color: #b91c1c;
      }
    }
  }

  .primary-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    height: 30px;
    padding: 0 14px;
    border: none;
    border-radius: 8px;
    background: linear-gradient(135deg, #ef4444, #b91c1c);
    color: #fff;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
  }

  .ghost-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    height: 30px;
    padding: 0 12px;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    background: #fff;
    color: #6b7280;
    font-size: 12px;
    white-space: nowrap;
    cursor: pointer;

    &:hover:not(:disabled) {
      border-color: #fecaca;
      color: #b91c1c;
    }

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }

  @media (max-width: 480px) {
    .memory-body {
      padding: 12px 12px 32px;
    }

    .page-head {
      flex-direction: column;
      align-items: stretch;
      gap: 8px;

      .head-actions {
        align-self: flex-end;
      }
    }

    .stats-row {
      .stat-total strong {
        font-size: 18px;
      }
    }
  }
}
</style>
