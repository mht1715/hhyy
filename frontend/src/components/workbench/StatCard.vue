<script setup>
/**
 * 指标卡：工作台首屏的「一眼看到」。
 *
 * `to` 有值时整张卡可点（跳到对应 Tab），键盘也能回车触发；
 * `loading` 时保留占位而不是整块消失，避免数字刷新时页面跳动。
 */
import {useRouter} from 'vue-router'
import {ChevronRight} from 'lucide-vue-next'

const props = defineProps({
  label: {type: String, default: ''},
  value: {type: [Number, String], default: '—'},
  unit: {type: String, default: ''},
  hint: {type: String, default: ''},
  tone: {type: String, default: 'default'}, // default | primary | warn | danger | ok
  icon: {type: [Object, Function], default: null},
  to: {type: [String, Object], default: ''},
  loading: {type: Boolean, default: false}
})

const router = useRouter()

const go = () => {
  if (!props.to) return
  router.push(props.to)
}
</script>

<template>
  <div
      class="stat-card"
      :class="[`tone-${tone}`, { 'is-clickable': !!to, 'is-loading': loading }]"
      :role="to ? 'link' : undefined"
      :tabindex="to ? 0 : undefined"
      @click="go"
      @keydown.enter.prevent="go"
  >
    <div v-if="icon" class="stat-icon">
      <component :is="icon" :size="18"/>
    </div>
    <div class="stat-body">
      <div class="stat-label">{{ label }}</div>
      <div class="stat-value">
        <span v-if="loading" class="skeleton-line"/>
        <template v-else>
          {{ value }}<span v-if="unit" class="stat-unit">{{ unit }}</span>
        </template>
      </div>
      <div v-if="hint" class="stat-hint">{{ hint }}</div>
    </div>
    <!-- 有 to 才显示箭头：纯展示的指标卡加箭头会误导「点了会跳」 -->
    <ChevronRight v-if="to" :size="15" class="stat-arrow"/>
  </div>
</template>

<style scoped lang="scss">
.stat-card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 16px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  transition: box-shadow 0.18s, transform 0.18s, border-color 0.18s;

  &.is-clickable {
    cursor: pointer;

    &:hover {
      border-color: #fecaca;
      box-shadow: 0 6px 16px -8px rgba(239, 68, 68, 0.35);
      transform: translateY(-1px);
    }

    &:focus-visible {
      outline: 2px solid #fca5a5;
      outline-offset: 2px;
    }
  }

  .stat-icon {
    display: grid;
    place-items: center;
    width: 34px;
    height: 34px;
    border-radius: 10px;
    background: #f3f4f6;
    color: #4b5563;
    flex-shrink: 0;
  }

  .stat-arrow {
    margin-left: auto;
    align-self: center;
    color: #c0c4cc;
    flex-shrink: 0;
    transition: color 0.16s, transform 0.16s;
  }

  &.is-clickable:hover .stat-arrow {
    color: #dc2626;
    transform: translateX(2px);
  }

  .stat-body {
    min-width: 0;
  }

  .stat-label {
    font-size: 12px;
    color: #6b7280;
    margin-bottom: 4px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .stat-value {
    font-size: 22px;
    font-weight: 700;
    color: #111827;
    line-height: 1.2;
  }

  .stat-unit {
    margin-left: 2px;
    font-size: 13px;
    font-weight: 500;
    color: #6b7280;
  }

  .stat-hint {
    margin-top: 4px;
    font-size: 11px;
    color: #9ca3af;
  }

  &.tone-primary {
    border-color: #fecaca;

    .stat-icon {
      background: #fef2f2;
      color: #dc2626;
    }
  }

  &.tone-warn {
    .stat-icon {
      background: #fffbeb;
      color: #d97706;
    }

    .stat-value {
      color: #b45309;
    }
  }

  &.tone-danger {
    .stat-icon {
      background: #fef2f2;
      color: #dc2626;
    }

    .stat-value {
      color: #dc2626;
    }
  }

  &.tone-ok {
    .stat-icon {
      background: #ecfdf5;
      color: #059669;
    }

    .stat-value {
      color: #047857;
    }
  }

  .skeleton-line {
    display: inline-block;
    width: 48px;
    height: 22px;
    border-radius: 6px;
    background: linear-gradient(90deg, #f3f4f6, #e5e7eb, #f3f4f6);
    background-size: 200% 100%;
    animation: shimmer 1.2s infinite;
  }
}

@keyframes shimmer {
  from {
    background-position: 200% 0;
  }
  to {
    background-position: -200% 0;
  }
}
</style>
