<script setup>
/**
 * 面试官导览：右下角浮标 + 右侧抽屉。
 *
 * 五个页签对应面试时最常被问的五类问题：这是什么 / 能做到什么程度 /
 * 关键取舍在哪 / 后面怎么长 / 现在带我走一遍。
 *
 * 「动手走一遍」的勾选状态存 localStorage：面试官点过哪一步不用记，进度条会告诉他。
 * 注意这里只做「跳转」，不自动点按钮——自动演示一旦失败比不演示更尴尬。
 */
import {computed, ref} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import {Check, Compass, RotateCcw, X} from 'lucide-vue-next'
import {BOUNDARY, GUIDE_TABS, INTRO, NEXT_STEPS, THINKING, TOUR_STEPS} from '../../data/guide'
import {closeGuide, setGuideTab, useGuideState} from '../../store/guide'
import {siteConfig as site} from '../../config/site'

const {state} = useGuideState()
const router = useRouter()
const route = useRoute()

// 对话页 / 客服页底部是输入框，浮标压上去会挡住发送按钮——
// 这两处仍然可以从顶栏的「MVP 演示」徽标打开导览。
const hideFab = computed(() => (
  route.path.startsWith('/agents/') || route.path === '/support'
))

const show = computed({
  get: () => state.open,
  set: (value) => {
    if (!value) closeGuide()
  }
})

const PROGRESS_KEY = 'hhyy.tour.done'
const readDone = () => {
  try {
    const raw = window.localStorage.getItem(PROGRESS_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed : []
  } catch (e) {
    return []
  }
}

const done = ref(readDone())
const doneCount = computed(() => done.value.filter((id) => TOUR_STEPS.some((s) => s.id === id)).length)
const progress = computed(() => Math.round((doneCount.value / TOUR_STEPS.length) * 100))

const persist = () => {
  try {
    window.localStorage.setItem(PROGRESS_KEY, JSON.stringify(done.value))
  } catch (e) {
    // 忽略
  }
}

const toggleDone = (id) => {
  done.value = done.value.includes(id) ? done.value.filter((item) => item !== id) : [...done.value, id]
  persist()
}

const resetDone = () => {
  done.value = []
  persist()
}

const goStep = (step) => {
  if (!step || !step.to) return
  toggleDone(step.id)
  closeGuide()
  router.push(step.to)
}

const isDone = (id) => done.value.includes(id)
</script>

<template>
  <div>
    <button v-if="!hideFab" type="button" class="guide-fab" aria-label="打开项目导览" @click="state.open = true">
      <Compass :size="18"/>
      <span>导览</span>
    </button>

    <van-popup
        v-model:show="show"
        position="right"
        :style="{ width: '100%', maxWidth: '560px', height: '100%' }"
        class="guide-popup"
    >
      <div class="guide">
        <header class="guide-head">
          <div>
            <span class="guide-kicker">面试导览</span>
            <h2>{{ site.guide.title }}</h2>
            <p>{{ site.guide.subtitle }}</p>
          </div>
          <button type="button" class="guide-close" aria-label="关闭" @click="closeGuide">
            <X :size="18"/>
          </button>
        </header>

        <nav class="guide-tabs">
          <button
              v-for="tab in GUIDE_TABS"
              :key="tab.key"
              type="button"
              class="guide-tab"
              :class="{ 'is-active': state.tab === tab.key }"
              @click="setGuideTab(tab.key)"
          >
            {{ tab.label }}
          </button>
        </nav>

        <div class="guide-body">
          <!-- 1. 项目介绍 -->
          <section v-if="state.tab === 'intro'" class="guide-section">
            <p class="lead">{{ INTRO.lead }}</p>

            <h4>一条消息的旅程</h4>
            <ol class="flow">
              <li v-for="(item, index) in INTRO.flow" :key="index">
                <span class="flow-index">{{ index + 1 }}</span>
                <span>{{ item }}</span>
              </li>
            </ol>

            <h4>技术栈</h4>
            <div class="stack">
              <span v-for="item in INTRO.stack" :key="item.label" class="stack-item">
                <b>{{ item.label }}</b>
                <em>{{ item.note }}</em>
              </span>
            </div>

            <h4>规模</h4>
            <ul class="facts">
              <li v-for="item in INTRO.facts" :key="item.label">
                <b>{{ item.label }}</b>
                <span>{{ item.text }}</span>
              </li>
            </ul>
          </section>

          <!-- 2. 能力边界 -->
          <section v-else-if="state.tab === 'boundary'" class="guide-section">
            <p class="lead">
              面试里最加分的不是「什么都能做」，而是「知道哪里不能做、并且系统里真的拦住了」。
            </p>

            <div class="boundary-card can">
              <h4>能做</h4>
              <ul>
                <li v-for="item in BOUNDARY.can" :key="item">{{ item }}</li>
              </ul>
            </div>

            <div class="boundary-card cannot">
              <h4>不做 / 做不到</h4>
              <ul>
                <li v-for="item in BOUNDARY.cannot" :key="item">{{ item }}</li>
              </ul>
            </div>

            <p class="note">
              拒答不是「模型心情好才拒」：检索层有范围守卫（问题里的疾病词必须出现在召回文本里），
              治理层还会再校验一次引用与免责声明。
            </p>
          </section>

          <!-- 3. 设计思考 -->
          <section v-else-if="state.tab === 'thinking'" class="guide-section">
            <p class="lead">几个当时纠结过的取舍，按「问题 → 选择 → 代价」讲。</p>
            <article v-for="item in THINKING" :key="item.title" class="think-card">
              <h4>{{ item.title }}</h4>
              <p>{{ item.body }}</p>
            </article>
          </section>

          <!-- 4. 后续拓展 -->
          <section v-else-if="state.tab === 'next'" class="guide-section">
            <p class="lead">MVP 收在哪、下一步往哪长，按投入产出排序。</p>
            <article v-for="item in NEXT_STEPS" :key="item.title" class="think-card">
              <h4>{{ item.title }}</h4>
              <p>{{ item.body }}</p>
            </article>
          </section>

          <!-- 5. 动手走一遍 -->
          <section v-else class="guide-section">
            <div class="tour-head">
              <div>
                <p class="lead" style="margin: 0">
                  八步覆盖 Agent、RAG、记忆、转人工、治理与评估。点一步直接跳过去。
                </p>
              </div>
              <button type="button" class="tour-reset" @click="resetDone">
                <RotateCcw :size="12"/>
                重置
              </button>
            </div>

            <div class="tour-progress">
              <div class="tour-bar"><span :style="{ width: `${progress}%` }"/></div>
              <small>{{ doneCount }} / {{ TOUR_STEPS.length }} 已完成</small>
            </div>

            <ol class="tour-list">
              <li v-for="step in TOUR_STEPS" :key="step.id" class="tour-step" :class="{ 'is-done': isDone(step.id) }">
                <button type="button" class="tour-check" :aria-label="isDone(step.id) ? '取消完成' : '标记完成'" @click="toggleDone(step.id)">
                  <Check v-if="isDone(step.id)" :size="12"/>
                </button>
                <div class="tour-content">
                  <h4>{{ step.title }}</h4>
                  <p>{{ step.desc }}</p>
                  <small v-if="step.hint">提示：{{ step.hint }}</small>
                </div>
                <button type="button" class="tour-go" @click="goStep(step)">去这里</button>
              </li>
            </ol>
          </section>
        </div>
      </div>
    </van-popup>
  </div>
</template>

<style scoped lang="scss">
.guide-fab {
  position: fixed;
  right: 18px;
  bottom: 22px;
  z-index: 950;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 14px;
  border: 1px solid #fecaca;
  border-radius: 999px;
  background: #fff;
  color: #b91c1c;
  font-size: 13px;
  font-weight: 600;
  box-shadow: 0 8px 20px -10px rgba(220, 38, 38, 0.55);
  cursor: pointer;
  transition: transform 0.16s, box-shadow 0.16s;

  &:hover {
    transform: translateY(-1px);
    box-shadow: 0 12px 24px -10px rgba(220, 38, 38, 0.6);
  }
}

@media (max-width: 768px) {
  .guide-fab {
    right: 12px;
    bottom: calc(76px + env(safe-area-inset-bottom, 0px));
    padding: 8px 12px;
    font-size: 12px;
  }
}

.guide {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #fff;
}

.guide-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 20px 20px 14px;
  background: linear-gradient(135deg, #fef2f2, #fff7ed);

  .guide-kicker {
    display: inline-block;
    padding: 1px 8px;
    border-radius: 6px;
    background: #dc2626;
    color: #fff;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.5px;
  }

  h2 {
    margin: 8px 0 4px;
    font-size: 18px;
    color: #111827;
  }

  p {
    margin: 0;
    font-size: 12px;
    color: #6b7280;
    line-height: 1.6;
  }

  .guide-close {
    display: grid;
    place-items: center;
    width: 30px;
    height: 30px;
    border: none;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.7);
    color: #6b7280;
    cursor: pointer;
    flex-shrink: 0;

    &:hover {
      background: #fff;
      color: #111827;
    }
  }
}

.guide-tabs {
  display: flex;
  gap: 4px;
  padding: 10px 14px;
  overflow-x: auto;
  border-bottom: 1px solid #e5e7eb;
  scrollbar-width: none;

  &::-webkit-scrollbar {
    display: none;
  }

  .guide-tab {
    flex: 0 0 auto;
    padding: 6px 12px;
    border: 1px solid transparent;
    border-radius: 999px;
    background: transparent;
    color: #4b5563;
    font-size: 12px;
    cursor: pointer;
    white-space: nowrap;

    &.is-active {
      background: #fef2f2;
      border-color: #fecaca;
      color: #b91c1c;
      font-weight: 600;
    }
  }
}

.guide-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px 28px;
  -webkit-overflow-scrolling: touch;
}

.guide-section {
  .lead {
    margin: 0 0 16px;
    padding: 12px 14px;
    border-radius: 10px;
    background: #f9fafb;
    border-left: 3px solid #f87171;
    font-size: 13px;
    line-height: 1.75;
    color: #374151;
  }

  h4 {
    margin: 18px 0 8px;
    font-size: 13px;
    font-weight: 700;
    color: #111827;
  }
}

.flow {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 8px;

  li {
    display: flex;
    gap: 8px;
    font-size: 12.5px;
    line-height: 1.65;
    color: #4b5563;
  }

  .flow-index {
    flex-shrink: 0;
    display: grid;
    place-items: center;
    width: 18px;
    height: 18px;
    margin-top: 2px;
    border-radius: 50%;
    background: #fef2f2;
    color: #b91c1c;
    font-size: 10px;
    font-weight: 700;
  }
}

.stack {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;

  .stack-item {
    display: inline-flex;
    align-items: baseline;
    gap: 6px;
    padding: 5px 10px;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    background: #fff;
    font-size: 12px;

    b {
      color: #111827;
    }

    em {
      font-style: normal;
      color: #9ca3af;
      font-size: 11px;
    }
  }
}

.facts {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;

  li {
    display: flex;
    gap: 8px;
    font-size: 12.5px;
    line-height: 1.6;

    b {
      flex-shrink: 0;
      color: #b91c1c;
    }

    span {
      color: #4b5563;
    }
  }
}

.boundary-card {
  margin-bottom: 12px;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid #e5e7eb;

  h4 {
    margin: 0 0 8px;
    font-size: 13px;
  }

  ul {
    margin: 0;
    padding-left: 18px;
    display: flex;
    flex-direction: column;
    gap: 5px;

    li {
      font-size: 12.5px;
      line-height: 1.65;
      color: #4b5563;
    }
  }

  &.can {
    background: #f0fdf4;
    border-color: #bbf7d0;

    h4 {
      color: #15803d;
    }
  }

  &.cannot {
    background: #fef2f2;
    border-color: #fecaca;

    h4 {
      color: #b91c1c;
    }
  }
}

.note {
  margin: 4px 0 0;
  font-size: 12px;
  color: #6b7280;
  line-height: 1.7;
}

.think-card {
  margin-bottom: 10px;
  padding: 12px 14px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;

  h4 {
    margin: 0 0 6px;
    font-size: 13px;
    color: #b91c1c;
  }

  p {
    margin: 0;
    font-size: 12.5px;
    line-height: 1.75;
    color: #4b5563;
  }
}

.tour-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;

  .tour-reset {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    flex-shrink: 0;
    padding: 4px 10px;
    border: 1px solid #e5e7eb;
    border-radius: 999px;
    background: #fff;
    color: #6b7280;
    font-size: 11px;
    cursor: pointer;
  }
}

.tour-progress {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;

  .tour-bar {
    flex: 1;
    height: 6px;
    border-radius: 999px;
    background: #f3f4f6;
    overflow: hidden;

    span {
      display: block;
      height: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, #f87171, #dc2626);
      transition: width 0.3s ease;
    }
  }

  small {
    flex-shrink: 0;
    font-size: 11px;
    color: #9ca3af;
  }
}

.tour-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tour-step {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  transition: border-color 0.18s, background 0.18s;

  &.is-done {
    background: #f9fafb;

    .tour-content h4 {
      color: #9ca3af;
      text-decoration: line-through;
    }
  }

  .tour-check {
    flex-shrink: 0;
    display: grid;
    place-items: center;
    width: 18px;
    height: 18px;
    margin-top: 1px;
    border: 1.5px solid #d1d5db;
    border-radius: 5px;
    background: #fff;
    color: #fff;
    cursor: pointer;
  }

  &.is-done .tour-check {
    background: #16a34a;
    border-color: #16a34a;
  }

  .tour-content {
    flex: 1;
    min-width: 0;

    h4 {
      margin: 0 0 3px;
      font-size: 12.5px;
      color: #111827;
    }

    p {
      margin: 0;
      font-size: 12px;
      line-height: 1.65;
      color: #6b7280;
    }

    small {
      display: block;
      margin-top: 4px;
      font-size: 11px;
      color: #9ca3af;
    }
  }

  .tour-go {
    flex-shrink: 0;
    padding: 4px 10px;
    border: 1px solid #fecaca;
    border-radius: 999px;
    background: #fef2f2;
    color: #b91c1c;
    font-size: 11px;
    cursor: pointer;
    white-space: nowrap;

    &:hover {
      background: #fee2e2;
    }
  }
}
</style>
