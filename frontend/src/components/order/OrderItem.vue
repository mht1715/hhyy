<script setup>
import {useRouter} from 'vue-router'

const props = defineProps({
  item: {type: Object, required: true}
})
const router = useRouter()

const goToDetail = () => {
  router.push(`/product/${props.item.product_id}`)
}
</script>

<template>
  <div class="order-item" @click="goToDetail">
    <img :src="item.image_url || 'https://fastly.jsdelivr.net/npm/@vant/assets/cat.jpeg'" class="thumb"/>
    <div class="info">
      <div class="name">{{ item.name }}</div>
      <div class="price-info">
        <span class="price">¥{{ item.unit_price }}</span>
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
  cursor: pointer;
  border-bottom: 1px solid #f3f4f6;

  &:last-child {
    border-bottom: none;
    padding-bottom: 0;
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
    display: flex;
    flex-direction: column;
    justify-content: center;

    .name {
      font-size: 14px;
      font-weight: 600;
      color: #333;
      margin-bottom: 8px;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
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