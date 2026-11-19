<script setup>
import {ref, onMounted, watch, computed} from 'vue'
import {useRouter} from 'vue-router'
import {useCartStore} from '../../store/cart'
import {useAuthStore} from '../../store/auth'
import {ShoppingCart, Trash2} from 'lucide-vue-next'
import {showToast} from 'vant'
import CartItem from './CartItem.vue'
import {writeCheckoutItems} from '../../utils/checkout'

const router = useRouter()
const cartStore = useCartStore()
const auth = useAuthStore()
const showCartPopup = ref(false)

// 勾选的商品ID列表
const checkedIds = ref([])

onMounted(() => {
  if (auth.isLoggedIn) cartStore.fetchCart()
})

watch(showCartPopup, async (newVal) => {
  if (newVal && auth.isLoggedIn) {
    await cartStore.fetchCart()
    // 默认全选
    checkedIds.value = cartStore.items.map(i => i.id)
  }
})

// 全选/反选逻辑
const isAllChecked = computed({
  get: () => cartStore.items.length > 0 && checkedIds.value.length === cartStore.items.length,
  set: (val) => {
    checkedIds.value = val ? cartStore.items.map(i => i.id) : []
  }
})

// 计算选中商品的总价
const checkedTotalPrice = computed(() => {
  return cartStore.items
      .filter(item => checkedIds.value.includes(item.id))
      .reduce((sum, item) => {
        // 强制转为数字计算，防止字符串拼接或 NaN
        const price = Number(item.price) || 0;
        const qty = Number(item.quantity) || 0;
        return sum + (price * qty);
      }, 0)
})

// 修改数量
const handleQuantityChange = (item, next) => {
  const quantity = Math.max(1, Math.floor(Number(next) || 1))
  cartStore.updateQuantity(item.id, quantity)
}

// 单行的勾选框由 CartItem 提供，这里维护选中集合（全选 / 合计都依赖它）
const toggleCheck = (item, checked) => {
  const id = item.id
  if (checked) {
    if (!checkedIds.value.includes(id)) checkedIds.value = [...checkedIds.value, id]
    return
  }
  checkedIds.value = checkedIds.value.filter((value) => value !== id)
}

const handleCheckout = () => {
  if (checkedIds.value.length === 0) return showToast('请选择要结算的商品')
  if (!auth.isLoggedIn) {
    auth.isLoginModalOpen = true
    return showToast('请先登录后再结算')
  }
  // 把「勾选的那几件」整体交给结算页：只给 id 的话，结算页还得依赖 store 已经 fetch 完，
  // 而且提交时是整车下单——勾了 2 件车里还有 3 件时会多买
  const selected = cartStore.items.filter((item) => checkedIds.value.includes(item.id))
  if (selected.length === 0) return showToast('选中的商品已不在购物车，请刷新后再试')
  showCartPopup.value = false
  writeCheckoutItems(selected)
  router.push('/checkout')
}

const handleClear = async () => {
  await cartStore.clear()
  checkedIds.value = []
}

const handleRemove = async (itemId) => {
  await cartStore.remove(itemId)
  checkedIds.value = checkedIds.value.filter(id => id !== itemId)
}
</script>

<template>
  <div class="cart-floating">
    <div class="cart-btn" @click="showCartPopup = true">
      <ShoppingCart :size="24" color="#fff"/>
      <span v-if="cartStore.totalCount > 0" class="badge">{{ cartStore.totalCount }}</span>
    </div>

    <van-popup v-model:show="showCartPopup" position="bottom" round :style="{ maxHeight: '70%' }"
               safe-area-inset-bottom>
      <div class="cart-popup-content">
        <div class="cart-header">
          <h3>购物车</h3>
          <span v-if="cartStore.items.length > 0" class="clear-btn" @click="handleClear">
            <Trash2 :size="16"/> 清空
          </span>
        </div>

        <van-empty v-if="cartStore.items.length === 0" description="购物车空空如也"/>

        <div class="cart-list" v-else>
          <!-- 勾选框和单行 UI 都收在 CartItem 里：购物车页、患者工作台用的是同一个组件 -->
          <CartItem
              v-for="item in cartStore.items"
              :key="item.id"
              :item="item"
              selectable
              :checked="checkedIds.includes(item.id)"
              @update:checked="(value) => toggleCheck(item, value)"
              @change="handleQuantityChange"
              @remove="(row) => handleRemove(row.id)"
          />
        </div>

        <div class="cart-footer" v-if="cartStore.items.length > 0">
          <div class="select-all">
            <van-checkbox v-model="isAllChecked" shape="square">全选</van-checkbox>
          </div>
          <div class="total">
            合计：<span class="total-price">¥{{ checkedTotalPrice.toFixed(2) }}</span>
            <van-button type="danger" round style="margin-left: 12px;" @click="handleCheckout">
              去结算({{ checkedIds.length }})
            </van-button>
          </div>
        </div>
      </div>
    </van-popup>
  </div>
</template>

<style scoped lang="scss">
/* 保持之前的样式，新增以下微小调整 */
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
        padding: 12px 0;
        border-bottom: 1px solid #f3f4f6;

        .thumb {
          width: 60px;
          height: 60px;
          object-fit: contain;
          background: #f9f9f9;
          border-radius: 6px;
          margin: 0 8px;
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

      .select-all {
        display: flex;
        align-items: center;
      }

      .total {
        display: flex;
        align-items: center;
        font-size: 14px;

        .total-price {
          color: #ee0a24;
          font-size: 20px;
          font-weight: bold;
        }
      }
    }
  }
}
</style>