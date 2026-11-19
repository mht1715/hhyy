<script setup>
// KeepAlive 依赖组件名（App.vue 的 CACHED 白名单按 name 匹配）
defineOptions({name: 'AgentsView'})

/**
 * Agent 广场。
 *
 * 除了「选一个 Agent 进去聊」，这页还承担「不用自己想问题」的职责：
 *   - 顶部「一句话开始」：输入框 + 选择 Agent，直接带着问题进对话（?q= 预填）；
 *   - 快捷体验：6 个业务场景入口，每条都写了示例提问，点一下就到；
 *   - 每张 Agent 卡片下面挂 2 条示例，点一下进对话并预填。
 *
 * 权限：不在自己角色范围内的入口显示锁图标，点了先提示登录 / 切换身份，
 * 而不是跳过去吃一个 403（那看起来像功能坏了）。
 */
import {computed, onMounted, ref} from 'vue'
import {useRouter} from 'vue-router'
import {ArrowRight, Bot, Lock, RefreshCw, Sparkles} from 'lucide-vue-next'
import {showToast} from 'vant'
import Navbar from '../components/Navbar.vue'
import AgentCard from '../components/agent/AgentCard.vue'
import FeatureHint from '../components/workbench/FeatureHint.vue'
import {fetchAgents} from '../api/chat'
import {openGuide} from '../store/guide'
import {useAuthStore} from '../store/auth'
import {QUICK_ENTRIES, ROLE_LABELS, samplesFor} from '../data/agentShortcuts'

const router = useRouter()
const auth = useAuthStore()

const agents = ref([])
const loading = ref(true)
const failed = ref('')

const quickText = ref('')
const quickAgent = ref('')

const load = async (force = false) => {
  loading.value = true
  failed.value = ''
  try {
    const list = await fetchAgents(force)
    agents.value = Array.isArray(list) ? list : []
    // 默认选「用药咨询」，它不在当前角色可见列表里时退到第一个
    const preferred = agents.value.find((agent) => agent.code === 'drug_consult')
    const fallback = agents.value[0]
    quickAgent.value = (preferred || fallback || {}).code || ''
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

/** 示例问题：进对话并预填，是否发送交给用户确认（避免替用户做主）。 */
const askSample = (agent, text) => {
  if (!agent || !text) return
  router.push({path: `/agents/${agent.code}`, query: {q: text}})
}

/** 顶部的自由输入：选一个 Agent，把问题带过去。 */
const submitQuick = () => {
  const text = quickText.value.trim()
  if (!text) {
    showToast('先写一句想问的问题')
    return
  }
  if (!quickAgent.value) {
    showToast('当前身份没有可用的 Agent，请先登录或切换角色')
    return
  }
  router.push({path: `/agents/${quickAgent.value}`, query: {q: text}})
}

/** 入口对当前身份是否不可用（游客看患者专属入口会显示锁）。 */
const entryLocked = (entry) => {
  if (!auth.isLoggedIn) return !entry.roles.includes('visitor')
  return !entry.roles.includes(auth.role)
}

const openEntry = (entry) => {
  if (!entry) return

  if (!auth.isLoggedIn) {
    if (!entry.roles.includes('visitor')) {
      auth.isLoginModalOpen = true
      showToast('这个入口需要登录；首页可以一键切换演示身份')
      return
    }
    router.push(entry.to)
    return
  }

  if (!entry.roles.includes(auth.role)) {
    const current = ROLE_LABELS[auth.role] || auth.role
    showToast(`当前身份（${current}）无权限，请切换为${entry.roleLabel}`)
    return
  }

  // 带了示例问题的入口：连问题一起带过去（AgentChat 会把 ?q= 填进输入框）
  if (entry.sample && entry.to.startsWith('/agents/')) {
    router.push({path: entry.to, query: {q: entry.sample}})
    return
  }
  if (entry.sample && entry.to === '/products') {
    router.push({path: entry.to, query: {q: entry.sample}})
    return
  }
  router.push(entry.to)
}

const quickEntries = computed(() => QUICK_ENTRIES)

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
            <p>挑一个 Agent 开始对话；在输入框里打 @，还可以召唤其他 Agent 一起协作。</p>
          </div>
        </div>

        <button type="button" class="refresh-btn" :disabled="loading" @click="load(true)">
          <RefreshCw :size="14" :class="{ spinning: loading }"/>
          刷新
        </button>
      </div>

      <!-- 快捷体验：面试官不用自己编问题 -->
      <section class="quick-panel" aria-label="快捷体验">
        <div class="quick-head">
          <strong>
            <Sparkles :size="15"/>
            一句话开始
          </strong>
          <small>不想自己想问题？挑一条示例，或者直接输入</small>
        </div>

        <form class="quick-form" @submit.prevent="submitQuick">
          <input
              v-model="quickText"
              class="quick-input"
              type="text"
              placeholder="例如：花红片哺乳期能吃吗"
              aria-label="想问的问题"
              enterkeyhint="send"
          />
          <select v-model="quickAgent" class="quick-select" aria-label="选择 Agent">
            <option v-for="agent in agents" :key="agent.code" :value="agent.code">
              {{ agent.name }}
            </option>
          </select>
          <button type="submit" class="quick-send">去提问</button>
        </form>

        <div class="entry-grid">
          <button
              v-for="entry in quickEntries"
              :key="entry.key"
              type="button"
              class="entry-card"
              :class="{ 'is-locked': entryLocked(entry) }"
              @click="openEntry(entry)"
          >
            <div class="entry-top">
              <strong>{{ entry.title }}</strong>
              <Lock v-if="entryLocked(entry)" :size="12" class="lock-icon"/>
            </div>
            <small class="entry-desc">{{ entry.desc }}</small>
            <span v-if="entry.sample" class="entry-sample">“{{ entry.sample }}”</span>
            <ArrowRight :size="14" class="entry-arrow"/>
          </button>
        </div>
      </section>

      <FeatureHint
          class="agents-hint"
          title="怎么验证它真的在检索"
          text="随便问一个说明书问题，回答下方会列出引用来源；点角标能看命中的原文片段。问一个知识库里没有的疾病，它会拒答而不是硬编。"
          :tags="[{label: '为什么拒答要做在检索层', key: 'refusal'}]"
          storage-key="agents.list"
          @tag-click="openGuide('thinking')"
      />

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
            :samples="samplesFor(agent.code)"
            @select="openAgent"
            @ask="(text) => askSample(agent, text)"
        />
      </div>

      <p v-if="!loading && agents.length > 0 && !auth.isLoggedIn" class="login-tip">
        游客当前只能用「企业介绍」；首页的「一键登录」可以切到患者 / 医生 / 客服 / 管理员，
        解锁用药咨询、订单售后与后台入口。
      </p>
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

  /* ------------------------------ 快捷体验 ------------------------------ */
  .quick-panel {
    background: #fff;
    border: 1px solid #f3f4f6;
    border-radius: 14px;
    padding: 14px;
    margin-bottom: 14px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
  }

  .quick-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    flex-wrap: wrap;
    margin-bottom: 10px;

    strong {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 14px;
      color: #111827;
    }

    small {
      font-size: 12px;
      color: #9ca3af;
    }
  }

  .quick-form {
    display: flex;
    gap: 8px;
    margin-bottom: 12px;

    .quick-input {
      flex: 1;
      min-width: 0;
      height: 40px;
      padding: 0 12px;
      border: 1px solid #e5e7eb;
      border-radius: 10px;
      font-size: 13px;
      color: #111827;
      outline: none;

      &:focus {
        border-color: #fca5a5;
        box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.08);
      }
    }

    .quick-select {
      flex: none;
      max-width: 150px;
      height: 40px;
      padding: 0 8px;
      border: 1px solid #e5e7eb;
      border-radius: 10px;
      background: #fff;
      font-size: 13px;
      color: #374151;
    }

    .quick-send {
      flex: none;
      height: 40px;
      padding: 0 16px;
      border: none;
      border-radius: 10px;
      background: #dc2626;
      color: #fff;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;

      &:hover {
        background: #b91c1c;
      }
    }
  }

  .entry-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
    gap: 10px;
  }

  .entry-card {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
    padding: 10px 30px 10px 12px;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    background: #fff;
    text-align: left;
    cursor: pointer;
    transition: border-color 0.16s ease, background-color 0.16s ease, transform 0.16s ease;

    &:hover {
      border-color: #fecaca;
      background: #fffafa;
      transform: translateY(-1px);
    }

    &.is-locked {
      background: #fafafa;
    }

    .entry-top {
      display: flex;
      align-items: center;
      gap: 4px;

      strong {
        font-size: 13px;
        color: #111827;
      }

      .lock-icon {
        color: #9ca3af;
      }
    }

    .entry-desc {
      font-size: 11.5px;
      line-height: 1.5;
      color: #6b7280;
    }

    .entry-sample {
      font-size: 11.5px;
      color: #b91c1c;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .entry-arrow {
      position: absolute;
      right: 10px;
      top: 50%;
      transform: translateY(-50%);
      color: #d1d5db;
    }

    &:hover .entry-arrow {
      color: #dc2626;
    }
  }

  .login-tip {
    margin: 16px 0 0;
    padding: 10px 12px;
    border-radius: 10px;
    background: #fffbeb;
    border: 1px solid #fde68a;
    font-size: 12px;
    line-height: 1.7;
    color: #92400e;
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

    // 手机上输入框 + 下拉 + 按钮挤一行会溢出，拆成两行
    .quick-form {
      flex-wrap: wrap;

      .quick-input {
        flex: 1 1 100%;
      }

      .quick-select {
        flex: 1;
        max-width: none;
      }

      .quick-send {
        flex: none;
      }
    }

    .entry-grid {
      grid-template-columns: 1fr;
      gap: 8px;
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

/* 提示条在卡片网格上方，留一点呼吸感 */
.agents-hint {
  margin-bottom: 14px;
}
</style>
