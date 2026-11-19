<script setup>
/**
 * 工作台外壳：四个角色共用同一套排版契约。
 *
 * 结构：
 *   Navbar
 *   ├─ MVP 说明条（可关）
 *   ├─ 标题区（角色徽标 / 标题 / 副标题 / 右侧操作）
 *   ├─ Tab 栏（桌面顶部药丸 / 手机底部固定）
 *   └─ 内容区（切换时淡入，避免整页闪白）
 *
 * 为什么 Tab 用组件内 state 而不是嵌套路由：工作台切换是「同一屏换数据」，
 * 用嵌套路由会让每个 Tab 都变成一次页面级导航（滚动位置、加载态全丢）。
 * 但仍然把 tab 写进 URL（页面自己用 ?tab= 同步），刷新和分享都还能落到原位。
 */
import {RefreshCw} from 'lucide-vue-next'
import Navbar from '../Navbar.vue'
import MvpBanner from './MvpBanner.vue'
import TabBar from './TabBar.vue'

defineProps({
  role: {type: String, default: 'patient'},
  roleLabel: {type: String, default: ''},
  title: {type: String, default: ''},
  subtitle: {type: String, default: ''},
  tabs: {type: Array, default: () => []},
  active: {type: String, default: ''},
  refreshing: {type: Boolean, default: false},
  updatedAt: {type: String, default: ''},
  banner: {type: Boolean, default: true}
})

defineEmits(['update:active', 'refresh'])
</script>

<template>
  <div class="wb" :class="`wb--${role}`">
    <Navbar/>

    <div class="wb-wrap">
      <MvpBanner v-if="banner"/>

      <header class="wb-head">
        <div class="wb-heading">
          <span class="role-chip">{{ roleLabel || role }}</span>
          <h1>{{ title }}</h1>
          <p v-if="subtitle">{{ subtitle }}</p>
        </div>
        <div class="wb-actions">
          <slot name="actions"/>
          <button
              v-if="tabs.length"
              type="button"
              class="wb-refresh"
              :disabled="refreshing"
              @click="$emit('refresh')"
          >
            <RefreshCw :size="14" :class="{ spinning: refreshing }"/>
            <span>{{ refreshing ? '刷新中' : '刷新' }}</span>
          </button>
          <span v-if="updatedAt" class="wb-updated">更新于 {{ updatedAt }}</span>
        </div>
      </header>

      <TabBar
          v-if="tabs.length"
          class="wb-tabs-top"
          :tabs="tabs"
          :active="active"
          @change="$emit('update:active', $event)"
      />

      <!-- 不用 <Transition :key="active">：那会强制卸载整个面板，
           聊天类 Tab（SSE 流式）一换 Tab 就断流。改成「子元素挂载时淡入」，
           需要保活的 Tab 自己用 v-show 留在 DOM 里。 -->
      <main class="wb-body">
        <slot/>
      </main>
    </div>

    <TabBar
        v-if="tabs.length"
        class="wb-tabs-bottom"
        variant="bottom"
        :tabs="tabs"
        :active="active"
        @change="$emit('update:active', $event)"
    />
  </div>
</template>

<style scoped lang="scss">
.wb {
  min-height: 100vh;
  padding-top: 64px;
  background: #f5f6f8;

  .wb-wrap {
    max-width: 1180px;
    margin: 0 auto;
    padding: 16px 20px 32px;
  }

  .wb-head {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 16px;
    padding: 4px 2px 14px;
    flex-wrap: wrap;

    .wb-heading {
      min-width: 0;

      .role-chip {
        display: inline-block;
        margin-bottom: 6px;
        padding: 1px 8px;
        border-radius: 6px;
        background: #eef2ff;
        color: #4338ca;
        font-size: 11px;
        font-weight: 600;
      }

      h1 {
        margin: 0;
        font-size: 22px;
        font-weight: 700;
        color: #111827;
        letter-spacing: 0.2px;
      }

      p {
        margin: 4px 0 0;
        font-size: 13px;
        color: #6b7280;
      }
    }

    .wb-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;

      .wb-refresh {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 6px 12px;
        border: 1px solid #e5e7eb;
        border-radius: 999px;
        background: #fff;
        color: #4b5563;
        font-size: 12px;
        cursor: pointer;

        &:disabled {
          opacity: 0.6;
          cursor: default;
        }

        .spinning {
          animation: spin 0.9s linear infinite;
        }
      }

      .wb-updated {
        font-size: 11px;
        color: #9ca3af;
      }
    }
  }

  .wb-tabs-top {
    padding-bottom: 14px;
    border-bottom: 1px solid #e5e7eb;
    margin-bottom: 16px;
  }

  .wb-body {
    display: flex;
    flex-direction: column;
    gap: 14px;

    /* 面板首次挂载时淡入：换 Tab 的「衔接感」来自这里，而不是整页跳转 */
    > * {
      animation: wb-in 0.16s ease both;
    }
  }
}

@keyframes wb-in {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .wb .wb-body > * {
    animation: none;
  }
}

/* 角色色彩：只影响徽标与强调色，布局完全一致 */
.wb--doctor .role-chip {
  background: #eff6ff;
  color: #1d4ed8;
}

.wb--patient .role-chip {
  background: #ecfdf5;
  color: #047857;
}

.wb--support .role-chip {
  background: #f5f3ff;
  color: #6d28d9;
}

.wb--admin .role-chip {
  background: #fef2f2;
  color: #b91c1c;
}

.wb-tabs-bottom {
  display: none;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 768px) {
  .wb {
    padding-top: 60px;

    .wb-wrap {
      padding: 12px 12px calc(84px + env(safe-area-inset-bottom, 0px));
    }

    .wb-head {
      align-items: flex-start;
      padding-bottom: 10px;

      .wb-heading h1 {
        font-size: 19px;
      }

      .wb-actions {
        .wb-updated {
          display: none;
        }
      }
    }

    .wb-tabs-top {
      display: none;
    }

    .wb-tabs-bottom {
      display: flex;
    }
  }
}
</style>
