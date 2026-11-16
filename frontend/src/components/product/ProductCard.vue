<script setup>
import {useRouter} from 'vue-router'

const props = defineProps({
  item: {type: Object, required: true}
})
const emit = defineEmits(['edit', 'delete'])

const router = useRouter()

// 点击卡片跳转详情
const goToDetail = () => {
  router.push(`/product/${props.item.id}`)
}
</script>

<template>
  <div class="product-card-wrap" @click="goToDetail">
    <van-card
        :price="item.price.toString()"
        :title="item.name"
        :desc="item.spec ? `${item.dosage_form} / ${item.spec}` : item.dosage_form"
        :thumb="item.image_url || 'https://fastly.jsdelivr.net/npm/@vant/assets/cat.jpeg'"
        currency="¥"
        class="product-card"
    >
      <template #price>
        <div class="price-box">
          <span class="current-price">¥{{ item.price }}</span>
          <span class="origin-price" v-if="item.original_price > item.price">¥{{ item.original_price }}</span>
        </div>
      </template>

      <template #tags>
        <van-tag type="danger" plain style="margin-right: 4px;">{{ item.category }}</van-tag>
        <van-tag type="primary" plain>库存 {{ item.stock }}</van-tag>
      </template>

      <!-- 阻止冒泡，防止点击按钮时触发卡片的跳转 -->
      <template #footer>
        <div class="card-actions" @click.stop>
          <van-button size="mini" plain type="primary" @click="emit('edit', item)">编辑</van-button>
          <van-button size="mini" plain type="danger" @click="emit('delete', item.id)">删除</van-button>
        </div>
      </template>
    </van-card>
  </div>
</template>

<style scoped lang="scss">
.product-card-wrap {
  cursor: pointer;
  transition: transform 0.2s;
  height: 100%;

  &:hover {
    transform: translateY(-2px);
  }
}

:deep(.product-card) {
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  height: 100%;
  display: flex;
  flex-direction: column;

  .van-card__header {
    flex-direction: column;
  }

  .van-card__thumb {
    width: 100% !important;
    height: 180px !important;
    margin-right: 0;
    margin-bottom: 8px;

    img {
      border-radius: 8px;
      object-fit: contain;
      background: #f9f9f9;
    }
  }

  .van-card__content {
    min-height: auto;
  }

  .van-card__title {
    font-size: 15px;
    font-weight: 600;
    color: #323233;
    margin-bottom: 4px;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .van-card__desc {
    font-size: 12px;
    color: #969799;
    margin-bottom: 6px;
  }

  .van-card__bottom {
    margin-top: 4px;
  }

  .price-box {
    display: flex;
    align-items: baseline;
    gap: 4px;

    .current-price {
      color: #ee0a24;
      font-size: 18px;
      font-weight: bold;
    }

    .origin-price {
      color: #969799;
      font-size: 12px;
      text-decoration: line-through;
    }
  }

  .card-actions {
    display: flex;
    gap: 8px;
    margin-top: 10px;

    .van-button {
      flex: 1;
    }
  }
}
</style>