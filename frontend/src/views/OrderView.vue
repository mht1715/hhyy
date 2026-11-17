<script setup>
import {ref, onMounted} from 'vue'
import {useRouter} from 'vue-router'
import {getMyOrdersApi} from '../api/order'
import {ArrowLeft} from 'lucide-vue-next'
import dayjs from 'dayjs' // 如果没装 dayjs，直接用原生 Date 转换即可

const router = useRouter()
const orders = ref([])
const loading = ref(true)

onMounted(async () => {
  try {
    orders.value = await getMyOrdersApi()
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="order-page">
    <div class="nav-bar">
      <div class="back-btn" @click="router.back()">
        <ArrowLeft :size="24"/>
      </div>
      <div class="title">我的订单</div>
    </div>

    <div v-if="loading" style="padding: 100px; text-align: center;">加载中...</div>
    <van-empty v-else-if="orders.length === 0" description="暂无订单记录"/>

    <div v-else class="order-list">
      <div class="order-card" v-for="order in orders" :key="order.id">
        <div class="order-header">
          <span class="order-no">订单号：{{ order.id.slice(0, 8) }}...</span>
          <span class="order-status">已支付</span>
        </div>
        <div class="order-items">
          <div class="item" v-for="item in order.items" :key="item.product_id">
            <img :src="item.image_url || 'https://fastly.jsdelivr.net/npm/@vant/assets/cat.jpeg'"/>
            <div class="info">
              <div class="name">{{ item.name }}</div>
              <div class="price">¥{{ item.unit_price }} x {{ item.quantity }}</div>
            </div>
          </div>
        </div>
        <div class="order-footer">
          总金额：<span class="total">¥{{ order.total_amount.toFixed(2) }}</span>
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

      .order-header {
        display: flex;
        justify-content: space-between;
        padding: 12px 16px;
        background: #f9f9f9;
        font-size: 13px;

        .order-status {
          color: #10b981;
          font-weight: bold;
        }
      }

      .order-items {
        padding: 16px;

        .item {
          display: flex;
          gap: 12px;
          margin-bottom: 12px;

          &:last-child {
            margin-bottom: 0;
          }

          img {
            width: 60px;
            height: 60px;
            object-fit: contain;
            background: #f9f9f9;
            border-radius: 6px;
          }

          .info {
            flex: 1;

            .name {
              font-size: 14px;
              font-weight: 600;
              color: #333;
            }

            .price {
              font-size: 13px;
              color: #999;
              margin-top: 4px;
            }
          }
        }
      }

      .order-footer {
        text-align: right;
        padding: 12px 16px;
        border-top: 1px solid #f3f4f6;
        font-size: 14px;

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