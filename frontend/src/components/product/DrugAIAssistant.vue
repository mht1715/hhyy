<script setup>
import {ref} from 'vue'
import {Sparkles, Send} from 'lucide-vue-next'
import {showToast} from 'vant'

const props = defineProps({
  productName: {type: String, default: '该药品'}
})

const input = ref('')
const messages = ref([
  {role: 'ai', text: `您好，我是您的专属药师。关于【${props.productName}】的用法、禁忌或适用人群，您可以随时问我。`}
])
const loading = ref(false)

const handleSend = async () => {
  if (!input.value.trim() || loading.value) return

  const userMsg = input.value
  messages.value.push({role: 'user', text: userMsg})
  input.value = ''
  loading.value = true

  // 模拟 AI 响应（后续可接入 LangGraph 接口）
  setTimeout(() => {
    messages.value.push({
      role: 'ai',
      text: `关于您问的“${userMsg}”，根据该药品的说明书，建议您在医生指导下使用。如需了解更详细的禁忌，请查看下方的说明书区域。`
    })
    loading.value = false
  }, 1000)
}
</script>

<template>
  <div class="ai-assistant-card">
    <div class="ai-header">
      <Sparkles :size="18" color="#ef4444"/>
      <span>AI 药师在线咨询</span>
    </div>

    <div class="chat-area">
      <div v-for="(msg, i) in messages" :key="i" :class="['msg', msg.role]">
        {{ msg.text }}
      </div>
      <div v-if="loading" class="msg ai loading">
        AI 药师思考中...
      </div>
    </div>

    <div class="input-area">
      <van-field
          v-model="input"
          placeholder="问点关于这个药的..."
          @keyup.enter="handleSend"
      />
      <van-button type="danger" size="small" icon="guide-o" @click="handleSend" :loading="loading">
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
    margin-bottom: 12px;
  }

  .chat-area {
    max-height: 200px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 12px;
    margin-bottom: 12px;

    .msg {
      padding: 10px 14px;
      border-radius: 8px;
      font-size: 13px;
      line-height: 1.5;
      max-width: 85%;

      &.ai {
        background: #fef2f2;
        color: #374151;
        align-self: flex-start;
        border-top-left-radius: 0;
      }

      &.user {
        background: #ef4444;
        color: white;
        align-self: flex-end;
        border-top-right-radius: 0;
      }

      &.loading {
        color: #9ca3af;
        font-style: italic;
      }
    }
  }

  .input-area {
    display: flex;
    gap: 8px;
    align-items: center;
    background: #f9fafb;
    padding: 8px;
    border-radius: 8px;
    border: 1px solid #e5e7eb;

    :deep(.van-field) {
      background: transparent;
      padding: 0;
    }
  }
}
</style>