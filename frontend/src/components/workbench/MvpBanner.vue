<script setup>
/**
 * MVP 说明条：一句话讲清楚「这是演示版、重点在哪、什么没做」。
 *
 * 常驻在每个页面顶部而不是弹一次就走——面试官中途刷新页面还能重新看到；
 * 可关闭并记住，避免挡住内容的视觉焦点。
 */
import {ref} from 'vue'
import {X} from 'lucide-vue-next'
import {openGuide} from '../../store/guide'

const KEY = 'hhyy.dismissed.mvp'
const dismissed = ref(false)
try {
  dismissed.value = window.localStorage.getItem(KEY) === '1'
} catch (e) {
  dismissed.value = false
}

const close = () => {
  dismissed.value = true
  try {
    window.localStorage.setItem(KEY, '1')
  } catch (e) {
    // 忽略隐私模式下的写入失败
  }
}
</script>

<template>
  <div v-if="!dismissed" class="mvp-banner">
    <span class="mvp-tag">MVP</span>
    <p>
      演示版，重点展示 <b>Agent 编排</b> 与 <b>RAG 检索</b>：
      多 Agent 路由、引用溯源、拒答边界、转人工、可评估。
      支付 / 物流 / 处方为模拟，不构成医疗建议。
    </p>
    <button type="button" class="mvp-link" @click="openGuide('intro')">看项目介绍</button>
    <button type="button" class="mvp-close" aria-label="关闭提示" @click="close">
      <X :size="14"/>
    </button>
  </div>
</template>

<style scoped lang="scss">
.mvp-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  margin-bottom: 14px;
  background: linear-gradient(90deg, #fef2f2, #fff7ed);
  border: 1px solid #fecaca;
  border-radius: 10px;
  font-size: 12px;
  line-height: 1.5;
  color: #7f1d1d;

  .mvp-tag {
    flex-shrink: 0;
    padding: 1px 7px;
    border-radius: 6px;
    background: #dc2626;
    color: #fff;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.5px;
  }

  p {
    flex: 1;
    margin: 0;
    min-width: 0;

    b {
      color: #b91c1c;
    }
  }

  .mvp-link {
    flex-shrink: 0;
    padding: 2px 10px;
    border: 1px solid #fca5a5;
    border-radius: 999px;
    background: #fff;
    color: #b91c1c;
    font-size: 11px;
    cursor: pointer;

    &:hover {
      background: #fef2f2;
    }
  }

  .mvp-close {
    flex-shrink: 0;
    display: grid;
    place-items: center;
    width: 22px;
    height: 22px;
    border: none;
    border-radius: 6px;
    background: transparent;
    color: #b91c1c;
    cursor: pointer;

    &:hover {
      background: rgba(220, 38, 38, 0.1);
    }
  }

  @media (max-width: 768px) {
    align-items: flex-start;
    flex-wrap: wrap;

    p {
      flex: 1 1 100%;
      order: 3;
    }

    .mvp-link {
      order: 2;
    }
  }
}
</style>
