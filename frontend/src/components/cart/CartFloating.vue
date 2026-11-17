<script setup>
import {ref} from 'vue'
import {useRouter} from 'vue-router'
import {useCartStore} from '../../store/cart'
import {ShoppingCart, Trash2} from 'lucide-vue-next'
import {showToast} from 'vant'

const router = useRouter()
const cartStore = useCartStore()
const showCartPopup = ref(false)

const handleCheckout = () => {
  if (cartStore.items.length === 0) return
  showCartPopup.value = false
  router.push('/checkout')
}
</script>

<template>
  <div class="cart-floating">
    <!-- 悬浮按钮 -->
    <div class="cart-btn" @click="showCartPopup = true">
      <ShoppingCart :size="24" color="#fff"/>
      <span v-if="cartStore.totalCount > 0" class="badge">{{ cartStore.totalCount }}</span>
    </div>

    <!-- 购物车弹窗 -->
    <van-popup
        v-model:show="showCartPopup"
        position="bottom"
        round
        :style="{ maxHeight: '70%' }"
        safe-area-inset-bottom
    >
      <div class="cart-popup-content">
        <div class="cart-header">
          <h3>购物车</h3>
          <span v-if="cartStore.items.length > 0" class="clear-btn" @click="cartStore.clearCart()">
            <Trash2 :size="16"/> 清空
          </span>
        </div>

        <van-empty v-if="cartStore.items.length === 0" description="购物车空空如也"/>

        <div class="cart-list" v-else>
          <div class="cart-item" v-for="item in cartStore.items" :key="item.id">
            <img :src="item.image_url || 'https://fastly.jsdelivr.net/npm/@vant/assets/cat.jpeg'" class="thumb"/>
            <div class="info">
              <div class="name">{{ item.name }}</div>
              <div class="price">¥{{ item.price }}</div>
            </div>
            <div class="actions">
              <!-- 单项删除按钮 -->
              <van-icon name="delete-o" size="20" color="#969799" @click="cartStore.removeFromCart(item.id)"/>
              <van-stepper v-model="item.quantity" min="1" @change="cartStore.save()"/>
            </div>
          </div>
        </div>

        <div class="cart-footer" v-if="cartStore.items.length > 0">
          <div class="total">
            合计：<span class="total-price">¥{{ cartStore.totalPrice.toFixed(2) }}</span>
          </div>
          <van-button type="danger" round @click="handleCheckout">去结算</van-button>
        </div>
      </div>
    </van-popup>
  </div>
</template>

<style scoped lang="scss">
.cart-floating {
  position: fixed;
  bottom: 80px;
  left: 20px;
  z-index: 99999;

  .cart-btn {
    width: 56px;
    height: 56px;
    background: #ef4444;
    border-radius: 50%;
    display: flex;
    justify-content: center;
    align-items: center;
    box-shadow: 0 4px 12px rgba(239, 68, 68, 0.4);
    cursor: pointer;
    position: relative;
    transition: transform 0.2s;

    &:active {
      transform: scale(0.95);
    }

    .badge {
      position: absolute;
      top: -4px;
      right: -4px;
      background: #fbbf24;
      color: #fff;
      font-size: 12px;
      font-weight: bold;
      padding: 2px 6px;
      border-radius: 10px;
      border: 2px solid #fff;
    }
  }

  .cart-popup-content {
    padding: 16px;
    display: flex;
    flex-direction: column;
    height: 100%;

    .cart-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;

      h3 {
        font-size: 18px;
      }

      .clear-btn {
        font-size: 13px;
        color: #ef4444;
        display: flex;
        align-items: center;
        gap: 4px;
        cursor: pointer;
      }
    }

    .cart-list {
      flex: 1;
      overflow-y: auto;
      max-height: 40vh;

      .cart-item {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px 0;
        border-bottom: 1px solid #f3f4f6;

        .thumb {
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
            color: #323233;
            margin-bottom: 4px;
            display: -webkit-box;
            -webkit-line-clamp: 1;
            -webkit-box-orient: vertical;
            overflow: hidden;
          }

          .price {
            color: #ee0a24;
            font-weight: bold;
          }
        }

        .actions {
          display: flex;
          flex-direction: column;
          align-items: flex-end;
          gap: 8px;
        }
      }
    }

    .cart-footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-top: 16px;
      border-top: 1px solid #f3f4f6;

      .total {
        font-size: 14px;
      }

      .total-price {
        color: #ee0a24;
        font-size: 20px;
        font-weight: bold;
      }
    }
  }
}
</style>