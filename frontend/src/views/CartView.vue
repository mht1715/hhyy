<script setup>
/**
 * 购物车页。
 *
 * 之前只有详情页 / 列表页弹出的购物车小浮层，没有独立页面：
 * 商品一多，浮层里既看不全也不好改数量。这里补一个正式页面，
 * 和「药品广场」配对，形成 逛 → 加购 → 结算 的完整链路。
 *
 * 几条刻意的处理：
 * 1. 数量改动先写本地、300ms 防抖后再打接口——步进器长按会连发十几次，
 *    直接发请求等于自己 DDoS 自己。
 * 2. 列表区自己滚动（max-height: 62vh），结算条吸底，商品再多也不会把
 *    「合计 / 去结算」挤出屏幕。
 * 3. 未登录不请求 /api/cart（后端会 401），直接给登录引导。
 */
import {computed, onActivated, onBeforeUnmount, onMounted, ref, watch} from 'vue'
import {useRouter} from 'vue-router'
import {ArrowRight, Lock, ShoppingCart} from 'lucide-vue-next'
import {showConfirmDialog, showToast} from 'vant'
import Navbar from '../components/Navbar.vue'
import PageBar from '../components/common/PageBar.vue'
import CartItem from '../components/cart/CartItem.vue'
import {useAuthStore} from '../store/auth'
import {useCartStore} from '../store/cart'
import {writeCheckoutItems} from '../utils/checkout'

// 与 App.vue 的 KeepAlive CACHED 列表保持一致，否则返回时会重新挂载、丢状态
defineOptions({name: 'CartView'})

const router = useRouter()
const auth = useAuthStore()
const cart = useCartStore()

const loading = ref(true)

const formatMoney = (value) => (Number(value) || 0).toFixed(2)
const itemSubtotal = (item) => (Number(item.price) || 0) * (Number(item.quantity) || 0)

// 合计自己算：数量是本地先变的，store 里的 totalPrice 要等接口回调才更新，
// 直接用会慢半拍（用户点了 + 数字却不动，很像卡住）
const itemCount = computed(() => cart.items.reduce((sum, item) => sum + (Number(item.quantity) || 0), 0))
const totalAmount = computed(() => cart.items.reduce((sum, item) => sum + itemSubtotal(item), 0))

/* ---------------- 数量同步（300ms 防抖） ---------------- */

// 待同步队列：商品 id -> {timer, quantity}
const pendingSync = new Map()

const queueQuantitySync = (item, quantity) => {
  const previous = pendingSync.get(item.id)
  if (previous) clearTimeout(previous.timer)

  const timer = window.setTimeout(() => {
    pendingSync.delete(item.id)
    // updateQuantity 内部先本地更新再静默发请求，失败会自己重新拉取，不会把 UI 卡住
    cart.updateQuantity(item.id, quantity)
  }, 300)

  pendingSync.set(item.id, {timer, quantity})
}

const handleQuantityInput = (item, value) => {
  // van-stepper 的输入框可能给出字符串，先归一化成 >=1 的整数再写回 store，
  // 否则 store 里 totalCount 的累加会变成字符串拼接（1 + '2' = '12'）
  const quantity = Math.max(1, Math.floor(Number(value) || 1))
  item.quantity = quantity
  queueQuantitySync(item, quantity)
}

const cancelPendingSync = (itemId) => {
  const pending = pendingSync.get(itemId)
  if (!pending) return
  clearTimeout(pending.timer)
  pendingSync.delete(itemId)
}

const cancelAllPendingSync = () => {
  pendingSync.forEach((pending) => clearTimeout(pending.timer))
  pendingSync.clear()
}

// 离开页面前把还没发出去的数量补发掉，否则「改完数量立刻去结算」会按旧数量下单
const flushPendingSync = async () => {
  const entries = Array.from(pendingSync.entries())
  pendingSync.clear()
  await Promise.allSettled(entries.map(([itemId, pending]) => {
    clearTimeout(pending.timer)
    return cart.updateQuantity(itemId, pending.quantity)
  }))
}

/* ---------------- 数据加载 ---------------- */

const loadCart = async () => {
  if (!auth.isLoggedIn) {
    loading.value = false
    return
  }
  loading.value = true
  try {
    await cart.fetchCart()
  } finally {
    loading.value = false
  }
}

/* ---------------- 交互 ---------------- */

const goDrugs = () => router.push('/drugs')

const handleRemove = async (item) => {
  try {
    await showConfirmDialog({
      title: '移出购物车',
      message: `确定把「${item.name}」移出购物车吗？`,
      confirmButtonColor: '#dc2626'
    })
  } catch (e) {
    return // 用户点了取消，什么都不做
  }

  cancelPendingSync(item.id) // 先撤掉待同步的数量，避免删除后又被写回去
  try {
    await cart.remove(item.id)
    showToast({type: 'success', message: '已移出购物车'})
  } catch (e) {
    showToast({type: 'fail', message: (e && e.message) || '删除失败'})
  }
}

const handleClear = async () => {
  try {
    await showConfirmDialog({
      title: '清空购物车',
      message: '清空后无法恢复，确定要清空吗？',
      confirmButtonColor: '#dc2626'
    })
  } catch (e) {
    return
  }

  cancelAllPendingSync()
  try {
    await cart.clear()
    showToast({type: 'success', message: '购物车已清空'})
  } catch (e) {
    showToast({type: 'fail', message: (e && e.message) || '清空失败'})
  }
}

const handleCheckout = async () => {
  if (cart.items.length === 0) return
  await flushPendingSync() // 结算前把数量同步补齐
  // 结算清单以快照形式交给结算页（utils/checkout 会顺手清掉「立即购买」的残留）
  writeCheckoutItems(cart.items)
  router.push('/checkout')
}

const openLogin = () => {
  auth.isLoginModalOpen = true
}

// 登录弹窗里选完身份后不跳页，这里监听登录态自动把购物车拉出来
watch(() => auth.isLoggedIn, (loggedIn) => {
  if (loggedIn) {
    loadCart()
  } else {
    cancelAllPendingSync()
    loading.value = false
  }
})

onMounted(loadCart)

// KeepAlive 缓存后再次进入：重新拉一次，保证在别的页面加购/下单后数量是对的
let activatedOnce = false
onActivated(() => {
  if (!activatedOnce) {
    activatedOnce = true // 首次进入已由 onMounted 请求过
    return
  }
  loadCart()
})

onBeforeUnmount(() => {
  // 组件真被销毁时把待同步的数量补发出去，不能让用户改的数量凭空消失
  flushPendingSync()
})
</script>

<template>
  <div class="cart-page">
    <Navbar/>

    <main class="page-body">
      <PageBar
          class="cart-bar"
          title="购物车"
          :subtitle="auth.isLoggedIn && cart.items.length
            ? `共 ${itemCount} 件商品，结算前请确认数量`
            : '加购的药品会保存在账号里，换设备也能看到'"
          back-to="/drugs"
      >
        <template #right>
          <button type="button" class="ghost-btn" @click="goDrugs">
            <ShoppingCart :size="15"/>
            继续逛逛
          </button>
        </template>
      </PageBar>

      <!-- 未登录：只给引导，不去请求必然 401 的 /api/cart -->
      <section v-if="!auth.isLoggedIn" class="state-card">
        <div class="state-icon">
          <Lock :size="28"/>
        </div>
        <h3>登录后才能使用购物车</h3>
        <p>购物车和订单都跟着账号走，登录后加的药才不会丢。</p>
        <button type="button" class="primary-btn" @click="openLogin">
          立即登录
        </button>
        <button type="button" class="link-btn" @click="goDrugs">先去药品广场逛逛</button>
      </section>

      <template v-else>
        <div v-if="loading" class="cart-skeleton" aria-busy="true" aria-label="正在加载购物车">
          <div v-for="index in 3" :key="index" class="skeleton-item" aria-hidden="true">
            <div class="skeleton-thumb"></div>
            <div class="skeleton-lines">
              <div class="skeleton-line w-70"></div>
              <div class="skeleton-line w-40"></div>
              <div class="skeleton-line w-55"></div>
            </div>
          </div>
        </div>

        <section v-else-if="cart.items.length === 0" class="state-card">
          <div class="state-icon">
            <ShoppingCart :size="30"/>
          </div>
          <h3>购物车是空的</h3>
          <p>去药品广场挑点常备药吧，加购后会出现在这里。</p>
          <button type="button" class="primary-btn" @click="goDrugs">
            去挑点药
            <ArrowRight :size="16"/>
          </button>
        </section>

        <template v-else>
          <!-- 列表自己滚：商品再多也撑不高整页，结算条才能一直吸在底部。
               单行统一用 CartItem（和详情页浮层、患者工作台是同一个组件） -->
          <div class="cart-list" aria-label="购物车商品">
            <CartItem
                v-for="item in cart.items"
                :key="item.id"
                :item="item"
                @change="handleQuantityInput"
                @remove="handleRemove"
            />
          </div>

          <!-- 吸底结算条：sticky 让它正常时位于内容末尾，内容变高时自动贴住视口底部 -->
          <div class="checkout-bar">
            <div class="total-box">
              <span class="total-label">合计（{{ itemCount }} 件）</span>
              <span class="total-amount">¥{{ formatMoney(totalAmount) }}</span>
            </div>
            <div class="bar-actions">
              <button type="button" class="bar-clear" @click="handleClear">清空</button>
              <button type="button" class="bar-pay" @click="handleCheckout">
                去结算
                <ArrowRight :size="16"/>
              </button>
            </div>
          </div>
        </template>
      </template>
    </main>
  </div>
</template>

<style scoped lang="scss">
.cart-page {
  min-height: 100vh;
  background: #f7f8fa;
  padding-top: 64px; // Navbar 固定 64px，页面让出高度
  padding-bottom: 24px;
  color: #374151;

  .page-body {
    max-width: 860px; // 购物车是单人清单，比广场窄一点更好读
    margin: 0 auto;
    padding: 20px 24px 8px;
    min-width: 0;
  }

  .cart-bar {
    margin-bottom: 16px;
  }

  .ghost-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    flex: none;
    min-height: 38px;
    padding: 0 14px;
    border: 1px solid #e5e7eb;
    border-radius: 999px;
    background: #fff;
    color: #4b5563;
    font-size: 13px;
    cursor: pointer;
    transition: border-color 0.16s ease, color 0.16s ease, background-color 0.16s ease;

    &:hover {
      border-color: #fca5a5;
      background: #fef2f2;
      color: #dc2626;
    }
  }

  .cart-list {
    margin: 0;
    padding: 0 16px;
    list-style: none;
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 14px;
    max-height: 62vh;
    overflow-y: auto;
    overscroll-behavior: contain; // 滚到底不要连带整页一起滚
    -webkit-overflow-scrolling: touch;
    // 自定义细滚动条：默认滚动条在浅色卡片上太抢眼
    scrollbar-width: thin;
    scrollbar-color: #e5e7eb transparent;

    &::-webkit-scrollbar {
      width: 6px;
    }

    &::-webkit-scrollbar-track {
      background: transparent;
    }

    &::-webkit-scrollbar-thumb {
      background: #e5e7eb;
      border-radius: 999px;

      &:hover {
        background: #d1d5db;
      }
    }
  }

  .cart-item {
    // 单行样式已收敛到 components/cart/CartItem.vue，这里不再维护
  }

  .checkout-bar {
    position: sticky;
    bottom: 0;
    z-index: 20;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
    margin-top: 12px;
    padding: 12px 16px calc(12px + env(safe-area-inset-bottom, 0px));
    background: rgba(255, 255, 255, 0.96);
    backdrop-filter: blur(10px);
    border: 1px solid #e5e7eb;
    border-radius: 14px;
    box-shadow: 0 -8px 24px -20px rgba(17, 24, 39, 0.6);

    .total-box {
      display: flex;
      align-items: baseline;
      gap: 8px;
      min-width: 0;
    }

    .total-label {
      color: #6b7280;
      font-size: 13px;
      white-space: nowrap;
    }

    .total-amount {
      color: #dc2626;
      font-size: 22px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }

    .bar-actions {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-left: auto;
    }

    .bar-clear {
      min-height: 40px;
      padding: 0 16px;
      border: 1px solid #e5e7eb;
      border-radius: 999px;
      background: #fff;
      color: #6b7280;
      font-size: 13px;
      cursor: pointer;
      transition: border-color 0.16s ease, color 0.16s ease, background-color 0.16s ease;

      &:hover {
        border-color: #fecaca;
        background: #fef2f2;
        color: #b91c1c;
      }
    }

    .bar-pay {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 4px;
      min-height: 42px;
      padding: 0 22px;
      border: none;
      border-radius: 999px;
      background: #ef4444;
      color: #fff;
      font-size: 15px;
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
  }

  /* 未登录 / 空态共用同一张卡，视觉不必两套 */
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
    min-height: 42px;
    margin-top: 8px;
    padding: 0 20px;
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

  .link-btn {
    padding: 4px 8px;
    border: none;
    background: transparent;
    color: #6b7280;
    font-size: 13px;
    text-decoration: underline;
    cursor: pointer;
    transition: color 0.16s ease;

    &:hover {
      color: #dc2626;
    }
  }

  .cart-skeleton {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 8px 16px;
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 14px;
  }

  .skeleton-item {
    display: flex;
    gap: 12px;
    padding: 14px 0;
    border-bottom: 1px solid #f3f4f6;

    &:last-child {
      border-bottom: none;
    }
  }

  .skeleton-thumb {
    flex: none;
    width: 76px;
    height: 76px;
    border-radius: 10px;
    background: linear-gradient(90deg, #f3f4f6, #e9ebee, #f3f4f6);
    background-size: 200% 100%;
    animation: shimmer 1.4s infinite;
  }

  .skeleton-lines {
    flex: 1;
    min-width: 0;
    padding-top: 4px;
  }

  .skeleton-line {
    height: 12px;
    margin-bottom: 10px;
    border-radius: 6px;
    background: linear-gradient(90deg, #f3f4f6, #e9ebee, #f3f4f6);
    background-size: 200% 100%;
    animation: shimmer 1.4s infinite;

    &.w-70 {
      width: 70%;
    }

    &.w-55 {
      width: 55%;
    }

    &.w-40 {
      width: 40%;
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

@media (max-width: 768px) {
  .cart-page {
    padding-top: 60px; // 移动端顶栏留白
    padding-bottom: 16px;

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
    }

    .ghost-btn {
      min-height: 40px;
      padding: 0 12px;
      font-size: 12px;
    }

    .cart-list {
      padding: 0 12px;
      max-height: 62vh; // 手机上同样只让列表区滚，结算条始终在视口里
    }

    .cart-item {
      gap: 10px;
      padding: 12px 0;
    }

    .thumb-btn {
      width: 64px;
      height: 64px;
    }

    .item-name {
      font-size: 13px;
    }

    .item-foot {
      gap: 6px;
    }

    .subtotal {
      font-size: 11px;
    }

    .checkout-bar {
      gap: 8px;
      padding: 10px 12px calc(10px + env(safe-area-inset-bottom, 0px));
      border-radius: 12px;

      .total-amount {
        font-size: 19px;
      }

      .bar-actions {
        gap: 8px;
      }

      .bar-clear {
        min-height: 40px;
        padding: 0 14px;
      }

      .bar-pay {
        min-height: 42px;
        padding: 0 18px;
        font-size: 14px;
      }
    }

    .state-card {
      padding: 40px 16px;
    }
  }
}
</style>
