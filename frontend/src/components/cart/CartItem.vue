<script setup>
/**
 * 购物车单行（唯一实现）。
 *
 * 之前「购物车」有两份 UI：详情页的浮层（CartFloating）和独立购物车页各写了一遍
 * 缩略图 + 名称 + 步进器 + 小计 + 删除，样式和交互细节（能不能减到 0、点图能不能
 * 进详情）还不一致。现在两边都用这个组件，行为只有一份。
 */
import {computed} from 'vue'
import {useRouter} from 'vue-router'
import {ChevronRight, Minus, Plus, Trash2} from 'lucide-vue-next'
import {imageUrl, onImageError} from '../../utils/image'

const props = defineProps({
  item: {type: Object, required: true},
  // 请求进行中：锁住步进器与删除，避免连点
  busy: {type: Boolean, default: false},
  // 浮层里带勾选框；购物车页默认全选，不需要
  selectable: {type: Boolean, default: false},
  checked: {type: Boolean, default: true},
  showSubtotal: {type: Boolean, default: true}
})

const emit = defineEmits(['open', 'remove', 'change', 'update:checked'])

const router = useRouter()

const quantity = computed(() => Number(props.item.quantity) || 0)
const price = computed(() => Number(props.item.price) || 0)
const subtotal = computed(() => price.value * quantity.value)
const money = (value) => `¥${(Number(value) || 0).toFixed(2)}`
const canDecrease = computed(() => quantity.value > 1)

const goDetail = () => {
  emit('open', props.item)
  if (props.item.product_id) router.push(`/product/${props.item.product_id}`)
}

const change = (delta) => {
  if (props.busy) return
  const next = quantity.value + delta
  if (next < 1) return
  emit('change', props.item, next)
}

const remove = () => {
  if (props.busy) return
  emit('remove', props.item)
}
</script>

<template>
  <div class="cart-line" :class="{ 'is-busy': busy }">
    <label v-if="selectable" class="pick" @click.stop>
      <input
          type="checkbox"
          :checked="checked"
          :aria-label="`选择 ${item.name || '商品'}`"
          @change="emit('update:checked', $event.target.checked)"
      />
    </label>

    <button type="button" class="thumb-btn" :aria-label="`查看 ${item.name || '商品'} 详情`" @click="goDetail">
      <img class="thumb" :src="imageUrl(item.image_url)" :alt="item.name || '商品'" loading="lazy"
           @error="onImageError"/>
    </button>

    <div class="line-main">
      <button type="button" class="line-name" @click="goDetail">
        {{ item.name || '商品已下架' }}
        <ChevronRight :size="13" class="name-arrow"/>
      </button>
      <p class="line-meta">
        单价 {{ money(price) }}<span v-if="item.spec"> · {{ item.spec }}</span>
      </p>

      <div class="line-foot">
        <div class="stepper">
          <button type="button" :disabled="busy || !canDecrease" aria-label="减少一件" @click="change(-1)">
            <Minus :size="14"/>
          </button>
          <span class="qty">{{ quantity }}</span>
          <button type="button" :disabled="busy" aria-label="增加一件" @click="change(1)">
            <Plus :size="14"/>
          </button>
        </div>

        <span v-if="showSubtotal" class="line-subtotal">{{ money(subtotal) }}</span>

        <button type="button" class="line-remove" :disabled="busy" title="移出购物车" @click="remove">
          <Trash2 :size="15"/>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.cart-line {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid #f3f4f6;
  min-width: 0;

  &:last-child {
    border-bottom: none;
  }

  &.is-busy {
    opacity: 0.7;
  }

  .pick {
    flex: none;
    display: grid;
    place-items: center;
    width: 22px;

    input {
      width: 18px;
      height: 18px;
      accent-color: #dc2626;
      cursor: pointer;
    }
  }

  .thumb-btn {
    flex: none;
    width: 64px;
    height: 64px;
    padding: 0;
    border: 1px solid #f3f4f6;
    border-radius: 10px;
    background: #f9fafb;
    overflow: hidden;
    cursor: pointer;

    .thumb {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
  }

  .line-main {
    flex: 1;
    min-width: 0;
  }

  .line-name {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    max-width: 100%;
    padding: 0;
    border: none;
    background: transparent;
    color: #111827;
    font-size: 14px;
    font-weight: 600;
    text-align: left;
    cursor: pointer;
    overflow-wrap: anywhere;

    .name-arrow {
      flex: none;
      color: #d1d5db;
    }

    &:hover {
      color: #dc2626;

      .name-arrow {
        color: #dc2626;
      }
    }
  }

  .line-meta {
    margin: 4px 0 0;
    font-size: 12px;
    color: #6b7280;
    overflow-wrap: anywhere;
  }

  .line-foot {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 8px;
    flex-wrap: wrap;
  }

  .stepper {
    display: inline-flex;
    align-items: center;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    overflow: hidden;

    button {
      width: 28px;
      height: 28px;
      display: grid;
      place-items: center;
      border: none;
      background: #f9fafb;
      color: #4b5563;
      cursor: pointer;

      &:disabled {
        color: #d1d5db;
        cursor: not-allowed;
      }
    }

    .qty {
      min-width: 30px;
      text-align: center;
      font-size: 13px;
      font-weight: 600;
      color: #111827;
    }
  }

  .line-subtotal {
    margin-left: auto;
    font-size: 14px;
    font-weight: 700;
    color: #dc2626;
  }

  .line-remove {
    flex: none;
    width: 28px;
    height: 28px;
    display: grid;
    place-items: center;
    border: none;
    border-radius: 8px;
    background: transparent;
    color: #9ca3af;
    cursor: pointer;

    &:hover:not(:disabled) {
      color: #dc2626;
      background: #fef2f2;
    }

    &:disabled {
      cursor: not-allowed;
      opacity: 0.5;
    }
  }

  @media (max-width: 768px) {
    gap: 10px;

    .thumb-btn {
      width: 56px;
      height: 56px;
    }

    .line-name {
      font-size: 13px;
    }

    .line-subtotal {
      font-size: 13px;
    }
  }
}
</style>
