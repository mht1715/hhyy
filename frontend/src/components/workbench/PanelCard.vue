<script setup>
/**
 * 面板容器：统一「标题 + 说明 + 刷新 + loading / 空 / 错误重试」四种状态。
 *
 * 工作台里最容易写丑的地方是每个面板各写一套 loading 和空态——最后必然出现
 * 「有的转圈、有的白屏、有的显示 undefined」。把四种状态收进这里，页面只写内容。
 */
defineProps({
  title: {type: String, default: ''},
  desc: {type: String, default: ''},
  icon: {type: [Object, Function], default: null},
  loading: {type: Boolean, default: false},
  error: {type: String, default: ''},
  empty: {type: Boolean, default: false},
  emptyText: {type: String, default: '暂无数据'},
  emptyHint: {type: String, default: ''},
  rows: {type: Number, default: 3}, // 骨架屏行数
  flush: {type: Boolean, default: false} // 内容贴边（列表类）
})

defineEmits(['retry'])
</script>

<template>
  <section class="panel">
    <header v-if="title || $slots.extra" class="panel-head">
      <div class="panel-title">
        <span v-if="icon" class="panel-icon"><component :is="icon" :size="16"/></span>
        <div>
          <h3>{{ title }}</h3>
          <p v-if="desc">{{ desc }}</p>
        </div>
      </div>
      <div class="panel-extra">
        <slot name="extra"/>
      </div>
    </header>

    <div class="panel-body" :class="{ flush }">
      <div v-if="loading" class="panel-state">
        <div v-for="index in rows" :key="index" class="skeleton-row">
          <span class="skeleton-block"/>
          <span class="skeleton-block short"/>
        </div>
      </div>

      <div v-else-if="error" class="panel-state is-error">
        <span>{{ error }}</span>
        <button type="button" class="retry-btn" @click="$emit('retry')">重试</button>
      </div>

      <div v-else-if="empty" class="panel-state is-empty">
        <span>{{ emptyText }}</span>
        <small v-if="emptyHint">{{ emptyHint }}</small>
      </div>

      <slot v-else/>
    </div>
  </section>
</template>

<style scoped lang="scss">
.panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  overflow: hidden;

  .panel-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    padding: 16px 18px 12px;
    border-bottom: 1px solid #f3f4f6;

    .panel-title {
      display: flex;
      gap: 10px;
      min-width: 0;
    }

    .panel-icon {
      display: grid;
      place-items: center;
      width: 28px;
      height: 28px;
      border-radius: 8px;
      background: #fef2f2;
      color: #dc2626;
      flex-shrink: 0;
    }

    h3 {
      margin: 0;
      font-size: 14px;
      font-weight: 600;
      color: #111827;
    }

    p {
      margin: 2px 0 0;
      font-size: 12px;
      color: #9ca3af;
      line-height: 1.5;
    }

    .panel-extra {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
    }
  }

  .panel-body {
    flex: 1;
    padding: 14px 18px 16px;
    min-width: 0;

    &.flush {
      padding: 0;
    }
  }

  .panel-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    min-height: 96px;
    color: #9ca3af;
    font-size: 13px;
    text-align: center;

    small {
      font-size: 11px;
      color: #c0c4cc;
    }

    &.is-error {
      color: #b91c1c;

      .retry-btn {
        padding: 4px 12px;
        border: 1px solid #fecaca;
        border-radius: 999px;
        background: #fef2f2;
        color: #b91c1c;
        font-size: 12px;
        cursor: pointer;
      }
    }
  }

  .skeleton-row {
    display: flex;
    gap: 10px;
    width: 100%;
    margin-bottom: 10px;

    .skeleton-block {
      flex: 1;
      height: 14px;
      border-radius: 6px;
      background: linear-gradient(90deg, #f3f4f6, #e9ebee, #f3f4f6);
      background-size: 200% 100%;
      animation: shimmer 1.2s infinite;

      &.short {
        flex: 0 0 30%;
      }
    }
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
