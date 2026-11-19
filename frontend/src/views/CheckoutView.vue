<script setup>
import {ref, computed, onMounted} from 'vue'
import {useRouter, useRoute} from 'vue-router'
import {useCartStore} from '../store/cart'
import {useAuthStore} from '../store/auth'
import {showToast} from 'vant'
import {ArrowLeft, MapPin} from 'lucide-vue-next'
import {checkoutApi} from '../api/order' // 引入支付 API
import {goBackOr} from '../utils/nav'
import {resolveHomePath} from '../utils/permission'

const router = useRouter()
const route = useRoute()
const cartStore = useCartStore()
const auth = useAuthStore()

const payStatus = ref('unpaid') // unpaid | paying | success
const orderNo = ref('')
const paidAmount = ref(0)

// 判断是否为立即购买模式
const isDirectBuy = route.query.mode === 'direct'

// 计算当前要结算的商品列表
const checkoutItems = computed(() => {
  if (isDirectBuy) {
    const directItem = JSON.parse(sessionStorage.getItem('direct_buy_item') || 'null')
    return directItem ? [directItem] : []
  } else {
    // 购物车模式，只展示勾选的
    const ids = JSON.parse(sessionStorage.getItem('checkout_items') || '[]')
    return cartStore.items.filter(item => ids.includes(item.id))
  }
})

// 计算总价
const totalPrice = computed(() => {
  return checkoutItems.value.reduce((sum, item) => sum + item.price * item.quantity, 0)
})

const address = {
  name: '张药师',
  phone: '138****8888',
  detail: '广西壮族自治区南宁市青秀区民族大道 123 号 花红药业大厦 8 楼'
}

// 真实发起支付
const handlePay = async () => {
  if (checkoutItems.value.length === 0) return
  payStatus.value = 'paying'

  try {
    let payload = {}
    if (isDirectBuy) {
      // 立即购买传商品列表
      payload.items = checkoutItems.value.map(i => ({product_id: i.product_id, quantity: i.quantity}))
    }
    // 购物车模式不传 items，后端自动读购物车

    const res = await checkoutApi(payload)

    // 支付成功逻辑
    paidAmount.value = totalPrice.value
    orderNo.value = res.order_id
    payStatus.value = 'success'

    // 清理本地缓存和购物车状态
    sessionStorage.removeItem('direct_buy_item')
    sessionStorage.removeItem('checkout_items')
    await cartStore.fetchCart() // 刷新购物车

    // 延迟跳回「我的订单」：患者直接回工作台的订单 Tab，
    // 工作台是 KeepAlive 缓存的，onActivated 里会重新拉一次统计与订单，
    // 所以「下完单回来数字没变」的问题在这里和 PatientView 两边一起兜住
    window.setTimeout(() => {
      router.replace(afterPaidTarget.value)
    }, 2200)

  } catch (e) {
    payStatus.value = 'unpaid'
    // 接口异常在拦截器统一提示了，这里可以不写
  }
}

// 付款成功后去哪：患者回工作台订单 Tab，其它角色回「我的订单」
const afterPaidTarget = computed(() => (
    auth.role === 'patient'
        ? {path: '/patient', query: {tab: 'orders'}}
        : {path: '/orders'}
))

const goHome = () => router.push(resolveHomePath(auth.role))

onMounted(() => {
  // 如果是购物车模式，刷新一下购物车数据防丢失
  if (!isDirectBuy) {
    cartStore.fetchCart()
  }
})
</script>

<template>
  <div class="checkout-page">
    <div class="nav-bar">
      <div class="back-btn" @click="goBackOr(router, '/cart')">
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
        <van-empty v-if="checkoutItems.length === 0" description="没有要结算的商品">
          <van-button round type="danger" @click="router.push('/')">去逛逛</van-button>
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
            <div class="item" v-for="item in checkoutItems" :key="item.id">
              <img :src="item.image_url || 'https://fastly.jsdelivr.net/npm/@vant/assets/cat.jpeg'" class="thumb"/>
              <div class="info">
                <div class="name">{{ item.name }}</div>
                <div class="spec">{{ item.spec }}</div>
              </div>
              <div class="price-info">
                <div class="price">¥{{ item.price }}</div>
                <div class="quantity">x{{ item.quantity }}</div>
              </div>
            </div>
          </div>

          <van-cell-group inset title="费用明细" class="fee-group">
            <van-cell title="商品总额" :value="`¥${totalPrice.toFixed(2)}`"/>
            <van-cell title="运费" value="免运费"/>
          </van-cell-group>
        </template>
      </div>

      <!-- 底部支付栏 -->
      <div class="bottom-pay-bar" v-if="checkoutItems.length > 0">
        <div class="total-info">
          <span class="label">合计：</span>
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