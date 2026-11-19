<script setup>
/**
 * 工作台 Tab 栏：同一个组件在桌面是顶部药丸，在手机是底部 tab bar。
 *
 * 为什么不用 vant 的 Tabbar：桌面端不需要底部栏，而且这里的项要带图标 + 角标 +
 * 键盘可聚焦，自己写 30 行比覆盖组件样式更省事。
 */

const props = defineProps({
  tabs: {type: Array, default: () => []},
  active: {type: String, default: ''},
  variant: {type: String, default: 'top'} // top | bottom
})

const emit = defineEmits(['change'])

const pick = (tab) => {
  if (!tab || typeof tab.key !== 'string') return
  if (tab.key === props.active) return
  emit('change', tab.key)
}
</script>

<template>
  <nav class="tab-bar" :class="`tab-bar--${variant}`" role="tablist">
    <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        role="tab"
        class="tab-item"
        :class="{ 'is-active': tab.key === active }"
        :aria-selected="tab.key === active"
        @click="pick(tab)"
    >
      <component :is="tab.icon" v-if="tab.icon" :size="variant === 'bottom' ? 20 : 15"/>
      <span class="tab-label">{{ tab.label }}</span>
      <span v-if="tab.badge" class="tab-badge">{{ tab.badge }}</span>
    </button>
  </nav>
</template>

<style scoped lang="scss">
.tab-bar {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  scrollbar-width: none;

  &::-webkit-scrollbar {
    display: none;
  }

  .tab-item {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px 14px;
    border: 1px solid transparent;
    border-radius: 999px;
    background: transparent;
    color: #4b5563;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    white-space: nowrap;
    transition: background-color 0.18s, color 0.18s, border-color 0.18s;

    &:hover {
      background: #f9fafb;
      color: #b91c1c;
    }

    &:focus-visible {
      outline: 2px solid #fca5a5;
      outline-offset: 2px;
    }

    &.is-active {
      background: #fef2f2;
      border-color: #fecaca;
      color: #b91c1c;
    }
  }

  .tab-badge {
    min-width: 18px;
    padding: 0 5px;
    border-radius: 9px;
    background: #ef4444;
    color: #fff;
    font-size: 11px;
    line-height: 18px;
    text-align: center;
  }
}

/* 手机：底部固定栏，图标在上、文字在下 */
.tab-bar--bottom {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 900;
  gap: 0;
  padding: 6px 4px calc(6px + env(safe-area-inset-bottom, 0px));
  background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(12px);
  border-top: 1px solid #e5e7eb;
  overflow: visible;

  .tab-item {
    flex: 1;
    flex-direction: column;
    gap: 2px;
    padding: 4px 2px;
    border: none;
    border-radius: 8px;
    font-size: 11px;

    &.is-active {
      background: transparent;
      color: #dc2626;
    }
  }

  .tab-badge {
    position: absolute;
    top: 0;
    right: calc(50% - 22px);
  }
}
</style>
