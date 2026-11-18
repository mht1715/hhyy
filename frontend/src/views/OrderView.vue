<script setup>
import {ref, onMounted, computed} from 'vue'
import {useRouter} from 'vue-router'
import {getMyOrdersApi} from '../api/order'
import {ArrowLeft, Copy} from 'lucide-vue-next'
import {showToast} from 'vant'
import OrderItem from '../components/order/OrderItem.vue'

const router = useRouter()
const orders = ref([])
const loading = ref(true)
const activeTab = ref('all')

// 兼容大小写
const statusMap = {
  'PENDING': {text: '待付款', color: '#ff976a'},
  'PAID': {text: '待发货', color: '#ee0a24'},
  'SHIPPED': {text: '待收货', color: '#1989fa'},
  'COMPLETED': {text: '已完成', color: '#07c160'},
  'CANCELLED': {text: '已取消', color: '#969799'}
}

const getStatus = (status) => {
  if (!status) return {text: '未知', color: '#999'}
  return statusMap[status.toUpperCase()] || {text: status, color: '#999'}
}

const tabs = [
  {name: 'all', title: '全部'},
  {name: 'PAID', title: '待发货'},
  {name: 'SHIPPED', title: '待收货'},
  {name: 'COMPLETED', title: '已完成'}
]

const filteredOrders = computed(() => {
  if (activeTab.value === 'all') return orders.value
  return orders.value.filter(o => o.status.toUpperCase() === activeTab.value)
})

const loadOrders = async () => {
  loading.value = true
  try {
    orders.value = await getMyOrdersApi()
  } catch (e) {
    showToast('获取订单失败')
  } finally {
    loading.value = false
  }
}

// 复制订单号
const copyOrderId = (id) => {
  navigator.clipboard.writeText(id).then(() => {
    showToast('订单号已复制')
  }).catch(() => {
    showToast('复制失败')
  })
}

onMounted(loadOrders)
</script>

<template>
  <div class="order-page">
    <div class="nav-bar">
      <div class="back-btn" @click="router.back()">
        <ArrowLeft :size="24"/>
      </div>
      <div class="title">我的订单</div>
    </div>

    <van-tabs v-model:active="activeTab" sticky offset-top="46" color="#ef4444" title-active-color="#ef4444">
      <van-tab v-for="tab in tabs" :key="tab.name" :title="tab.title" :name="tab.name"/>
    </van-tabs>

    <div class="order-list">
      <van-empty v-if="!loading && filteredOrders.length === 0" description="暂无相关订单"/>

      <div class="order-card" v-for="order in filteredOrders" :key="order.id">
        <div class="order-header">
          <div class="order-no">
            <span>订单号：{{ order.id }}</span>
            <Copy :size="14" class="copy-icon" @click="copyOrderId(order.id)"/>
          </div>
          <span class="order-status" :style="{ color: getStatus(order.status).color }">
            {{ getStatus(order.status).text }}
          </span>
        </div>

        <div class="order-items">
          <OrderItem v-for="item in order.items" :key="item.product_id" :item="item"/>
        </div>

        <div class="order-footer">
          <div class="total-info">
            共 {{ order.items.length }} 件商品，实付：<span class="total">¥{{ order.total_amount.toFixed(2) }}</span>
          </div>
          <van-button size="small" plain type="danger" round @click="router.push(`/orders/${order.id}`)">
            查看详情
          </van-button>
        </div>
      </div>
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
    padding: 0 16px;

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

  .order-list {
    max-width: 800px;
    margin: 0 auto;
    padding: 16px;

    .order-card {
      background: #fff;
      border-radius: 12px;
      margin-bottom: 16px;
      overflow: hidden;
      padding-bottom: 12px;

      .order-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px 16px;
        background: #f9f9f9;
        font-size: 13px;
        color: #666;

        .order-no {
          display: flex;
          align-items: center;
          gap: 6px;

          .copy-icon {
            cursor: pointer;

            &:hover {
              color: #ef4444;
            }
          }
        }

        .order-status {
          font-weight: bold;
        }
      }

      .order-items {
        padding: 0 16px;
      }

      .order-footer {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px 16px;
        border-top: 1px solid #f3f4f6;
        margin-top: 12px;
        font-size: 13px;
        color: #333;

        .total {
          font-size: 18px;
          font-weight: bold;
          color: #ee0a24;
        }
      }
    }
  }
}
</style>