<script setup>
import {onMounted, ref} from 'vue'
import {useRouter} from 'vue-router'
import {Bot, RefreshCw} from 'lucide-vue-next'
import Navbar from '../components/Navbar.vue'
import AgentCard from '../components/agent/AgentCard.vue'
import {fetchAgents} from '../api/chat'

const router = useRouter()

const agents = ref([])
const loading = ref(true)
const failed = ref('')

const load = async (force = false) => {
  loading.value = true
  failed.value = ''
  try {
    const list = await fetchAgents(force)
    agents.value = Array.isArray(list) ? list : []
  } catch (e) {
    agents.value = []
    failed.value = (e && e.message) || 'Agent 列表加载失败'
  } finally {
    loading.value = false
  }
}

const openAgent = (agent) => {
  if (!agent) return
  const target = agent.entry || `/agents/${agent.code}`
  router.push(target)
}

onMounted(() => load())
</script>

<template>
  <div class="agents-page">
    <Navbar/>

    <div class="page-container">
      <div class="page-header">
        <div class="title-row">
          <div class="title-icon">
            <Bot :size="20" color="#fff"/>
          </div>
          <div class="title-text">
            <h2>Agent 广场</h2>
            <p>选择一个 Agent 开始对话；在输入框里打 @，还可以召唤其他 Agent 一起协作。</p>
          </div>
        </div>

        <button type="button" class="refresh-btn" :disabled="loading" @click="load(true)">
          <RefreshCw :size="14" :class="{ spinning: loading }"/>
          刷新
        </button>
      </div>

      <div v-if="loading" class="state-box">
        <van-loading type="dots" size="22px" color="#ef4444"/>
        <span>正在加载 Agent…</span>
      </div>

      <div v-else-if="failed" class="state-box error">
        <span>{{ failed }}</span>
        <button type="button" class="state-btn" @click="load(true)">重试</button>
      </div>

      <van-empty v-else-if="agents.length === 0" description="暂时没有可用的 Agent"/>

      <div v-else class="agent-grid">
        <AgentCard
            v-for="agent in agents"
            :key="agent.code || agent.name"
            :agent="agent"
            @select="openAgent"
        />
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.agents-page {
  min-height: 100vh;
  background: #f3f4f6;
  padding-top: 64px;
  padding-bottom: 24px;

  .page-container {
    max-width: 1000px;
    margin: 0 auto;
    padding: 24px;
  }

  .page-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 18px;

    .title-row {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }

    .title-icon {
      width: 40px;
      height: 40px;
      flex-shrink: 0;
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: linear-gradient(135deg, #ef4444, #b91c1c);
      box-shadow: 0 6px 14px rgba(239, 68, 68, 0.25);
    }

    .title-text {
      min-width: 0;

      h2 {
        font-size: 22px;
        color: #111827;
        line-height: 1.3;
      }

      p {
        margin-top: 4px;
        font-size: 13px;
        color: #6b7280;
        line-height: 1.6;
      }
    }

    .refresh-btn {
      flex-shrink: 0;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      margin-top: 4px;
      padding: 6px 12px;
      border-radius: 8px;
      border: 1px solid #fecaca;
      background: #fff;
      color: #b91c1c;
      font-size: 12px;
      cursor: pointer;
      transition: background-color 0.15s ease;

      &:hover {
        background: #fef2f2;
      }

      &:disabled {
        opacity: 0.6;
        cursor: not-allowed;
      }

      .spinning {
        animation: agents-spin 0.9s linear infinite;
      }
    }
  }

  .agent-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 16px;
  }

  .state-box {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    min-height: 220px;
    font-size: 13px;
    color: #6b7280;
    background: #fff;
    border-radius: 12px;
    border: 1px solid #f3f4f6;

    &.error {
      flex-direction: column;
      color: #b91c1c;
      background: #fef2f2;
      border-color: #fecaca;
    }

    .state-btn {
      padding: 3px 14px;
      border-radius: 6px;
      border: 1px solid #fecaca;
      background: #fff;
      color: #b91c1c;
      font-size: 12px;
      cursor: pointer;
    }
  }

  @media (max-width: 768px) {
    padding-bottom: 16px;

    .page-container {
      padding: 16px 12px;
    }

    .page-header {
      flex-direction: column;
      align-items: stretch;
      gap: 10px;

      .title-text h2 {
        font-size: 19px;
      }

      .refresh-btn {
        align-self: flex-end;
        margin-top: 0;
      }
    }

    .agent-grid {
      grid-template-columns: 1fr;
      gap: 12px;
    }
  }
}

@keyframes agents-spin {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}
</style>
