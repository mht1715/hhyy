<script setup>
/**
 * 我的会话（M3 低成本改造）：
 * 用 GET /api/conversations 列出自己的会话，点开就地展开历史消息（只读），
 * 并给出「继续对话」入口回到对应 Agent 页。写操作（删除/改名）不在 M3 范围内。
 */
import {onMounted, ref} from 'vue'
import {useRouter} from 'vue-router'
import {ArrowRight, ChevronDown, MessageSquare, RefreshCw} from 'lucide-vue-next'
import dayjs from 'dayjs'
import Navbar from '../components/Navbar.vue'
import {fetchConversation, fetchConversations} from '../api/support'

const router = useRouter()

const conversations = ref([])
const loading = ref(false)
const error = ref('')

const activeId = ref('')
const detail = ref(null)
const detailLoading = ref(false)
const detailError = ref('')

const STATUS_LABELS = {
  bot_active: '进行中',
  handoff_pending: '等待转接',
  human_active: '人工接待',
  closed: '已结束'
}

const TICKET_STATUS_LABELS = {
  queued: '排队中',
  assigned: '已接管',
  resolved: '已结束',
  offline: '已留言'
}

const statusText = (status) => STATUS_LABELS[status] || status || '未知状态'
const ticketStatusText = (status) => TICKET_STATUS_LABELS[status] || status || ''

const formatTime = (value) => {
  if (!value) return ''
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('YYYY-MM-DD HH:mm') : ''
}

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const data = await fetchConversations()
    conversations.value = Array.isArray(data) ? data : []
  } catch (e) {
    if (e && e.status === 401) {
      error.value = '登录已过期，请重新登录'
    } else {
      error.value = (e && e.message) || '会话列表加载失败'
    }
  } finally {
    loading.value = false
  }
}

const loadDetail = async (conversation) => {
  if (!conversation) return
  detailLoading.value = true
  detailError.value = ''
  detail.value = null
  try {
    const data = await fetchConversation(conversation.id)
    detail.value = data
      ? {...data, messages: Array.isArray(data.messages) ? data.messages : []}
      : null
  } catch (e) {
    detailError.value = (e && e.message) || '会话详情加载失败'
  } finally {
    detailLoading.value = false
  }
}

const toggle = async (conversation) => {
  if (activeId.value === conversation.id) {
    activeId.value = ''
    detail.value = null
    detailError.value = ''
    return
  }
  activeId.value = conversation.id
  await loadDetail(conversation)
}

const continueChat = (conversation) => {
  const code = conversation.agent_code || 'drug_consult'
  // 带上 ?c=<会话 id>：Agent 页会据此把这段对话（含人工客服的消息）接回来
  router.push(`/agents/${code}?c=${encodeURIComponent(conversation.id)}`)
}

const roleLabel = (message) => {
  if (!message) return ''
  if (message.role === 'user') return '我'
  if (message.role === 'human_agent') return message.actor_name || '客服'
  if (message.role === 'system') return '系统'
  return 'AI 助手'
}

const roleClass = (message) => {
  const value = message && message.role
  return ['user', 'assistant', 'human_agent', 'system'].includes(value) ? `role-${value}` : 'role-assistant'
}

onMounted(load)
</script>

<template>
  <div class="service-page">
    <Navbar/>

    <main class="service-body">
      <header class="page-head">
        <div class="head-text">
          <div class="head-title">
            <span class="head-icon">
              <MessageSquare :size="16" color="#fff"/>
            </span>
            <h1>我的会话</h1>
          </div>
          <p class="head-desc">和 AI / 人工客服聊过的会话都在这里，点开可以看历史消息。</p>
        </div>

        <button type="button" class="ghost-btn" :disabled="loading" @click="load">
          <RefreshCw :size="13"/>
          <span>刷新</span>
        </button>
      </header>

      <section v-if="loading" class="state-box">正在加载会话…</section>

      <section v-else-if="error" class="state-box is-error">
        <p>{{ error }}</p>
        <button type="button" class="ghost-btn" @click="load">重试</button>
      </section>

      <section v-else-if="conversations.length === 0" class="state-box">
        <span class="empty-icon">
          <MessageSquare :size="20" color="#ef4444"/>
        </span>
        <p>还没有会话记录</p>
        <p class="state-hint">去 Agent 广场问点什么吧</p>
        <button type="button" class="primary-btn" @click="router.push('/agents')">去 Agent 广场</button>
      </section>

      <ul v-else class="conversation-list">
        <li
            v-for="conversation in conversations"
            :key="conversation.id"
            class="conversation-card"
            :class="{ active: conversation.id === activeId }"
        >
          <div class="card-main" @click="toggle(conversation)">
            <div class="card-top">
              <span class="card-title">{{ conversation.title || '未命名会话' }}</span>
              <span class="status-chip" :class="`status-${conversation.status}`">
                {{ statusText(conversation.status) }}
              </span>
              <ChevronDown
                  :size="15"
                  class="expand-icon"
                  :class="{ 'is-open': conversation.id === activeId }"
              />
            </div>

            <div class="card-meta">
              <span class="meta-item">{{ conversation.agent_code || 'drug_consult' }}</span>
              <span v-if="conversation.ticket" class="meta-item is-ticket">
                工单 {{ conversation.ticket.ticket_id }} · {{ ticketStatusText(conversation.ticket.status) }}
              </span>
              <span class="meta-item is-time">{{ formatTime(conversation.updated_at) }}</span>
            </div>
          </div>

          <div v-if="conversation.id === activeId" class="card-detail">
            <div v-if="detailLoading" class="detail-state">正在加载历史消息…</div>
            <div v-else-if="detailError" class="detail-state is-error">
              <p>{{ detailError }}</p>
              <button type="button" class="ghost-btn" @click="loadDetail(conversation)">重试</button>
            </div>
            <template v-else-if="detail">
              <div v-if="detail.messages.length === 0" class="detail-state">暂无消息</div>
              <div
                  v-for="message in detail.messages"
                  :key="message.id"
                  class="mini-message"
                  :class="roleClass(message)"
              >
                <span class="mini-role">{{ roleLabel(message) }}</span>
                <span class="mini-content">{{ message.content }}</span>
              </div>

              <div class="detail-actions">
                <button type="button" class="ghost-btn" @click="continueChat(conversation)">
                  继续对话
                  <ArrowRight :size="13"/>
                </button>
              </div>
            </template>
          </div>
        </li>
      </ul>
    </main>
  </div>
</template>

<style scoped lang="scss">
.service-page {
  min-height: 100vh;
  background: #f3f4f6;
  padding-top: 64px;

  .service-body {
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
  }

  .conversation-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .conversation-card {
    background: #fff;
    border: 1px solid #f3f4f6;
    border-radius: 12px;
    overflow: hidden;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;

    &.active {
      border-color: #fecaca;
      box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.06);
    }

    .card-main {
      padding: 12px 14px;
      cursor: pointer;

      &:hover {
        background: #fff7f7;
      }
    }

    .card-top {
      display: flex;
      align-items: center;
      gap: 8px;

      .card-title {
        flex: 1;
        min-width: 0;
        font-size: 14px;
        font-weight: 600;
        color: #111827;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .expand-icon {
        flex-shrink: 0;
        color: #9ca3af;
        transition: transform 0.2s;

        &.is-open {
          transform: rotate(180deg);
        }
      }
    }

    .card-meta {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      margin-top: 6px;
      font-size: 11px;
      color: #9ca3af;

      .meta-item.is-ticket {
        padding: 0 6px;
        border-radius: 6px;
        background: #fef2f2;
        color: #b91c1c;
      }
    }

    .card-detail {
      padding: 10px 14px 12px;
      border-top: 1px solid #f3f4f6;
      background: #fcfcfd;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .detail-state {
      font-size: 12px;
      color: #9ca3af;
      padding: 8px 0;

      &.is-error {
        color: #b91c1c;
      }
    }

    .mini-message {
      display: flex;
      gap: 8px;
      font-size: 12.5px;
      line-height: 1.7;

      .mini-role {
        flex-shrink: 0;
        width: 48px;
        color: #9ca3af;
        font-size: 11px;
        line-height: 1.9;
      }

      .mini-content {
        flex: 1;
        min-width: 0;
        color: #374151;
        word-break: break-word;
        white-space: pre-wrap;
      }

      &.role-user .mini-content {
        color: #111827;
        font-weight: 500;
      }

      &.role-human_agent .mini-content {
        color: #1e3a8a;
      }
    }

    .detail-actions {
      display: flex;
      justify-content: flex-end;
      padding-top: 4px;
    }
  }

  .status-chip {
    flex-shrink: 0;
    padding: 0 6px;
    border-radius: 6px;
    background: #f3f4f6;
    color: #6b7280;
    font-size: 10.5px;
    line-height: 17px;
    white-space: nowrap;

    &.status-bot_active {
      background: #eff6ff;
      color: #2563eb;
    }

    &.status-handoff_pending {
      background: #fff7ed;
      color: #c2410c;
    }

    &.status-human_active {
      background: #ecfdf5;
      color: #047857;
    }

    &.status-closed {
      background: #f3f4f6;
      color: #6b7280;
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
    font-size: 13px;
    line-height: 1.7;
    color: #6b7280;

    .state-hint {
      font-size: 11.5px;
      color: #9ca3af;
    }

    .empty-icon {
      width: 46px;
      height: 46px;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 14px;
      background: #fff7f7;
      border: 1px solid #fecaca;
    }

    &.is-error {
      background: #fef2f2;
      border-color: #fecaca;
      color: #b91c1c;
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
    flex-shrink: 0;
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
    white-space: nowrap;
    cursor: pointer;

    &:hover:not(:disabled) {
      border-color: #fecaca;
      color: #b91c1c;
    }

    &:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }
  }

  @media (max-width: 480px) {
    .service-body {
      padding: 12px 12px 32px;
    }
  }
}
</style>
