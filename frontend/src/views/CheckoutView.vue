<script setup>
/**
 * 确认订单 / 模拟支付。
 *
 * 结算清单现在统一走 utils/checkout.js 的快照：
 * 页面不再依赖「sessionStorage 里的 id + pinia 里已 fetch 的购物车」这两个东西同时成立，
 * 所以刷新、从工作台进来、从浮层勾选进来，看到的都是同一份清单。
 *
 * 下单时把清单显式提交（items + from_cart），而不是让后端自己读整车：
 * 浮层里勾了 2 件、车里还有 3 件时，只该结算并清掉那 2 件。
 */
import {computed, onMounted, ref} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import {useCartStore} from '../store/cart'
import {useAuthStore} from '../store/auth'
import {ArrowLeft, MapPin} from 'lucide-vue-next'
import {checkoutApi} from '../api/order'
import {goBackOr} from '../utils/nav'
import {imageUrl, onImageError} from '../utils/image'
import {
  clearCheckout,
  checkoutTotal,
  readCheckoutItems,
  readDirectItem,
  toCheckoutItem
} from '../utils/checkout'

const router = useRouter()
const route = useRoute()
const cartStore = useCartStore()
const auth = useAuthStore()

const payStatus = ref('unpaid') // unpaid | paying | success
const orderNo = ref('')
const paidAmount = ref(0)

// 结算清单（快照）+ 加载态：之前没有加载态，购物车还没回来就渲染「没有要结算的商品」
const selection = ref([])
const loading = ref(true)
const loadError = ref('')

const isDirectBuy = computed(() => route.query.mode === 'direct')
const checkoutItems = computed(() => selection.value)
const totalPrice = computed(() => checkoutTotal(selection.value))
const totalCount = computed(() => selection.value.reduce((sum, item) => sum + (Number(item.quantity) || 0), 0))

const address = {
  name: '张药师',
  phone: '138****8888',
  detail: '广西壮族自治区南宁市青秀区民族大道 123 号 花红药业大厦 8 楼'
}

/**
 * 清单与「最新购物车」对齐：清单里还留在车里的行，用车上最新的价格/数量，
 * 避免展示的金额和实际下单金额不一致；已经不是同一条行的，按清单原样展示。
 */
const mergeWithCart = (snapshot, cartRows) => {
  const byId = new Map(cartRows.filter((row) => row.id).map((row) => [row.id, row]))
  const byProduct = new Map(cartRows.map((row) => [row.product_id, row]))
  return snapshot.map((item) => byId.get(item.id) || byProduct.get(item.product_id) || item)
}

const loadSelection = async () => {
  loading.value = true
  loadError.value = ''
  try {
    if (isDirectBuy.value) {
      const item = readDirectItem()
      selection.value = item ? [item] : []
      if (!item) loadError.value = '没有找到要购买的商品，可能已经支付过了'
      return
    }

    const snapshot = readCheckoutItems()
    if (auth.isLoggedIn) {
      try {
        await cartStore.fetchCart()
      } catch (e) {
        // 拉不到购物车时，只要还有快照就能继续结算；两个都空才是真的没东西
        if (snapshot.length === 0) throw e
      }
    }
    const cartRows = cartStore.items.map(toCheckoutItem).filter(Boolean)
    selection.value = snapshot.length ? mergeWithCart(snapshot, cartRows) : cartRows
  } catch (e) {
    loadError.value = (e && e.message) || '结算清单加载失败'
  } finally {
    loading.value = false
  }
}

// 付款成功后去哪：患者回工作台订单 Tab，其它角色回「我的订单」
const afterPaidTarget = computed(() => (
    auth.role === 'patient'
        ? {path: '/patient', query: {tab: 'orders'}}
        : {path: '/orders'}
))

const handlePay = async () => {
  if (checkoutItems.value.length === 0) return
  payStatus.value = 'paying'

  try {
    // 两种模式都显式传 items：金额与件数以服务端重新读到的价格/库存为准
    const payload = {
      items: checkoutItems.value.map((item) => ({
        product_id: item.product_id,
        quantity: Number(item.quantity) || 1
      }))
    }
    // 购物车结算：让后端把结算过的行从购物车删掉（勾选结算是「真的只结算这些」）
    if (!isDirectBuy.value) payload.from_cart = true

    const res = await checkoutApi(payload)

    paidAmount.value = totalPrice.value
    orderNo.value = res.order_id
    payStatus.value = 'success'

    // 清单任务完成：两个 key 一起清，避免返回结算页把同一单再下一遍
    clearCheckout()
    // 不 await：刷新购物车不该拖住成功页的展示与跳转
    cartStore.fetchCart()

    // 延迟跳回订单：患者回工作台订单 Tab，工作台是 KeepAlive 缓存的，
    // onActivated 会重新拉统计与订单，所以「下完单回来数字没变」两边一起兜住
    window.setTimeout(() => {
      router.replace(afterPaidTarget.value)
    }, 2200)
  } catch (e) {
    payStatus.value = 'unpaid'
    // 接口异常在拦截器统一提示了，这里只把按钮解锁，别让人卡在「支付中」
  }
}

onMounted(loadSelection)
</script>

<template>
  <div class="checkout-page">
    <div class="nav-bar">
      <div class="back-btn" @click="goBackOr(router, isDirectBuy ? '/drugs' : '/cart')">
        <ArrowLeft :size="24"/>
      </div>
      <div class="title">{{ payStatus === 'success' ? '支付结果' : '确认订单' }}</div>
    </div>

    <!-- 支付成功状态 -->
    <div v-if="payStatus === 'success'" class="success-wrapper">
      <van-icon name="checked" color="#10b981" size="80"/>
      <h2 class="success-title">支付成功</h2>
      <p class="success-amount">¥{{ paidAmount.toFixed(2) }}</p>
      <p class="success-order">订单号：{{ orderNo }}</p>
      <p style="color: #999; font-size: 13px;">即将跳转{{ auth.role === 'patient' ? '工作台订单页' : '我的订单' }}...</p>

      <!-- 自动跳转之外给两个明确出口：等待 2 秒什么也不做也有人会以为卡住了 -->
      <div class="success-actions">
        <van-button round type="danger" @click="router.replace(afterPaidTarget)">查看订单</van-button>
        <van-button round plain type="danger" @click="router.replace('/drugs')">继续逛逛</van-button>
      </div>
    </div>

    <!-- 结算状态 -->
    <template v-else>
      <div class="content-wrapper">
        <div v-if="loading" class="checkout-state">
          <van-loading size="22px" vertical>正在准备结算清单…</van-loading>
        </div>

        <div v-else-if="loadError" class="checkout-state">
          <van-empty image="error" :description="loadError">
            <van-button round type="danger" @click="loadSelection">重新加载</van-button>
          </van-empty>
        </div>

        <van-empty v-else-if="checkoutItems.length === 0" description="没有要结算的商品">
          <p class="empty-hint">购物车可能是空的，或者商品已经被移除了。</p>
          <div class="empty-actions">
            <van-button round type="danger" @click="router.push('/cart')">去购物车看看</van-button>
            <van-button round plain type="danger" @click="router.push('/drugs')">继续逛逛</van-button>
          </div>
        </van-empty>

        <template v-else>
          <div class="address-card">
            <div class="icon-box">
              <MapPin :size="20" color="#ef4444"/>
            </div>
            <div class="address-info">
              <div class="user-info">
                <span class="name">{{ address.name }}</span>
                <span class="phone">{{ address.phone }}</span>
              </div>
              <div class="detail">{{ address.detail }}</div>
            </div>
          </div>

          <div class="order-items">
            <div class="item" v-for="item in checkoutItems" :key="item.id || item.product_id">
              <img class="thumb" :src="imageUrl(item.image_url)" :alt="item.name || '商品'"
                   loading="lazy" @error="onImageError"/>
              <div class="info">
                <div class="name">{{ item.name || '商品已下架' }}</div>
                <div class="spec">{{ item.spec }}</div>
              </div>
              <div class="price-info">
                <div class="price">¥{{ (Number(item.price) || 0).toFixed(2) }}</div>
                <div class="quantity">x{{ item.quantity }}</div>
              </div>
            </div>
          </div>

          <van-cell-group inset title="费用明细" class="fee-group">
            <van-cell title="商品总额" :value="`¥${totalPrice.toFixed(2)}`"/>
            <van-cell title="运费" value="免运费"/>
            <van-cell title="支付方式" value="模拟支付（不产生真实扣款）"/>
          </van-cell-group>
        </template>
      </div>

      <!-- 底部支付栏 -->
      <div class="bottom-pay-bar" v-if="checkoutItems.length > 0 && !loading">
        <div class="total-info">
          <span class="label">共 {{ totalCount }} 件 · 合计：</span>
          <span class="price">¥{{ totalPrice.toFixed(2) }}</span>
        </div>
        <van-button
            type="danger" round class="pay-btn"
            :loading="payStatus === 'paying'" loading-text="支付中..."
            @click="handlePay"
        >
          立即支付
        </van-button>
      </div>
    </template>
  </div>
</template>

<style scoped lang="scss">
/* 保留你之前的样式，无需大改 */
.checkout-page {
  min-height: 100vh;
  background: #f7f8fa;
  padding-top: 46px;
  padding-bottom: 80px;

  .nav-bar {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    z-index: 10;
    display: flex;
    align-items: center;
    background: #fff;
    height: 46px;
    padding: 0 16px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    max-width: 800px;
    margin: 0 auto;

    .back-btn {
      cursor: pointer;
    }

    .title {
      flex: 1;
      text-align: center;
      font-size: 16px;
      font-weight: 600;
      margin-right: 24px;
    }
  }

  .content-wrapper {
    max-width: 800px;
    margin: 0 auto;
    padding: 16px;
  }

  /* 加载 / 报错 / 空态：三者都用同一块居中的容器，
     避免「清单还没回来」和「真的没有商品」长得一模一样 */
  .checkout-state {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 46vh;

    .empty-hint {
      margin: -8px 0 16px;
      font-size: 13px;
      color: #9ca3af;
      text-align: center;
    }

    .empty-actions {
      display: flex;
      gap: 12px;
      justify-content: center;
      flex-wrap: wrap;
    }
  }

  .address-card {
    background: #fff;
    border-radius: 12px;
    padding: 16px;
    display: flex;
    gap: 12px;
    margin-bottom: 16px;
    position: relative;
    overflow: hidden;

    &::after {
      content: '';
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      height: 4px;
      background: repeating-linear-gradient(-45deg, #ef4444, #ef4444 10px, transparent 10px, transparent 20px);
      opacity: 0.5;
    }

    .address-info {
      flex: 1;

      .user-info {
        margin-bottom: 6px;

        .name {
          font-weight: 600;
          font-size: 15px;
          margin-right: 12px;
        }

        .phone {
          color: #666;
          font-size: 13px;
        }
      }

      .detail {
        font-size: 13px;
        color: #333;
        line-height: 1.5;
      }
    }
  }

  .order-items {
    background: #fff;
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 16px;

    .item {
      display: flex;
      gap: 12px;
      padding-bottom: 16px;
      margin-bottom: 16px;
      border-bottom: 1px solid #f3f4f6;

      &:last-child {
        padding-bottom: 0;
        margin-bottom: 0;
        border-bottom: none;
      }

      .thumb {
        width: 70px;
        height: 70px;
        object-fit: contain;
        background: #f9f9f9;
        border-radius: 8px;
      }

      .info {
        flex: 1;

        .name {
          font-size: 14px;
          font-weight: 600;
          color: #333;
          margin-bottom: 4px;
        }

        .spec {
          font-size: 12px;
          color: #999;
        }
      }

      .price-info {
        text-align: right;

        .price {
          font-size: 15px;
          font-weight: bold;
          color: #ee0a24;
        }

        .quantity {
          font-size: 12px;
          color: #999;
          margin-top: 4px;
        }
      }
    }
  }

  .fee-group {
    margin: 0;

    :deep(.van-cell-group__title) {
      padding-left: 4px;
    }
  }

  .bottom-pay-bar {
    position: fixed;
    bottom: 0;
    left: 0;
    width: 100%;
    background: #fff;
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 24px;
    padding-bottom: calc(12px + env(safe-area-inset-bottom));
    box-shadow: 0 -1px 3px rgba(0, 0, 0, 0.05);
    z-index: 99;
    @media (min-width: 768px) {
      max-width: 800px;
      left: 50%;
      transform: translateX(-50%);
      border-radius: 12px 12px 0 0;
    }

    .total-info {
      .label {
        font-size: 14px;
        color: #333;
      }

      .price {
        font-size: 22px;
        font-weight: bold;
        color: #ee0a24;
      }
    }

    .pay-btn {
      width: 140px;
      height: 40px;
      font-size: 15px;
      font-weight: 600;
    }
  }

  .success-wrapper {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 60px 24px;
    max-width: 400px;
    margin: 0 auto;
    animation: fade-in 0.5s ease;

    .success-title {
      font-size: 22px;
      font-weight: 600;
      color: #333;
      margin: 20px 0 10px;
    }

    .success-amount {
      font-size: 32px;
      font-weight: bold;
      color: #333;
      margin-bottom: 12px;
    }

    .success-order {
      font-size: 13px;
      color: #999;
      margin-bottom: 20px;
      background: #f3f4f6;
      padding: 6px 16px;
      border-radius: 16px;
    }

    .success-actions {
      display: flex;
      gap: 12px;
      margin-top: 8px;

      .van-button {
        min-width: 120px;
      }
    }
  }
}

@keyframes fade-in {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>