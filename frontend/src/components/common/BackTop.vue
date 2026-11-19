<script setup>
/**
 * 全局「返回顶部」。
 *
 * 为什么放根组件而不是每页各加一个：工作台、观测页、药品广场都可能很长，
 * 各页自己实现必然出现「有的页有、有的页没有、位置还不在一个地方」。
 *
 * 监听 window 滚动（内部滚动列表不触发，这是有意的：那些列表自己滚自己的）。
 * 用 rAF 合并事件，避免滚动时每帧都改响应式状态。
 */
import {computed, onBeforeUnmount, onMounted, ref} from 'vue'
import {ArrowUp} from 'lucide-vue-next'

const visible = ref(false)
const scrollY = ref(0)
let ticking = false
let frame = 0

const onScroll = () => {
  if (ticking) return
  ticking = true
  frame = window.requestAnimationFrame(() => {
    scrollY.value = window.scrollY || document.documentElement.scrollTop || 0
    visible.value = scrollY.value > 480
    ticking = false
  })
}

const progress = computed(() => {
  const height = document.documentElement.scrollHeight - window.innerHeight
  if (height <= 0) return 0
  return Math.min(100, Math.round((scrollY.value / height) * 100))
})

const backToTop = () => {
  // 尊重「减少动效」偏好：系统开了减少动效就直接跳
  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  window.scrollTo({top: 0, behavior: reduce ? 'auto' : 'smooth'})
}

onMounted(() => {
  onScroll()
  window.addEventListener('scroll', onScroll, {passive: true})
  window.addEventListener('resize', onScroll, {passive: true})
})

onBeforeUnmount(() => {
  window.removeEventListener('scroll', onScroll)
  window.removeEventListener('resize', onScroll)
  if (frame) window.cancelAnimationFrame(frame)
})
</script>

<template>
  <Transition name="back-top">
    <button
        v-if="visible"
        type="button"
        class="back-top"
        aria-label="返回顶部"
        title="返回顶部"
        @click="backToTop"
    >
      <span class="ring" :style="{ '--p': `${progress}%` }"/>
      <ArrowUp :size="16"/>
    </button>
  </Transition>
</template>

<style scoped lang="scss">
.back-top {
  position: fixed;
  right: 18px;
  bottom: 84px;
  z-index: 940;
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border: 1px solid #e5e7eb;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(8px);
  color: #4b5563;
  cursor: pointer;
  box-shadow: 0 8px 20px -12px rgba(17, 24, 39, 0.5);
  transition: transform 0.16s, color 0.16s, border-color 0.16s;

  &:hover {
    transform: translateY(-2px);
    border-color: #fecaca;
    color: #b91c1c;
  }

  /* 进度环：纯 CSS conic-gradient，不引第三方组件 */
  .ring {
    position: absolute;
    inset: -3px;
    border-radius: 50%;
    background: conic-gradient(#dc2626 var(--p), transparent 0);
    mask: radial-gradient(farthest-side, transparent calc(100% - 2px), #000 calc(100% - 1px));
    -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 2px), #000 calc(100% - 1px));
    opacity: 0.55;
    pointer-events: none;
  }
}

@media (max-width: 768px) {
  .back-top {
    right: 12px;
    /* 让开底部 Tab 栏与导览浮标 */
    bottom: calc(132px + env(safe-area-inset-bottom, 0px));
    width: 38px;
    height: 38px;
  }
}

.back-top-enter-active,
.back-top-leave-active {
  transition: opacity 0.16s ease, transform 0.16s ease;
}

.back-top-enter-from,
.back-top-leave-to {
  opacity: 0;
  transform: translateY(6px);
}
</style>
