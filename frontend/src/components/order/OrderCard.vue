<script setup>
/**
 * 订单卡（唯一实现）。
 *
 * 患者工作台、我的订单页、管理员订单管理三处都展示订单，之前各写了一遍：
 * 一处有缩略图、一处只有文字摘要，一处能点进详情、一处点了没反应。
 * 现在统一到这里：
 *   - 头部：订单号（可复制）+ 状态标签（+ 下单人，管理员视角）
 *   - 中部：明细行用 OrderItem（带缩略图、可点进药品详情）
 *   - 底部：件数 / 时间 / 合计 + 操作按钮（患者：取消、收货；管理员：发货）
 *
 * 明细超过 3 条时区域内滚动，卡片本身不会被撑到半屏高。
 */
import {computed, ref} from 'vue'
import {showToast} from 'vant'
import dayjs from 'dayjs'
import {ChevronRight, Copy} from 'lucide-vue-next'
import OrderItem from './OrderItem.vue'
import {
  canCancelOrder,
  canReceiveOrder,
  canShipOrder,
  normalizeOrderStatus,
  orderItemCount,
  orderMoney,
  orderStatusMeta,
  shortOrderId
} from '../../utils/orderStatus'

const props = defineProps({
  order: {type: Object, required: true},
  // 有请求在飞（取消 / 收货 / 发货）：锁住按钮
  mutating: {type: Boolean, default: false},
  // 嵌在面板里时不要再套一层卡片的边框和阴影
  flat: {type: Boolean, default: false},
  // 管理员视角：多显示「下单人」
  showUser: {type: Boolean, default: false},
  // 按角色决定底部操作：patient 可取消/收货，admin 可发货，view 只有详情
  mode: {type: String, default: 'view'}
})

const emit = defineEmits(['open', 'cancel', 'receive', 'ship'])

const copied = ref(false)
const status = computed(() => orderStatusMeta(props.order.status))
const items = computed(() => (Array.isArray(props.order.items) ? props.order.items : []))
const count = computed(() => orderItemCount(props.order))
const createdAt = computed(() => {
  const value = props.order.created_at
  if (!value) return '—'
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('YYYY-MM-DD HH:mm') : String(value)
})

const copyId = async () => {
  const id = String(props.order.id || '')
  if (!id) return
  try {
    await navigator.clipboard.writeText(id)
    copied.value = true
    showToast('订单号已复制')
    window.setTimeout(() => {
      copied.value = false
    }, 1500)
  } catch (e) {
    showToast({type: 'fail', message: '复制失败，请手动选择订单号'})
  }
}

const open = () => emit('open', props.order)
</script>

<template>
  <article class="order-card" :class="{ 'is-flat': flat }">
    <header class="card-head">
      <button type="button" class="order-no" title="点击复制完整订单号" @click.stop="copyId">
        <span>{{ shortOrderId(order.id) }}</span>
        <Copy :size="12" :class="{ 'is-copied': copied }"/>
      </button>
      <span class="status" :class="`status--${status.tone}`">{{ status.label }}</span>
    </header>

    <p v-if="showUser" class="buyer">
      下单人：<strong>{{ order.username || '—' }}</strong>
    </p>

    <div class="card-items" :class="{ 'is-scroll': items.length > 3 }">
      <OrderItem v-for="item in items" :key="`${item.product_id}-${item.quantity}`" :item="item"/>
      <p v-if="items.length === 0" class="no-items">商品明细缺失（商品可能已被删除）</p>
    </div>

    <footer class="card-foot">
      <div class="foot-meta">
        <span>{{ createdAt }}</span>
        <span>共 {{ count }} 件</span>
      </div>

      <div class="foot-sum">
        合计 <strong>{{ orderMoney(order.total_amount) }}</strong>
      </div>

      <div class="foot-actions">
        <template v-if="mode === 'patient'">
          <button
              v-if="canCancelOrder(order)"
              type="button"
              class="btn-ghost is-danger"
              :disabled="mutating"
              @click.stop="emit('cancel', order)"
          >
            取消订单
          </button>
          <button
              v-if="canReceiveOrder(order)"
              type="button"
              class="btn-ghost is-primary"
              :disabled="mutating"
              @click.stop="emit('receive', order)"
          >
            确认收货
          </button>
        </template>

        <template v-else-if="mode === 'admin'">
          <button
              v-if="canShipOrder(order)"
              type="button"
              class="btn-ghost is-primary"
              :disabled="mutating"
              @click.stop="emit('ship', order)"
          >
            {{ mutating ? '发货中…' : '模拟发货' }}
          </button>
          <span v-else class="ship-hint">
            {{ normalizeOrderStatus(order.status) === 'shipped' ? '已发货' : '无需发货' }}
          </span>
        </template>

        <slot name="actions"/>

        <button type="button" class="btn-detail" @click.stop="open">
          详情
          <ChevronRight :size="14"/>
        </button>
      </div>
    </footer>
  </article>
</template>

<style scoped lang="scss">
.order-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 12px 14px;
  min-width: 0;

  &.is-flat {
    border: none;
    border-radius: 0;
    padding: 0;
  }

  .card-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding-bottom: 8px;
    border-bottom: 1px dashed #f3f4f6;
  }

  .order-no {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    min-width: 0;
    padding: 0;
    border: none;
    background: transparent;
    color: #6b7280;
    font-size: 12px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    cursor: pointer;

    span {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    svg {
      flex: none;
    }

    &:hover {
      color: #dc2626;
    }

    .is-copied {
      color: #10b981;
    }
  }

  .status {
    flex: none;
    padding: 1px 8px;
    border-radius: 999px;
    font-size: 12px;
    line-height: 18px;
    font-weight: 600;
    white-space: nowrap;

    &.status--warn {
      background: #fff7ed;
      color: #c2410c;
    }

    &.status--primary {
      background: #fef2f2;
      color: #b91c1c;
    }

    &.status--info {
      background: #eff6ff;
      color: #1d4ed8;
    }

    &.status--ok {
      background: #ecfdf5;
      color: #047857;
    }

    &.status--muted {
      background: #f3f4f6;
      color: #6b7280;
    }
  }

  .buyer {
    margin: 8px 0 0;
    font-size: 12px;
    color: #6b7280;
    overflow-wrap: anywhere;

    strong {
      color: #111827;
    }
  }

  .card-items {
    &.is-scroll {
      max-height: 208px;
      overflow-y: auto;
      padding-right: 4px;
      scrollbar-width: thin;
      scrollbar-color: #e5e7eb transparent;
    }

    .no-items {
      margin: 10px 0;
      font-size: 12px;
      color: #9ca3af;
    }
  }

  .card-foot {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    padding-top: 10px;
    border-top: 1px solid #f3f4f6;
    margin-top: 4px;
  }

  .foot-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    font-size: 12px;
    color: #9ca3af;
    min-width: 0;
  }

  .foot-sum {
    margin-left: auto;
    font-size: 13px;
    color: #4b5563;

    strong {
      margin-left: 4px;
      font-size: 17px;
      font-weight: 700;
      color: #dc2626;
    }
  }

  .foot-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }

  .btn-detail {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    height: 30px;
    padding: 0 10px;
    border: 1px solid #fecaca;
    border-radius: 999px;
    background: #fff;
    color: #b91c1c;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;

    &:hover {
      background: #fef2f2;
    }
  }

  .btn-ghost {
    height: 30px;
    padding: 0 12px;
    border-radius: 999px;
    border: 1px solid #e5e7eb;
    background: #fff;
    color: #4b5563;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;

    &:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }

    &.is-danger {
      border-color: #fecaca;
      color: #b91c1c;

      &:hover:not(:disabled) {
        background: #fef2f2;
      }
    }

    &.is-primary {
      border-color: transparent;
      background: #dc2626;
      color: #fff;

      &:hover:not(:disabled) {
        background: #b91c1c;
      }
    }
  }

  .ship-hint {
    font-size: 12px;
    color: #9ca3af;
  }

  @media (max-width: 768px) {
    padding: 10px 12px;

    .foot-sum {
      margin-left: 0;

      strong {
        font-size: 16px;
      }
    }

    .foot-actions {
      width: 100%;
      justify-content: flex-end;
    }
  }
}
</style>
