<script setup>
/**
 * 页面返回条：标题 + 返回按钮 + 右侧操作。
 *
 * 为什么单独抽：之前每个页面各写一套返回逻辑，出现了三种坏法——
 * 有的页面完全没有返回；有的写死 `router.back()`（直接打开链接时把人送出站外）；
 * 客服台干脆写死回「Agent 广场」，从药品详情进客服就再也回不去。
 * 现在统一走 utils/nav 的 goBackOr：有来源就 back，没有就落到 backTo。
 */
import {ArrowLeft} from 'lucide-vue-next'
import {useRouter} from 'vue-router'
import {goBackOr} from '../../utils/nav'

const props = defineProps({
  title: {type: String, default: ''},
  subtitle: {type: String, default: ''},
  // 没有历史记录时的兜底页
  backTo: {type: String, default: '/'},
  backLabel: {type: String, default: '返回'},
  // 吸顶：长列表滚动时返回按钮不会滚丢
  sticky: {type: Boolean, default: false}
})

const emit = defineEmits(['back'])

const router = useRouter()

const goBack = () => {
  emit('back')
  goBackOr(router, props.backTo)
}
</script>

<template>
  <header class="page-bar" :class="{ 'is-sticky': sticky }">
    <button type="button" class="back-btn" :aria-label="`${backLabel}上一页`" @click="goBack">
      <ArrowLeft :size="18"/>
      <span class="back-text">{{ backLabel }}</span>
    </button>

    <div class="bar-title">
      <strong v-if="title">{{ title }}</strong>
      <small v-if="subtitle" :title="subtitle">{{ subtitle }}</small>
    </div>

    <div class="bar-extra">
      <slot name="right"/>
    </div>
  </header>
</template>

<style scoped lang="scss">
.page-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: #fff;
  border: 1px solid #f3f4f6;
  border-radius: 12px;
  min-width: 0;

  &.is-sticky {
    position: sticky;
    // 顶栏是 fixed 64px，吸顶要落在它下面，否则会被盖住
    top: 72px;
    z-index: 20;
    box-shadow: 0 6px 18px -14px rgba(17, 24, 39, 0.6);
  }

  .back-btn {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    flex: none;
    height: 32px;
    padding: 0 10px 0 6px;
    border: 1px solid #e5e7eb;
    border-radius: 999px;
    background: #fff;
    color: #4b5563;
    font-size: 13px;
    cursor: pointer;
    transition: color 0.16s ease, border-color 0.16s ease, background-color 0.16s ease;

    &:hover {
      color: #dc2626;
      border-color: #fecaca;
      background: #fef2f2;
    }
  }

  .bar-title {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;

    strong {
      font-size: 15px;
      font-weight: 700;
      color: #111827;
      overflow-wrap: anywhere;
    }

    small {
      font-size: 12px;
      color: #6b7280;
      overflow-wrap: anywhere;
      display: -webkit-box;
      -webkit-line-clamp: 1;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
  }

  .bar-extra {
    flex: none;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  @media (max-width: 768px) {
    padding: 8px 10px;

    // 手机上「返回」两个字会挤掉标题，只留箭头（aria-label 已说明语义）
    .back-text {
      display: none;
    }

    .back-btn {
      width: 32px;
      padding: 0;
      justify-content: center;
    }

    .bar-title strong {
      font-size: 14px;
    }
  }
}
</style>
