<script setup>
import {computed} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import {ArrowLeft} from 'lucide-vue-next'
import Navbar from '../components/Navbar.vue'
import AgentChat from '../components/agent/AgentChat.vue'
import {goBackOr} from '../utils/nav'

const route = useRoute()
const router = useRouter()

const agentCode = computed(() => String(route.params.code || ''))

const queryValue = (value) => {
  const raw = Array.isArray(value) ? value[0] : value
  return raw === undefined || raw === null || raw === '' ? null : raw
}

const context = computed(() => ({
  product_id: queryValue(route.query.product_id),
  order_id: queryValue(route.query.order_id)
}))

// 同一个 Agent 换了上下文（例如从另一个药品详情进来）时重新挂载会话
const chatKey = computed(() => `${agentCode.value}-${context.value.product_id || ''}-${context.value.order_id || ''}`)
</script>

<template>
  <div class="agent-chat-page">
    <Navbar/>

    <div class="page-container">
      <div class="top-bar">
        <button type="button" class="back-link" @click="goBackOr(router, '/agents')">
          <ArrowLeft :size="16"/>
          返回
        </button>
      </div>

      <AgentChat
          :key="chatKey"
          :agent-code="agentCode"
          :context="context"
      />
    </div>
  </div>
</template>

<style scoped lang="scss">
.agent-chat-page {
  min-height: 100vh;
  background: #f3f4f6;
  padding-top: 64px;

  .page-container {
    width: 100%;
    max-width: 900px;
    height: calc(100vh - 64px);
    margin: 0 auto;
    padding: 12px 16px 16px;
    display: flex;
    flex-direction: column;
    min-height: 0;
  }

  .top-bar {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    margin-bottom: 8px;
  }

  .back-link {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 0;
    border: none;
    background: transparent;
    color: #6b7280;
    font-size: 13px;
    cursor: pointer;

    &:hover {
      color: #ef4444;
    }
  }

  @media (max-width: 768px) {
    .page-container {
      padding: 8px;
    }

    .top-bar {
      margin-bottom: 6px;
    }
  }
}
</style>
