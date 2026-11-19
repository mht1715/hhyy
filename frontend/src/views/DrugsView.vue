<script setup>
/**
 * 药品广场：患者 / 游客逛药的入口。
 *
 * 之前的药品列表在 /products，是后台管理页（加 / 改 / 删，只对 admin、doctor 开放），
 * 患者和游客根本进不去。这里换成公开只读目录，把「逛」和「管」分开：
 * 同一批数据，后台改，前台只负责展示与加购。
 *
 * 布局用 CSS columns 而不是 grid：药品卡的说明文字长短不一，grid 会把同一行
 * 拉到一样高、留下大片空白；columns 让每列按卡片自然高度往下排，才是真瀑布流。
 */
import {computed, onActivated, onBeforeUnmount, onMounted, ref} from 'vue'
import {useRouter} from 'vue-router'
import {RotateCcw, Search, ShoppingCart, X} from 'lucide-vue-next'
import {showToast} from 'vant'
import Navbar from '../components/Navbar.vue'
import PageBar from '../components/common/PageBar.vue'
import ProductCard from '../components/product/ProductCard.vue'
import PanelCard from '../components/workbench/PanelCard.vue'
import {listCatalogCategories, listCatalogProducts} from '../api/catalog'
import {useAuthStore} from '../store/auth'
import {useCartStore} from '../store/cart'

// App.vue 的 KeepAlive 用组件名做 include（CACHED 里已登记 DrugsView），
// 名字对不上就不会缓存——从详情页返回时筛选条件和滚动位置都会丢。
defineOptions({name: 'DrugsView'})

const router = useRouter()
const auth = useAuthStore()
const cart = useCartStore()

const products = ref([])
const categories = ref(['全部'])
const activeCategory = ref('全部')
const keyword = ref('')
const loading = ref(true)
const error = ref('')
const addingId = ref('')

const SEARCH_DEBOUNCE = 300
let searchTimer = 0
let requestController = null

const hasFilter = computed(() => keyword.value.trim() !== '' || activeCategory.value !== '全部')

/**
 * 拉取列表。
 *
 * 每次请求都 abort 上一次：用户快速改关键词时，先发的请求可能后回来，
 * 不做取消就会出现「列表和输入框对不上」的竞态。
 */
const fetchProducts = async () => {
  if (requestController) requestController.abort()
  const controller = new AbortController()
  requestController = controller

  loading.value = true
  error.value = ''

  try {
    const data = await listCatalogProducts({
      keyword: keyword.value.trim(),
      category: activeCategory.value === '全部' ? '' : activeCategory.value,
      signal: controller.signal
    })
    // 接口约定返回数组；万一后端给了 null 也当成空列表，模板里就不用到处判空
    products.value = Array.isArray(data) ? data : []
  } catch (e) {
    if (e && e.name === 'AbortError') return // 主动取消不是错误，别把骨架屏换成报错
    products.value = []
    error.value = (e && e.message) || '药品加载失败，请稍后重试'
  } finally {
    // 只有「当前这次」请求可以收掉 loading，
    // 否则被 abort 的旧请求会在新请求返回前把骨架屏提前撤掉，闪一下空态
    if (requestController === controller) loading.value = false
  }
}

const fetchCategories = async () => {
  const data = await listCatalogCategories()
  const list = Array.isArray(data) ? data.filter(Boolean) : []
  categories.value = ['全部', ...list]
}

const loadPage = async () => {
  // 分类和商品互不依赖：分类接口挂了也得能看药，商品接口挂了也得能切分类，
  // 所以用 allSettled 分别兜底，而不是 Promise.all 一失败就整页报错
  const [categoryResult] = await Promise.allSettled([fetchCategories(), fetchProducts()])
  if (categoryResult.status === 'rejected') {
    categories.value = ['全部'] // 分类降级为只有「全部」，不阻塞药品展示
  }
}

const applySearch = () => {
  if (searchTimer) {
    clearTimeout(searchTimer)
    searchTimer = 0
  }
  fetchProducts()
}

// 输入即搜，但 300ms 内只认最后一次；回车则跳过等待，立即搜
const onKeywordInput = () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    searchTimer = 0
    fetchProducts()
  }, SEARCH_DEBOUNCE)
}

const clearKeyword = () => {
  keyword.value = ''
  applySearch()
}

const selectCategory = (category) => {
  if (activeCategory.value === category) return
  activeCategory.value = category
  fetchProducts() // 点分类是一次性动作，不用防抖，立刻给反馈
}

const resetFilters = () => {
  keyword.value = ''
  activeCategory.value = '全部'
  applySearch()
}

// 游客也能逛，但加购要登录：后端 /api/cart 对未登录返回 401，
// 这里提前拦住并弹登录框，比让请求失败、再由拦截器清登录态体面得多
const handleAdd = async (product) => {
  if (!product || Number(product.stock) <= 0) return

  if (!auth.isLoggedIn) {
    auth.isLoginModalOpen = true
    showToast('登录后才能加入购物车')
    return
  }

  if (addingId.value) return // 已有加购请求在飞，避免连点重复加购
  addingId.value = product.id
  try {
    await cart.add(product.id, 1)
    showToast({type: 'success', message: '已加入购物车'})
  } catch (e) {
    showToast({type: 'fail', message: (e && e.message) || '加入购物车失败'})
  } finally {
    addingId.value = ''
  }
}

// 浮标上的数量：只同步角标，不 await、不阻塞列表渲染
const syncCartCount = () => {
  if (!auth.isLoggedIn) return
  cart.fetchCart()
}

const goCart = () => {
  router.push('/cart')
}

onMounted(() => {
  loadPage()
  syncCartCount()
})

// 页面被 KeepAlive 缓存：从详情页加购回来时角标要是最新的，
// 但列表不重新请求，这样筛选条件和滚动位置都还在
let activatedOnce = false
onActivated(() => {
  if (!activatedOnce) {
    activatedOnce = true // 首次进入由 onMounted 负责，避免重复请求
    return
  }
  syncCartCount()
})

onBeforeUnmount(() => {
  if (searchTimer) clearTimeout(searchTimer)
  if (requestController) requestController.abort()
})
</script>

<template>
  <div class="drugs-page">
    <Navbar/>

    <main class="page-body">
      <PageBar
          class="drugs-bar"
          title="药品广场"
          subtitle="不登录也能逛；加购需要登录"
          back-to="/"
      >
        <template #right>
          <span class="head-note" aria-hidden="true">公开目录 · 只读</span>
        </template>
      </PageBar>

      <section class="toolbar" aria-label="筛选药品">
        <div class="search-box">
          <Search :size="18" class="search-icon"/>
          <input
              v-model="keyword"
              class="search-input"
              type="text"
              placeholder="搜药名、通用名或适应症"
              enterkeyhint="search"
              aria-label="搜索药品"
              @input="onKeywordInput"
              @keydown.enter.prevent="applySearch"
          />
          <button
              v-if="keyword"
              type="button"
              class="clear-input"
              aria-label="清空关键词"
              @click="clearKeyword"
          >
            <X :size="16"/>
          </button>
        </div>

        <div class="chips">
          <button
              v-for="category in categories"
              :key="category"
              type="button"
              class="chip"
              :class="{ active: activeCategory === category }"
              @click="selectCategory(category)"
          >
            {{ category }}
          </button>
        </div>
      </section>

      <!-- 骨架屏占位卡 ≥ 6：首屏就有稳定结构，避免「先白屏再突然长出一堆卡」 -->
      <section v-if="loading" class="waterfall" aria-busy="true" aria-label="正在加载药品">
        <div v-for="index in 8" :key="index" class="skeleton-card" aria-hidden="true">
          <div class="skeleton-thumb"></div>
          <div class="skeleton-line w-80"></div>
          <div class="skeleton-line w-60"></div>
          <div class="skeleton-line w-40"></div>
        </div>
      </section>

      <PanelCard
          v-else-if="error"
          class="error-panel"
          :error="error"
          @retry="fetchProducts"
      />

      <section v-else-if="products.length === 0" class="state-card">
        <div class="state-icon">
          <Search :size="28"/>
        </div>
        <h3>{{ hasFilter ? '没有找到相关药品' : '药品目录还是空的' }}</h3>
        <p>{{ hasFilter ? '换个关键词试试，或者清空筛选看看全部药品。' : '后台还没上架药品，稍后再来看看。' }}</p>
        <!-- 空结果一律给「清空筛选」出口：没有筛选条件时它等价于重新拉一次，不至于卡在死路 -->
        <button type="button" class="primary-btn" @click="resetFilters">
          <RotateCcw :size="16"/>
          清空筛选
        </button>
      </section>

      <section v-else class="waterfall" aria-label="药品列表">
        <ProductCard
            v-for="product in products"
            :key="product.id"
            variant="shop"
            :item="product"
            :adding="addingId === product.id"
            @add="handleAdd"
        />
      </section>
    </main>

    <!-- 购物车浮标：右下角已被全局「返回顶部」和「MVP 导览」两个圆钮占住，
         放左下角才不会三个浮标叠一起；手机上抬到 76px 给底部手势区让位 -->
    <button type="button" class="cart-fab" aria-label="打开购物车" title="购物车" @click="goCart">
      <ShoppingCart :size="22"/>
      <span v-if="cart.totalCount > 0" class="cart-badge">
        {{ cart.totalCount > 99 ? '99+' : cart.totalCount }}
      </span>
    </button>
  </div>
</template>

<style scoped lang="scss">
.drugs-page {
  position: relative;
  min-height: 100vh;
  background: #f7f8fa;
  padding-top: 64px; // Navbar 是 fixed 的，页面自己让出高度
  padding-bottom: 88px; // 给左下角购物车浮标留出空间，滚到底时最后一行不被盖住
  color: #374151;

  .page-body {
    max-width: 1280px;
    margin: 0 auto;
    padding: 20px 24px 8px;
    min-width: 0;
  }

  .drugs-bar {
    margin-bottom: 14px;

    .head-note {
      flex: none;
      padding: 3px 10px;
      border: 1px dashed #fecaca;
      border-radius: 999px;
      color: #b91c1c;
      font-size: 11px;
      white-space: nowrap;
    }
  }

  .toolbar {
    padding: 14px;
    margin-bottom: 16px;
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 14px;
  }

  .search-box {
    display: flex;
    align-items: center;
    gap: 8px;
    height: 44px; // 手机端点按区够高，也避免 iOS 聚焦时页面缩放
    padding: 0 12px;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    transition: border-color 0.16s ease, box-shadow 0.16s ease, background-color 0.16s ease;

    &:focus-within {
      background: #fff;
      border-color: #fca5a5;
      box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.08);
    }

    .search-icon {
      flex: none;
      color: #9ca3af;
    }

    .search-input {
      flex: 1;
      min-width: 0;
      height: 100%;
      border: none;
      outline: none;
      background: transparent;
      font-size: 14px;
      color: #374151;

      &::placeholder {
        color: #9ca3af;
      }
    }

    .clear-input {
      display: grid;
      place-items: center;
      flex: none;
      width: 28px;
      height: 28px;
      border: none;
      border-radius: 50%;
      background: transparent;
      color: #9ca3af;
      cursor: pointer;
      transition: background-color 0.16s ease, color 0.16s ease;

      &:hover {
        background: #f3f4f6;
        color: #4b5563;
      }
    }
  }

  .chips {
    display: flex;
    flex-wrap: wrap; // 换行而不是横向滚动，页面永远不会多出一条横向滚动条
    gap: 8px;
    margin-top: 12px;
  }

  .chip {
    min-height: 34px;
    padding: 0 14px;
    border: 1px solid #e5e7eb;
    border-radius: 999px;
    background: #fff;
    color: #4b5563;
    font-size: 13px;
    white-space: nowrap;
    cursor: pointer;
    transition: background-color 0.16s ease, border-color 0.16s ease, color 0.16s ease;

    &:hover {
      border-color: #fca5a5;
      color: #dc2626;
    }

    &.active {
      background: #fef2f2;
      border-color: #fca5a5;
      color: #b91c1c;
      font-weight: 600;
    }
  }

  /* CSS columns 才是真瀑布流：每列各自往下排，卡片高度由内容决定 */
  .waterfall {
    column-count: 4;
    column-gap: 16px;

    > * {
      width: 100%;
      margin: 0 0 16px;
      break-inside: avoid; // 关键：不让一张卡被拆到两列
      -webkit-column-break-inside: avoid;
      page-break-inside: avoid;
    }
  }

  .skeleton-card {
    overflow: hidden;
    padding-bottom: 14px;
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 14px;
  }

  .skeleton-thumb {
    width: 100%;
    aspect-ratio: 4 / 3; // 和真实卡片同比例，加载完成时不会跳一下
    background: linear-gradient(90deg, #f3f4f6, #e9ebee, #f3f4f6);
    background-size: 200% 100%;
    animation: shimmer 1.4s infinite;
  }

  .skeleton-line {
    height: 12px;
    margin: 10px 12px 0;
    border-radius: 6px;
    background: linear-gradient(90deg, #f3f4f6, #e9ebee, #f3f4f6);
    background-size: 200% 100%;
    animation: shimmer 1.4s infinite;

    &.w-80 {
      width: 80%;
    }

    &.w-60 {
      width: 60%;
    }

    &.w-40 {
      width: 40%;
    }
  }

  .error-panel {
    margin-top: 8px;
  }

  .state-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    padding: 48px 20px;
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 14px;
    text-align: center;

    .state-icon {
      display: grid;
      place-items: center;
      width: 64px;
      height: 64px;
      margin-bottom: 4px;
      border-radius: 50%;
      background: #fef2f2;
      color: #ef4444;
    }

    h3 {
      margin: 0;
      font-size: 16px;
      font-weight: 600;
      color: #111827;
    }

    p {
      margin: 0;
      max-width: 420px;
      color: #6b7280;
      font-size: 13px;
      line-height: 1.7;
      overflow-wrap: anywhere;
    }
  }

  .primary-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    min-height: 40px;
    margin-top: 8px;
    padding: 0 18px;
    border: none;
    border-radius: 999px;
    background: #ef4444;
    color: #fff;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: background-color 0.16s ease, transform 0.16s ease;

    &:hover {
      background: #dc2626;
    }

    &:active {
      transform: scale(0.98);
    }
  }

  .cart-fab {
    position: fixed;
    left: 20px;
    bottom: 20px;
    z-index: 900;
    display: grid;
    place-items: center;
    width: 52px;
    height: 52px;
    border: none;
    border-radius: 50%;
    background: #ef4444;
    color: #fff;
    cursor: pointer;
    box-shadow: 0 10px 24px -10px rgba(239, 68, 68, 0.75);
    transition: background-color 0.16s ease, transform 0.16s ease;

    &:hover {
      background: #dc2626;
      transform: translateY(-2px);
    }

    &:active {
      transform: scale(0.96);
    }

    .cart-badge {
      position: absolute;
      top: -4px;
      right: -4px;
      display: grid;
      place-items: center;
      min-width: 20px;
      height: 20px;
      padding: 0 5px;
      border: 2px solid #fff;
      border-radius: 999px;
      background: #fbbf24;
      color: #fff;
      font-size: 11px;
      font-weight: 700;
      line-height: 1;
    }
  }
}

@keyframes shimmer {
  from {
    background-position: 200% 0;
  }
  to {
    background-position: -200% 0;
  }
}

/* 平板：3 列，卡片不会被挤成细长条 */
@media (max-width: 1100px) {
  .drugs-page .waterfall {
    column-count: 3;
  }
}

@media (max-width: 768px) {
  .drugs-page {
    padding-top: 60px; // 移动端顶栏视觉高度按 60px 留白
    padding-bottom: 132px; // 浮标抬高到 76px 后仍要留够空间，最后一行不会被挡住

    .page-body {
      padding: 14px 12px 4px;
    }

    .page-head {
      align-items: flex-start;

      h1 {
        font-size: 19px;
      }

      p {
        font-size: 12px;
      }

      .head-note {
        display: none; // 小屏顶部空间紧张，说明文字已经讲清楚了
      }
    }

    .toolbar {
      padding: 12px;
      border-radius: 12px;
    }

    .chip {
      min-height: 40px; // 手机端点按区不小于 40px
      padding: 0 13px;
      font-size: 12px;
    }

    .waterfall {
      column-count: 2;
      column-gap: 10px;

      > * {
        margin-bottom: 10px;
      }
    }

    .cart-fab {
      left: 14px;
      bottom: calc(76px + env(safe-area-inset-bottom, 0px));
      width: 48px;
      height: 48px;
    }

    .state-card {
      padding: 40px 16px;
    }
  }
}
</style>
