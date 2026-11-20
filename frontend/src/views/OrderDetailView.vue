<script setup>
import {ref, onMounted} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import {getOrderDetailApi, cancelOrderApi, receiveOrderApi, shipOrderApi} from '../api/order'
import {useAuthStore} from '../store/auth'
import {ArrowLeft, MapPin} from 'lucide-vue-next'
import {showToast, showConfirmDialog} from 'vant'
import OrderItem from '../components/order/OrderItem.vue'
import {goBackOr} from '../utils/nav'
import {siteConfig as site} from '../config/site'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const order = ref(null)
const loading = ref(true)

// 统一转为大写查找
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

const loadDetail = async () => {
  loading.value = true
  try {
    order.value = await getOrderDetailApi(route.params.id)
  } catch (e) {
    showToast('订单加载失败')
    goBackOr(router, '/orders')
  } finally {
    loading.value = false
  }
}

const handleCancel = async () => {
  try {
    await showConfirmDialog({title: '取消订单', message: '确定要取消该订单吗？'})
    await cancelOrderApi(order.value.id)
    showToast('订单已取消')
    loadDetail()
  } catch (e) {
    if (e !== 'cancel') showToast('取消失败')
  }
}

const handleReceive = async () => {
  try {
    await showConfirmDialog({title: '确认收货', message: '请确认已收到全部商品'})
    await receiveOrderApi(order.value.id)
    showToast('确认收货成功')
    loadDetail()
  } catch (e) {
    if (e !== 'cancel') showToast('操作失败')
  }
}

const handleMockShip = async () => {
  try {
    await shipOrderApi(order.value.id)
    showToast('商家已发货 (模拟)')
    loadDetail()
  } catch (e) {
    showToast('操作失败')
  }
}

onMounted(loadDetail)
</script>

<template>
  <div class="detail-page">
    <div class="nav-bar">
      <div class="back-btn" @click="goBackOr(router, '/orders')">
        <ArrowLeft :size="24"/>
      </div>
      <div class="title">订单详情</div>
    </div>

    <div v-if="loading" style="padding: 100px; text-align: center;">加载中...</div>

    <div v-else-if="order" class="content-wrapper">
      <!-- 状态栏 -->
      <div class="status-banner" :style="{ backgroundColor: getStatus(order.status).color }">
        <h2>{{ getStatus(order.status).text }}</h2>
        <p style="font-size: 13px; opacity: 0.9; margin-top: 6px;">订单号：{{ order.id }}</p>
      </div>

      <!-- 收货地址 -->
      <div class="address-card">
        <div class="icon-box">
          <MapPin :size="20" color="#ef4444"/>
        </div>
        <div class="address-info">
          <div class="user-info">
            <span class="name">{{ site.demoAddress.name }}</span>
            <span class="phone">{{ site.demoAddress.phone }}</span>
          </div>
          <div class="detail">{{ site.demoAddress.detail }}</div>
        </div>
      </div>

      <!-- 商品明细 (复用组件) -->
      <div class="order-items">
        <OrderItem v-for="item in order.items" :key="item.product_id" :item="item"/>
      </div>

      <!-- 金额与信息 -->
      <van-cell-group inset title="订单信息" class="info-group">
        <van-cell title="商品总额" :value="`¥${order.total_amount.toFixed(2)}`"/>
        <van-cell title="运费" value="¥0.00"/>
        <van-cell title="实付款" :value="`¥${order.total_amount.toFixed(2)}`" value-class="total-price"/>
        <van-cell title="下单时间" :value="order.created_at.replace('T', ' ').slice(0, 19)"/>
      </van-cell-group>

      <!-- 底部操作栏 -->
      <div class="bottom-actions" v-if="['PAID', 'SHIPPED'].includes(order.status.toUpperCase())">
        <!-- 待发货状态 -->
        <template v-if="order.status.toUpperCase() === 'PAID'">
          <!-- 取消是「下单人」的动作：管理员从订单管理点进来只是查看/发货，
               不能替患者取消（后端接口也只认本人） -->
          <van-button v-if="!auth.isAdmin" plain type="danger" round @click="handleCancel">取消订单</van-button>
          <!-- 只有管理员能发货 -->
          <van-button v-if="auth.isAdmin" type="warning" round @click="handleMockShip">
            模拟商家发货
          </van-button>
        </template>

        <!-- 待收货状态 -->
        <template v-if="order.status.toUpperCase() === 'SHIPPED'">
          <van-button type="danger" round @click="handleReceive">确认收货</van-button>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.detail-page {
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

    .status-banner {
      color: #fff;
      padding: 24px 16px;
      border-radius: 12px;
      margin-bottom: 16px;

      h2 {
        font-size: 20px;
        font-weight: 600;
      }
    }

    .address-card {
      background: #fff;
      border-radius: 12px;
      padding: 16px;
      display: flex;
      gap: 12px;
      margin-bottom: 16px;

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
      padding: 0 16px;
      margin-bottom: 16px;
    }

    .info-group {
      margin: 0;

      :deep(.van-cell-group__title) {
        padding-left: 4px;
      }

      :deep(.total-price) {
        color: #ee0a24;
        font-weight: bold;
        font-size: 16px;
      }
    }

    .bottom-actions {
      position: fixed;
      bottom: 0;
      left: 0;
      right: 0;
      background: #fff;
      padding: 12px 24px;
      padding-bottom: calc(12px + env(safe-area-inset-bottom));
      display: flex;
      justify-content: flex-end;
      gap: 12px;
      box-shadow: 0 -1px 3px rgba(0, 0, 0, 0.05);
      z-index: 99;
      @media (min-width: 768px) {
        max-width: 800px;
        left: 50%;
        transform: translateX(-50%);
        border-radius: 12px 12px 0 0;
      }
    }
  }
}
</style>