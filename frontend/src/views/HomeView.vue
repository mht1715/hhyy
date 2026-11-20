<script setup>
/**
 * 游客落地页：面试官打开的第一个页面，必须回答三件事——
 * 「这是什么」「凭什么可信」「我该点哪里」。
 *
 * 所以这里的数字全部来自 `/api/public/stats`（知识库文档数、切片数、Agent 数、
 * 最近一次评估的召回率），而不是写死「服务 10 万用户」。接口挂了就显示「—」，
 * 不影响页面可用——落地页因为一个统计接口 500 而白屏是最亏的。
 */
import {computed, onMounted, ref} from 'vue'
import {useRouter} from 'vue-router'
import {showToast} from 'vant'
import {
  ArrowRight,
  Bot,
  BookOpen,
  Brain,
  CheckCircle2,
  Compass,
  Database,
  Headphones,
  Pill,
  PlayCircle,
  ReceiptText,
  ShieldCheck,
  ShoppingCart,
  Sparkles,
  Users
} from 'lucide-vue-next'
import Navbar from '../components/Navbar.vue'
import MvpBanner from '../components/workbench/MvpBanner.vue'
import {fetchPublicStats} from '../api/workbench'
import {useAuthStore} from '../store/auth'
import {resolveHomePath} from '../utils/permission'
import {openGuide} from '../store/guide'
import {siteConfig as site} from '../config/site'

const router = useRouter()
const auth = useAuthStore()

const stats = ref(null)
const statsFailed = ref(false)

const loadStats = async () => {
  statsFailed.value = false
  try {
    stats.value = await fetchPublicStats()
  } catch (e) {
    statsFailed.value = true
  }
}

onMounted(loadStats)

const number = (value) => (value === null || value === undefined ? '—' : String(value))
const percent = (value) => (
  value === null || value === undefined ? '—' : `${(Number(value) * 100).toFixed(0)}%`
)

const homePath = computed(() => resolveHomePath(auth.role))

const HERO_STATS = computed(() => [
  {label: '知识库文档', value: number(stats.value?.kb?.documents)},
  {label: '知识切片', value: number(stats.value?.kb?.chunks)},
  {label: '子 Agent', value: number(stats.value?.agents)},
  {label: '召回@5', value: percent(stats.value?.eval?.recall_at_5)}
])

const CAPABILITIES = [
  {
    key: 'routing',
    icon: Sparkles,
    title: '多 Agent 路由',
    desc: 'Supervisor 判断意图后分派给药品 / 售后 / 公司 / 客服四个子 Agent，路由理由可回看。',
    cta: '去 Agent 广场',
    to: '/agents'
  },
  {
    key: 'rag',
    icon: BookOpen,
    title: 'RAG 可溯源',
    desc: '混合召回 + 重排 + 阈值过滤，回答里的每个角标都能点开原文片段。',
    cta: '问一个说明书问题',
    to: '/agents/drug_consult'
  },
  {
    key: 'memory',
    icon: Brain,
    title: '三层记忆',
    desc: '会话检查点 + 窗口摘要 + 长期记忆；说过「对青霉素过敏」，下次不用再说。',
    cta: '看记忆管理',
    to: '/me/memory'
  },
  {
    key: 'handoff',
    icon: Headphones,
    title: '转人工闭环',
    desc: '显式点击或敏感词触发转人工，坐席接管后同一会话继续，结单自动回到 AI。',
    cta: '进客服工作台',
    to: '/support'
  }
]

// 角色卡片 = site.js 里的演示账号 + 本页自己的图标与配色。
// 图标是组件、配色是视觉细节，不适合塞进「站点信息」，所以只把账号数据放过去。
const ROLE_ICONS = {patient: Users, doctor: ShieldCheck, support: Headphones, admin: Database}
const ROLE_TONES = {
  patient: {color: '#059669', bg: '#ecfdf5'},
  doctor: {color: '#2563eb', bg: '#eff6ff'},
  support: {color: '#7c3aed', bg: '#f5f3ff'},
  admin: {color: '#dc2626', bg: '#fef2f2'}
}

const ROLES = site.demo.accounts.map((item) => ({
  ...item,
  icon: ROLE_ICONS[item.role] || Users,
  ...(ROLE_TONES[item.role] || {color: '#374151', bg: '#f3f4f6'})
}))

const FLOW = [
  {title: '路由', desc: 'Supervisor 选 Agent，带历史与指代改写'},
  {title: '检索', desc: '混合召回 → 重排 → 阈值 → 范围守卫'},
  {title: '生成', desc: '流式输出，边流边做合规改写'},
  {title: '治理', desc: '引用裁剪、免责声明、拒答识别'},
  {title: '沉淀', desc: '落库 + Langfuse 追踪 + 可评估'}
]

const loginBusy = ref('')

const enterAs = async (item) => {
  if (loginBusy.value) return
  loginBusy.value = item.username
  try {
    if (!auth.isLoggedIn || auth.username !== item.username) {
      await auth.login(item.username)
    }
    router.push(item.homePath || resolveHomePath(item.role))
  } catch (e) {
    showToast((e && e.message) || '演示账号登录失败，请确认后端已启动')
  } finally {
    loginBusy.value = ''
  }
}

const goWorkbench = () => {
  router.push(auth.isLoggedIn && homePath.value !== '/' ? homePath.value : '/agents')
}
</script>

<template>
  <div class="home">
    <Navbar/>

    <div class="page">
      <MvpBanner/>

      <!-- ============================ Hero ============================ -->
      <section class="hero">
        <div class="hero-left">
          <span class="hero-kicker">
            <Bot :size="13"/>
            Agent 应用开发 · 作品集
          </span>
          <h1>
            让药品知识<span class="accent">可查、可溯源、可拒答</span>
          </h1>
          <p class="hero-desc">
            一个面向 C 端咨询与 B 端坐席的 Agent 系统：多 Agent 编排、RAG 检索带引用、
            三层记忆、转人工闭环，以及一套能跑出指标的输出治理。
          </p>

          <div class="hero-actions">
            <button type="button" class="btn primary" @click="goWorkbench">
              <PlayCircle :size="16"/>
              {{ auth.isLoggedIn ? '进入我的工作台' : '开始体验' }}
            </button>
            <button type="button" class="btn ghost" @click="openGuide('tour')">
              <Compass :size="16"/>
              8 步导览
            </button>
          </div>

          <div class="hero-stats">
            <div v-for="item in HERO_STATS" :key="item.label" class="hero-stat">
              <b>{{ item.value }}</b>
              <small>{{ item.label }}</small>
            </div>
          </div>
          <p v-if="statsFailed" class="stats-note">统计接口未连通，数字显示为「—」；不影响对话功能。</p>
        </div>

        <div class="hero-right">
          <div class="flow-card">
            <header>
              <Sparkles :size="14"/>
              一条消息的旅程
            </header>
            <ol>
              <li v-for="(step, index) in FLOW" :key="step.title">
                <span class="flow-index">{{ index + 1 }}</span>
                <div>
                  <b>{{ step.title }}</b>
                  <small>{{ step.desc }}</small>
                </div>
              </li>
            </ol>
          </div>
        </div>
      </section>

      <!-- ========================= 能力地图 ========================= -->
      <section class="section">
        <header class="section-head">
          <h2>能力地图</h2>
          <p>每张卡都对应一个能点进去的真实功能，不是截图。</p>
        </header>
        <div class="cap-grid">
          <article v-for="item in CAPABILITIES" :key="item.key" class="cap-card">
            <div class="cap-icon"><component :is="item.icon" :size="18"/></div>
            <h3>{{ item.title }}</h3>
            <p>{{ item.desc }}</p>
            <button type="button" class="cap-link" @click="router.push(item.to)">
              {{ item.cta }}
              <ArrowRight :size="13"/>
            </button>
          </article>
        </div>
      </section>

      <!-- ========================= 商城链路 ========================= -->
      <section class="section">
        <header class="section-head">
          <h2>商城链路</h2>
          <p>药品瀑布流 → 详情（带 AI 药师）→ 加购 → 结算 → 订单，全程可点。</p>
        </header>
        <div class="shop-row">
          <button type="button" class="shop-card" @click="router.push('/drugs')">
            <span class="shop-icon"><Pill :size="18"/></span>
            <span class="shop-body">
              <strong>药品广场</strong>
              <small>分类筛选 + 瀑布流，游客也能逛</small>
            </span>
            <ArrowRight :size="15" class="shop-arrow"/>
          </button>
          <button type="button" class="shop-card" @click="router.push('/cart')">
            <span class="shop-icon"><ShoppingCart :size="18"/></span>
            <span class="shop-body">
              <strong>购物车</strong>
              <small>改数量、算总价、去结算</small>
            </span>
            <ArrowRight :size="15" class="shop-arrow"/>
          </button>
          <button type="button" class="shop-card" @click="router.push('/orders')">
            <span class="shop-icon"><ReceiptText :size="18"/></span>
            <span class="shop-body">
              <strong>我的订单</strong>
              <small>状态流转、取消与确认收货</small>
            </span>
            <ArrowRight :size="15" class="shop-arrow"/>
          </button>
        </div>
      </section>

      <!-- ========================= 角色入口 ========================= -->
      <section class="section">
        <header class="section-head">
          <h2>按角色体验</h2>
          <p>点一下即用演示账号登录（密码统一 {{ site.demo.password }}），直接进对应工作台。</p>
        </header>
        <div class="role-grid">
          <button
              v-for="item in ROLES"
              :key="item.role"
              type="button"
              class="role-card"
              :disabled="!!loginBusy"
              @click="enterAs(item)"
          >
            <span class="role-icon" :style="{ background: item.bg, color: item.color }">
              <component :is="item.icon" :size="18"/>
            </span>
            <span class="role-body">
              <strong>{{ item.title }}工作台</strong>
              <small>{{ item.desc }}</small>
            </span>
            <span class="role-go">
              {{ loginBusy === item.username ? '登录中…' : '进入' }}
            </span>
          </button>
        </div>
      </section>

      <!-- ========================= 边界说明 ========================= -->
      <section class="section boundary">
        <div class="boundary-copy">
          <h2>它明确不做什么</h2>
          <p>
            不做诊断、不开处方、不替代医生；知识库外的问题直接拒答，不硬编。
            高危症状只给「立即就医」提示再谈药理。
          </p>
          <button type="button" class="btn ghost small" @click="openGuide('boundary')">
            完整能力边界
            <ArrowRight :size="13"/>
          </button>
        </div>
        <ul class="boundary-list">
          <li><CheckCircle2 :size="14"/> 说明书问答带引用角标，可点开原文</li>
          <li><CheckCircle2 :size="14"/> 记忆按账号隔离，可逐条删除</li>
          <li><CheckCircle2 :size="14"/> 50 条 golden set，一条命令出指标</li>
          <li class="muted">支付 / 物流 / 处方为模拟流程</li>
        </ul>
      </section>

      <footer class="home-foot">
        <span>{{ site.footer.stack.join(' · ') }}</span>
        <span class="dot">·</span>
        <span>演示账号 {{ site.demo.accounts.map((item) => item.username).join(' / ') }}</span>
      </footer>
    </div>
  </div>
</template>

<style scoped lang="scss">
.home {
  min-height: 100vh;
  padding-top: 64px;
  background:
      radial-gradient(900px 420px at 12% -8%, #fee2e2 0%, transparent 60%),
      radial-gradient(800px 380px at 92% 0%, #eff6ff 0%, transparent 55%),
      #f7f8fa;
}

.page {
  max-width: 1120px;
  margin: 0 auto;
  padding: 16px 20px 40px;
}

/* ------------------------------- Hero ------------------------------- */
.hero {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr);
  gap: 24px;
  align-items: start;
  padding: 18px 0 28px;

  .hero-kicker {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 3px 10px;
    border-radius: 999px;
    background: #fff;
    border: 1px solid #fecaca;
    color: #b91c1c;
    font-size: 11px;
    font-weight: 600;
  }

  h1 {
    margin: 14px 0 10px;
    font-size: 34px;
    line-height: 1.25;
    color: #111827;
    letter-spacing: -0.5px;

    .accent {
      color: #dc2626;
      background: linear-gradient(180deg, transparent 62%, #fecaca 62%);
    }
  }

  .hero-desc {
    margin: 0 0 18px;
    max-width: 560px;
    font-size: 14px;
    line-height: 1.8;
    color: #4b5563;
  }

  .hero-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 20px;
  }

  .hero-stats {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 10px;
    max-width: 560px;

    .hero-stat {
      padding: 10px 12px;
      border-radius: 10px;
      background: #fff;
      border: 1px solid #e5e7eb;

      b {
        display: block;
        font-size: 19px;
        color: #111827;
      }

      small {
        font-size: 11px;
        color: #9ca3af;
      }
    }
  }

  .stats-note {
    margin: 8px 0 0;
    font-size: 11px;
    color: #b45309;
  }
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 16px;
  border-radius: 999px;
  border: 1px solid transparent;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.16s, box-shadow 0.16s, background 0.16s;

  &.primary {
    background: #dc2626;
    color: #fff;
    box-shadow: 0 8px 18px -10px rgba(220, 38, 38, 0.8);

    &:hover {
      background: #b91c1c;
      transform: translateY(-1px);
    }
  }

  &.ghost {
    background: #fff;
    border-color: #e5e7eb;
    color: #374151;

    &:hover {
      border-color: #fecaca;
      color: #b91c1c;
    }
  }

  &.small {
    padding: 6px 12px;
    font-size: 12px;
  }
}

.flow-card {
  padding: 16px 18px;
  border-radius: 14px;
  background: #fff;
  border: 1px solid #e5e7eb;
  box-shadow: 0 12px 30px -24px rgba(17, 24, 39, 0.5);

  header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding-bottom: 10px;
    margin-bottom: 10px;
    border-bottom: 1px dashed #e5e7eb;
    font-size: 12px;
    font-weight: 600;
    color: #b91c1c;
  }

  ol {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  li {
    display: flex;
    gap: 8px;
    align-items: flex-start;
  }

  .flow-index {
    flex-shrink: 0;
    display: grid;
    place-items: center;
    width: 18px;
    height: 18px;
    margin-top: 1px;
    border-radius: 50%;
    background: #fef2f2;
    color: #b91c1c;
    font-size: 10px;
    font-weight: 700;
  }

  b {
    display: block;
    font-size: 12.5px;
    color: #111827;
  }

  small {
    font-size: 11.5px;
    color: #6b7280;
    line-height: 1.5;
  }
}

/* ------------------------------ 通用区块 ------------------------------ */
.section {
  padding: 26px 0;
  border-top: 1px solid #eceef1;

  .section-head {
    margin-bottom: 16px;

    h2 {
      margin: 0 0 4px;
      font-size: 20px;
      color: #111827;
    }

    p {
      margin: 0;
      font-size: 13px;
      color: #6b7280;
    }
  }
}

.cap-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.cap-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  transition: border-color 0.16s, box-shadow 0.16s, transform 0.16s;

  &:hover {
    border-color: #fecaca;
    box-shadow: 0 12px 26px -20px rgba(17, 24, 39, 0.6);
    transform: translateY(-2px);
  }

  .cap-icon {
    display: grid;
    place-items: center;
    width: 34px;
    height: 34px;
    border-radius: 10px;
    background: #fef2f2;
    color: #dc2626;
  }

  h3 {
    margin: 0;
    font-size: 14px;
    color: #111827;
  }

  p {
    margin: 0;
    flex: 1;
    font-size: 12.5px;
    line-height: 1.7;
    color: #6b7280;
  }

  .cap-link {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-top: 4px;
    padding: 0;
    border: none;
    background: transparent;
    color: #b91c1c;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;

    &:hover {
      text-decoration: underline;
    }
  }
}

/* 商城链路：三张横条卡片，比大卡片更容易扫读，也明确带箭头表示可点 */
.shop-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;

  .shop-card {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 14px 16px;
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    text-align: left;
    cursor: pointer;
    transition: border-color 0.16s, box-shadow 0.16s, transform 0.16s;

    &:hover {
      border-color: #fecaca;
      box-shadow: 0 12px 26px -20px rgba(17, 24, 39, 0.6);
      transform: translateY(-1px);

      .shop-arrow {
        color: #dc2626;
        transform: translateX(2px);
      }
    }

    .shop-icon {
      display: grid;
      place-items: center;
      width: 34px;
      height: 34px;
      border-radius: 10px;
      background: #fef2f2;
      color: #dc2626;
      flex-shrink: 0;
    }

    .shop-body {
      flex: 1;
      min-width: 0;

      strong {
        display: block;
        font-size: 13.5px;
        color: #111827;
      }

      small {
        font-size: 11.5px;
        color: #9ca3af;
      }
    }

    .shop-arrow {
      flex-shrink: 0;
      color: #9ca3af;
      transition: color 0.16s, transform 0.16s;
    }
  }
}

.role-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  .role-card {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px;
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    text-align: left;
    cursor: pointer;
    transition: border-color 0.16s, box-shadow 0.16s;

    &:hover:not(:disabled) {
      border-color: #fecaca;
      box-shadow: 0 10px 22px -18px rgba(17, 24, 39, 0.6);
    }

    &:disabled {
      opacity: 0.7;
      cursor: default;
    }

    .role-icon {
      display: grid;
      place-items: center;
      width: 36px;
      height: 36px;
      border-radius: 10px;
      flex-shrink: 0;
    }

    .role-body {
      flex: 1;
      min-width: 0;

      strong {
        display: block;
        font-size: 13px;
        color: #111827;
      }

      small {
        font-size: 11px;
        color: #9ca3af;
      }
    }

    .role-go {
      flex-shrink: 0;
      font-size: 11px;
      color: #b91c1c;
      font-weight: 600;
    }
  }
}

.boundary {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr);
  gap: 24px;
  align-items: center;

  .boundary-copy {
    h2 {
      margin: 0 0 8px;
      font-size: 20px;
      color: #111827;
    }

    p {
      margin: 0 0 14px;
      font-size: 13px;
      line-height: 1.8;
      color: #4b5563;
    }
  }

  .boundary-list {
    margin: 0;
    padding: 16px 18px;
    list-style: none;
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 14px;
    display: flex;
    flex-direction: column;
    gap: 9px;

    li {
      display: flex;
      align-items: center;
      gap: 7px;
      font-size: 12.5px;
      color: #374151;

      svg {
        color: #059669;
        flex-shrink: 0;
      }

      &.muted {
        color: #9ca3af;
        font-size: 11.5px;
      }
    }
  }
}

.home-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: center;
  padding-top: 22px;
  border-top: 1px solid #eceef1;
  font-size: 11.5px;
  color: #9ca3af;
}

/* ------------------------------- 响应式 ------------------------------- */
@media (max-width: 960px) {
  .hero {
    grid-template-columns: minmax(0, 1fr);
    gap: 18px;
  }

  .hero-right {
    order: -1;
  }

  .cap-grid,
  .role-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .shop-row {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 768px) {
  .home {
    padding-top: 60px;
  }

  .page {
    padding: 12px 12px calc(84px + env(safe-area-inset-bottom, 0px));
  }

  .hero {
    padding-top: 8px;

    h1 {
      font-size: 25px;
    }

    .hero-desc {
      font-size: 13px;
    }

    .hero-stats {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  .cap-grid,
  .role-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .boundary {
    grid-template-columns: minmax(0, 1fr);
  }

  .btn {
    padding: 10px 16px;
    min-height: 42px;
  }
}
</style>
