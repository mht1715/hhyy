<script setup>
import {ref, onMounted, nextTick, watch} from 'vue'
import {Sparkles, Send} from 'lucide-vue-next'
import {showToast} from 'vant'
import {marked} from 'marked'
import {drugConsultApi} from '../../api/agentChat'

const props = defineProps({
  productId: {type: String, required: true},
  productName: {type: String, default: '该药品'}
})

const quickQuestions = [
  '这个药怎么吃？',
  '孕妇可以用吗？',
  '有什么副作用？',
  '和其他药能一起吃吗？'
]

const input = ref('')
const messages = ref([
  {role: 'ai', text: `您好，我是您的专属AI药师。关于【${props.productName}】的用法、禁忌或适用人群，您可以随时问我。`}
])
const loading = ref(false)
const sessionId = ref('')
const chatAreaRef = ref(null)

onMounted(() => {
  sessionId.value = crypto.randomUUID ? crypto.randomUUID() : Date.now().toString()
})

const renderMarkdown = (text) => {
  return marked.parse(text)
}

watch(messages, () => {
  nextTick(() => {
    if (chatAreaRef.value) {
      chatAreaRef.value.scrollTop = chatAreaRef.value.scrollHeight
    }
  })
}, {deep: true})

// 【修复核心逻辑】
const sendMessage = async (quickText) => {
  // 判断是快捷提问（传了字符串）还是手动输入（没传参）
  const userText = typeof quickText === 'string' ? quickText : input.value;

  // 安全校验，防止 undefined
  if (!userText || !userText.trim() || loading.value) return

  messages.value.push({role: 'user', text: userText})

  // 如果是手动输入（没有传 quickText），才清空输入框
  if (typeof quickText !== 'string') {
    input.value = ''
  }

  loading.value = true

  try {
    const res = await drugConsultApi(props.productId, userText, sessionId.value)
    messages.value.push({role: 'ai', text: res.reply})
  } catch (e) {
    messages.value.push({role: 'ai', text: '抱歉，药师现在有点忙，请稍后再试。'})
  } finally {
    loading.value = false
  }
}

const handleSendClick = () => sendMessage()
</script>

<template>
  <div class="ai-assistant-card">
    <div class="ai-header">
      <Sparkles :size="18" color="#ef4444"/>
      <span>AI 药师在线咨询</span>
    </div>

    <!-- 聊天记录区 -->
    <div class="chat-area" ref="chatAreaRef">
      <div v-for="(msg, i) in messages" :key="i" :class="['msg-wrap', msg.role]">
        <div class="avatar" v-if="msg.role === 'ai'">
          <Sparkles :size="14" color="#fff"/>
        </div>
        <div class="msg-bubble">
          <!-- 使用 v-html 渲染 Markdown 结果 -->
          <div class="markdown-body" v-html="renderMarkdown(msg.text)"></div>
        </div>
      </div>
      <div v-if="loading" class="msg-wrap ai">
        <div class="avatar">
          <Sparkles :size="14" color="#fff"/>
        </div>
        <div class="msg-bubble loading-bubble">
          <van-loading type="dots" size="20px" color="#ef4444"/>
          <span>正在查阅说明书...</span>
        </div>
      </div>
    </div>

    <!-- 快捷提问区 -->
    <div class="quick-questions">
      <van-tag
          v-for="(q, index) in quickQuestions"
          :key="index"
          plain
          type="danger"
          size="medium"
          class="q-tag"
          @click="sendMessage(q)"
      >
        {{ q }}
      </van-tag>
    </div>

    <!-- 输入区 -->
    <div class="input-area">
      <van-field
          v-model="input"
          placeholder="输入您想咨询的问题..."
          @keyup.enter="handleSendClick"
          :disabled="loading"
          class="chat-input"
      />
      <van-button
          type="danger"
          class="send-btn"
          :loading="loading"
          @click="handleSendClick"
      >
        <template #icon>
          <Send :size="16"/>
        </template>
        发送
      </van-button>
    </div>
  </div>
</template>

<style scoped lang="scss">
.ai-assistant-card {
  background: #fff;
  margin: 12px 0;
  padding: 16px;
  border-top: 1px solid #f3f4f6;
  border-bottom: 1px solid #f3f4f6;

  .ai-header {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 600;
    color: #b91c1c;
    margin-bottom: 16px;
  }

  .chat-area {
    max-height: 300px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 16px;
    margin-bottom: 16px;
    padding-right: 4px;

    .msg-wrap {
      display: flex;
      align-items: flex-start;
      gap: 8px;
      max-width: 90%;

      &.user {
        align-self: flex-end;
        flex-direction: row-reverse;

        .msg-bubble {
          background: #ef4444;
          color: white;
          border-radius: 12px 0 12px 12px;
        }
      }

      &.ai {
        align-self: flex-start;

        .msg-bubble {
          background: #f9fafb;
          color: #374151;
          border-radius: 0 12px 12px 12px;
        }
      }

      .avatar {
        width: 24px;
        height: 24px;
        background: #ef4444;
        border-radius: 50%;
        display: flex;
        justify-content: center;
        align-items: center;
        flex-shrink: 0;
        margin-top: 4px;
      }

      .msg-bubble {
        padding: 10px 14px;
        font-size: 14px;
        line-height: 1.6;
        word-break: break-all;
      }
    }

    .loading-bubble {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      color: #9ca3af;
    }
  }

  /* 深度定制 Markdown 渲染后的样式 */
  :deep(.markdown-body) {
    p {
      margin-bottom: 8px;

      &:last-child {
        margin-bottom: 0;
      }
    }

    strong {
      font-weight: bold;
      color: #b91c1c;
    }

    ul, ol {
      padding-left: 20px;
      margin-bottom: 8px;
    }

    li {
      margin-bottom: 4px;
    }

    br {
      display: block;
      content: "";
      margin-top: 4px;
    }
  }

  .quick-questions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 12px;

    .q-tag {
      cursor: pointer;
      transition: all 0.2s;
      padding: 6px 12px;
      border-radius: 16px;
      background: #fef2f2;

      &:hover {
        background: #fee2e2;
        transform: translateY(-1px);
      }
    }
  }

  .input-area {
    display: flex;
    gap: 8px;
    align-items: center;
    background: #f9fafb;
    padding: 6px 12px;
    border-radius: 8px;
    border: 1px solid #e5e7eb;

    :deep(.chat-input) {
      background: transparent;
      padding: 4px 0;
      flex: 1;
    }

    .send-btn {
      flex-shrink: 0; /* 核心修复：防止按钮被挤压导致文字换行 */
      height: 32px;
      padding: 0 16px;
      border-radius: 6px;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 4px; /* 图标与文字间距 */
    }
  }
}
</style>