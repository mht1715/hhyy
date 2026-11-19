<script setup>
// KeepAlive 依赖组件名（App.vue 的 CACHED 白名单按 name 匹配）
defineOptions({name: 'OrderView'})

/**
 * 我的订单（独立页）。
 *
 * 订单卡本身复用 components/order/OrderCard.vue —— 患者工作台、管理员订单管理
 * 用的是同一个组件，状态文案 / 图片兜底 / 点击进详情的行为只有一份实现。
 */
import {computed, onActivated, onMounted, ref} from 'vue'
import {useRouter} from 'vue-router'
import {ArrowLeft} from 'lucide-vue-next'
import {showToast} from 'vant'
import {getMyOrdersApi} from '../api/order'
import OrderCard from '../components/order/OrderCard.vue'
import {ORDER_FILTERS, normalizeOrderStatus} from '../utils/orderStatus'
import {goBackOr} from '../utils/nav'

const router = useRouter()
const orders = ref([])
const loading = ref(true)
const errorText = ref('')
const activeTab = ref('all')

const TABS = ORDER_FILTERS

const filteredOrders = computed(() => {
  if (activeTab.value === 'all') return orders.value
  return orders.value.filter((o) => normalizeOrderStatus(o.status) === activeTab.value)
})

const counts = computed(() => {
  const result = {}
  orders.value.forEach((order) => {
    const key = normalizeOrderStatus(order.status)
    result[key] = (result[key] || 0) + 1
  })
  return result
})

const loadOrders = async () => {
  loading.value = true
  errorText.value = ''
  try {
    const data = await getMyOrdersApi()
    orders.value = Array.isArray(data) ? data : []
  } catch (e) {
    errorText.value = '订单加载失败，请稍后重试'
    showToast('获取订单失败')
  } finally {
    loading.value = false
  }
}

const goDetail = (order) => {
  if (order && order.id) router.push(`/orders/${order.id}`)
}

onMounted(loadOrders)

// 从订单详情返回时状态可能已经变了（取消 / 收货），重新拉一次
let activatedOnce = false
onActivated(() => {
  if (!activatedOnce) {
    activatedOnce = true
    return
  }
  loadOrders()
})
</script>

<template>
  <div class="order-page">
    <div class="nav-bar">
      <button type="button" class="back-btn" aria-label="返回上一页" @click="goBackOr(router, '/patient')">
        <ArrowLeft :size="22"/>
      </button>
      <div class="title">我的订单</div>
    </div>

    <van-tabs v-model:active="activeTab" sticky offset-top="46" color="#ef4444" title-active-color="#ef4444">
      <van-tab v-for="tab in TABS" :key="tab.key" :title="tab.label" :name="tab.key">
        <template v-if="tab.key !== 'all' && counts[tab.key]" #title>
          {{ tab.label }}
          <span class="tab-count">{{ counts[tab.key] }}</span>
        </template>
      </van-tab>
    </van-tabs>

    <div class="order-list">
      <div v-if="loading" class="state-box">
        <van-loading type="dots" color="#ef4444"/>
        <span>正在加载订单…</span>
      </div>

      <div v-else-if="errorText" class="state-box">
        <span>{{ errorText }}</span>
        <button type="button" class="retry-btn" @click="loadOrders">重试</button>
      </div>

      <van-empty v-else-if="filteredOrders.length === 0" description="暂无相关订单"/>

      <template v-else>
        <OrderCard
            v-for="order in filteredOrders"
            :key="order.id"
            :order="order"
            @open="goDetail"
        />
      </template>
    </div>
  </div>
</template>

<style scoped lang="scss">
.order-page {
  min-height: 100vh;
  background: #f7f8fa;
  padding-top: 46px;

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
    padding: 0 12px;

    .back-btn {
      display: grid;
      place-items: center;
      width: 32px;
      height: 32px;
      padding: 0;
      border: none;
      background: transparent;
      color: #4b5563;
      cursor: pointer;
    }

    .title {
      flex: 1;
      text-align: center;
      font-size: 16px;
      font-weight: 600;
      margin-right: 32px;
    }
  }

  .tab-count {
    margin-left: 2px;
    font-size: 11px;
    color: #dc2626;
  }

  .order-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
    max-width: 820px;
    margin: 0 auto;
    padding: 16px;
    padding-bottom: calc(24px + env(safe-area-inset-bottom));
  }

  .state-box {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    min-height: 200px;
    font-size: 13px;
    color: #6b7280;

    .retry-btn {
      padding: 3px 12px;
      border: 1px solid #fecaca;
      border-radius: 6px;
      background: #fff;
      color: #b91c1c;
      font-size: 12px;
      cursor: pointer;
    }
  }

  @media (max-width: 768px) {
    .order-list {
      padding: 12px;
    }
  }
}
</style>
