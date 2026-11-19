<script setup>
/**
 * 药品卡片（唯一实现，两种形态）。
 *
 * 背景：这里曾经有两个几乎重复的组件——后台「药品库管理」用 van-card 横排，
 * 前台「药品广场」用瀑布流竖排。两套卡片各自处理图片兜底、价格、库存，
 * 改一处忘另一处，同一个药品在管理页和广场长得不一样、图片兜底行为也不一致。
 *
 * 现在合成一个组件，用 variant 区分：
 *   variant="shop"   → 广场竖排卡（加入购物车 / 缺货态 / 详情箭头）
 *   variant="manage" → 后台横排卡（编辑 / 删除 / 库存标签）
 *
 * 两种形态共用同一套「图片地址纠正 + 裂图占位 + 价格 / 库存 / 规格」逻辑。
 */
import {computed, ref} from 'vue'
import {useRouter} from 'vue-router'
import {ChevronRight, Plus} from 'lucide-vue-next'
import {FALLBACK_IMAGE, normalizeImageUrl} from '../../utils/image'

const props = defineProps({
  item: {type: Object, required: true},
  variant: {type: String, default: 'shop'}, // shop | manage
  // 加购请求进行中：按钮文案变化并锁住，避免连点造成重复加购
  adding: {type: Boolean, default: false}
})

const emit = defineEmits(['add', 'edit', 'delete'])

const router = useRouter()

const imageFailed = ref(false)
// 后端历史数据里可能有 `\\` 路径；空值 / 裂图都落到内联 SVG 占位，
// 不额外发请求，也不会让卡片高度二次抖动
const imageSrc = computed(() => {
  const fixed = normalizeImageUrl(props.item.image_url)
  if (imageFailed.value || !fixed) return FALLBACK_IMAGE
  return fixed
})

const isShop = computed(() => props.variant !== 'manage')
const inStock = computed(() => Number(props.item.stock) > 0)
const hasDiscount = computed(() => Number(props.item.original_price) > Number(props.item.price))
// 剂型 / 规格都可能缺字段，过滤空值，避免出现「颗粒剂 · 」这种尾巴
const specText = computed(() => [props.item.dosage_form, props.item.spec].filter(Boolean).join(' · '))
const descText = computed(() => (specText.value ? specText.value : props.item.dosage_form || ''))

const goDetail = () => {
  router.push(`/product/${props.item.id}`)
}

const handleAdd = () => {
  if (!inStock.value || props.adding) return
  emit('add', props.item)
}
</script>

<template>
  <!-- ------------------------------ 广场竖排卡 ------------------------------ -->
  <article
      v-if="isShop"
      class="product-card is-shop"
      :class="{ 'is-sold-out': !inStock }"
      role="link"
      tabindex="0"
      :aria-label="`查看 ${item.name} 详情`"
      @click="goDetail"
      @keydown.enter.self="goDetail"
  >
    <!-- 固定宽高比：图片未加载完也占住位置，瀑布流不会先塌再撑 -->
    <div class="thumb-box">
      <img
          class="thumb"
          :src="imageSrc"
          :alt="item.name"
          loading="lazy"
          @error="imageFailed = true"
      />
      <span v-if="!inStock" class="sold-out-mask">暂时缺货</span>
    </div>

    <div class="card-body">
      <h3 class="name">{{ item.name }}</h3>
      <p v-if="item.generic_name" class="generic">{{ item.generic_name }}</p>
      <p v-if="specText" class="spec">{{ specText }}</p>
      <!-- 适应症是控制卡片高度的主要变量，最多两行，瀑布流才有错落感 -->
      <p v-if="item.indications" class="indications">{{ item.indications }}</p>

      <div class="tags">
        <span v-if="item.category" class="tag tag-category">{{ item.category }}</span>
        <span class="tag tag-stock" :class="{ 'is-out': !inStock }">
          {{ inStock ? `库存 ${item.stock}` : '暂无库存' }}
        </span>
      </div>

      <div class="price-row">
        <span class="price"><small>¥</small>{{ item.price }}</span>
        <span v-if="hasDiscount" class="origin-price">¥{{ item.original_price }}</span>
      </div>

      <div class="card-foot">
        <button
            type="button"
            class="add-btn"
            :disabled="!inStock || adding"
            @click.stop="handleAdd"
            @keydown.enter.stop
        >
          <Plus :size="14"/>
          {{ !inStock ? '暂时缺货' : (adding ? '加入中…' : '加入购物车') }}
        </button>
        <!-- 右下角箭头是「整张卡可点进详情」的视觉信号，本身不单独响应点击 -->
        <span class="detail-hint" aria-hidden="true">
          详情<ChevronRight :size="14"/>
        </span>
      </div>
    </div>
  </article>

  <!-- ------------------------------ 后台横排卡 ------------------------------ -->
  <div v-else class="product-card is-manage" @click="goDetail">
    <van-card
        :price="String(item.price)"
        :title="item.name"
        :desc="descText"
        :thumb="imageSrc"
        currency="¥"
        class="manage-card"
    >
      <template #price>
        <div class="price-box">
          <span class="current-price">¥{{ item.price }}</span>
          <span v-if="hasDiscount" class="origin-price">¥{{ item.original_price }}</span>
        </div>
      </template>

      <template #tags>
        <van-tag v-if="item.category" type="danger" plain style="margin-right: 4px;">
          {{ item.category }}
        </van-tag>
        <van-tag type="primary" plain>库存 {{ item.stock }}</van-tag>
      </template>

      <!-- 阻止冒泡，防止点按钮时触发卡片的详情跳转 -->
      <template #footer>
        <div class="card-actions" @click.stop>
          <van-button size="mini" plain type="primary" @click="emit('edit', item)">编辑</van-button>
          <van-button size="mini" plain type="danger" @click="emit('delete', item.id)">删除</van-button>
          <span class="detail-hint" @click="goDetail">
            详情<ChevronRight :size="13"/>
          </span>
        </div>
      </template>
    </van-card>
  </div>
</template>

<style scoped lang="scss">
/* ============================== 广场竖排卡 ============================== */
.product-card.is-shop {
  display: block;
  width: 100%;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  overflow: hidden;
  cursor: pointer;
  color: #374151;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
  break-inside: avoid;

  &:hover {
    transform: translateY(-2px);
    border-color: #fecaca;
    box-shadow: 0 10px 24px -18px rgba(17, 24, 39, 0.55);
  }

  &:focus-visible {
    outline: 2px solid #fca5a5;
    outline-offset: 2px;
  }

  &.is-sold-out {
    .thumb {
      filter: grayscale(0.6);
      opacity: 0.75;
    }
  }

  .thumb-box {
    position: relative;
    width: 100%;
    aspect-ratio: 4 / 3;
    background: #f9fafb;
    overflow: hidden;
  }

  .thumb {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: cover; // 统一裁切，避免不同尺寸的药品图把卡片高度拉花
  }

  .sold-out-mask {
    position: absolute;
    right: 8px;
    bottom: 8px;
    padding: 2px 8px;
    border-radius: 999px;
    background: rgba(17, 24, 39, 0.72);
    color: #fff;
    font-size: 11px;
    line-height: 18px;
  }

  .card-body {
    padding: 10px 12px 12px;
    min-width: 0;
  }

  .name {
    margin: 0;
    font-size: 14px;
    font-weight: 600;
    line-height: 1.45;
    color: #111827;
    overflow-wrap: anywhere;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .generic {
    margin: 4px 0 0;
    font-size: 12px;
    color: #6b7280;
    overflow-wrap: anywhere;
    display: -webkit-box;
    -webkit-line-clamp: 1;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .spec {
    margin: 6px 0 0;
    font-size: 12px;
    color: #6b7280;
    overflow-wrap: anywhere;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .indications {
    margin: 8px 0 0;
    font-size: 12px;
    line-height: 1.6;
    color: #9ca3af;
    overflow-wrap: anywhere;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 10px;
  }

  .tag {
    max-width: 100%;
    padding: 1px 8px;
    border-radius: 6px;
    font-size: 11px;
    line-height: 18px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;

    &.tag-category {
      background: #fef2f2;
      color: #b91c1c;
    }

    &.tag-stock {
      background: #f3f4f6;
      color: #6b7280;

      &.is-out {
        background: #f9fafb;
        color: #9ca3af;
      }
    }
  }

  .price-row {
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 10px;
  }

  .price {
    color: #dc2626;
    font-size: 18px;
    font-weight: 700;
    line-height: 1.2;

    small {
      margin-right: 1px;
      font-size: 12px;
      font-weight: 600;
    }
  }

  .origin-price {
    color: #9ca3af;
    font-size: 12px;
    text-decoration: line-through;
  }

  .card-foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-top: 10px;
  }

  .add-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
    height: 34px;
    padding: 0 12px;
    border: none;
    border-radius: 999px;
    background: #dc2626;
    color: #fff;
    font-size: 13px;
    font-weight: 600;
    white-space: nowrap;
    cursor: pointer;
    transition: background-color 0.16s ease, transform 0.16s ease;

    &:hover:not(:disabled) {
      background: #b91c1c;
    }

    &:active:not(:disabled) {
      transform: scale(0.97);
    }

    &:disabled {
      background: #f3f4f6;
      color: #9ca3af;
      cursor: not-allowed;
    }
  }

  .detail-hint {
    display: inline-flex;
    align-items: center;
    gap: 1px;
    flex: none;
    color: #9ca3af;
    font-size: 12px;
    transition: color 0.16s ease;
  }

  &:hover .detail-hint {
    color: #dc2626;
  }
}

/* ============================== 后台横排卡 ============================== */
.product-card.is-manage {
  cursor: pointer;
  transition: transform 0.2s;
  height: 100%;

  &:hover {
    transform: translateY(-2px);
  }
}

:deep(.manage-card) {
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
    align-items: center;
    gap: 8px;
    margin-top: 10px;

    .van-button {
      flex: 1;
    }

    .detail-hint {
      flex: none;
      display: inline-flex;
      align-items: center;
      gap: 1px;
      color: #9ca3af;
      font-size: 12px;

      &:hover {
        color: #dc2626;
      }
    }
  }
}

/* ============================== 移动端 ============================== */
@media (max-width: 768px) {
  .product-card.is-shop {
    .card-body {
      padding: 8px 10px 10px;
    }

    .name {
      font-size: 13px;
    }

    .price {
      font-size: 16px;
    }

    // 手机上卡片更窄，按钮撑到 36px 高度更利于点按，同时不挤压「详情」箭头
    .add-btn {
      height: 36px;
      padding: 0 10px;
      font-size: 12px;

      svg {
        display: none; // 小屏优先保证文字完整，加号可省
      }
    }

    .detail-hint {
      font-size: 11px;
    }
  }
}
</style>
