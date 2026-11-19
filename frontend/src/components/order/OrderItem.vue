<script setup>
/**
 * 订单明细行：缩略图 + 名称 + 单价 × 数量，整行可点进药品详情。
 *
 * 这一行在三个地方复用（订单列表、订单详情、管理员订单管理），
 * 所以图片兜底、点击目标、缺字段时的降级都在这里处理一次。
 */
import {useRouter} from 'vue-router'
import {ChevronRight} from 'lucide-vue-next'
import {imageUrl, onImageError} from '../../utils/image'

const props = defineProps({
  item: {type: Object, required: true},
  // 管理员列表里单价可能是 unit_price，购物车场景用 price
  priceKey: {type: String, default: 'unit_price'}
})

const router = useRouter()

const price = () => Number(props.item[props.priceKey]) || 0

const goToDetail = () => {
  if (!props.item.product_id) return
  router.push(`/product/${props.item.product_id}`)
}
</script>

<template>
  <div
      class="order-item"
      :class="{ 'is-link': !!item.product_id }"
      role="link"
      tabindex="0"
      :aria-label="`查看 ${item.name || '药品'} 详情`"
      @click="goToDetail"
      @keydown.enter.prevent="goToDetail"
  >
    <img class="thumb" :src="imageUrl(item.image_url)" :alt="item.name || '药品'" loading="lazy"
         @error="onImageError"/>
    <div class="info">
      <div class="name">
        {{ item.name }}
        <ChevronRight v-if="item.product_id" :size="13" class="arrow"/>
      </div>
      <div class="price-info">
        <span class="price">¥{{ price().toFixed(2) }}</span>
        <span class="quantity">x{{ item.quantity }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.order-item {
  display: flex;
  gap: 12px;
  padding: 12px 0;
  cursor: default;
  border-bottom: 1px solid #f3f4f6;

  &.is-link {
    cursor: pointer;

    &:hover .name {
      color: #dc2626;
    }

    &:hover .arrow {
      color: #dc2626;
    }
  }

  &:last-child {
    border-bottom: none;
    padding-bottom: 0;
  }

  .thumb {
    width: 64px;
    height: 64px;
    flex: none;
    object-fit: cover;
    background: #f9f9f9;
    border-radius: 8px;
  }

  .info {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    justify-content: center;

    .name {
      display: flex;
      align-items: center;
      gap: 2px;
      font-size: 14px;
      font-weight: 600;
      color: #333;
      margin-bottom: 8px;
      overflow-wrap: anywhere;
      transition: color 0.15s ease;

      .arrow {
        flex: none;
        color: #d1d5db;
      }
    }

    .price-info {
      display: flex;
      gap: 8px;
      font-size: 13px;

      .price {
        color: #ee0a24;
        font-weight: bold;
      }

      .quantity {
        color: #999;
      }
    }
  }
}
</style>
