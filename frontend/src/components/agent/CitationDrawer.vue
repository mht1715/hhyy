<script setup>
import {computed, nextTick, ref, watch} from 'vue'
import {BookOpen, ExternalLink, X} from 'lucide-vue-next'

const props = defineProps({
  citations: {type: Array, default: () => []},
  modelValue: {type: Boolean, default: false},
  activeIndex: {type: [Number, String], default: null}
})

const emit = defineEmits(['update:modelValue'])

const listRef = ref(null)

const show = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const list = computed(() => (Array.isArray(props.citations) ? props.citations : []))

const isActive = (citation) => (
  props.activeIndex !== null
  && props.activeIndex !== undefined
  && Number(citation.index) === Number(props.activeIndex)
)

watch(
    () => [props.modelValue, props.activeIndex],
    async ([visible]) => {
      if (!visible) return
      await nextTick()
      if (!listRef.value) return
      const target = String(props.activeIndex)
      const items = listRef.value.querySelectorAll('.citation-item')
      for (const item of items) {
        if (item.dataset.citationIndex === target) {
          item.scrollIntoView({block: 'nearest'})
          break
        }
      }
    }
)
</script>

<template>
  <van-popup
      v-model:show="show"
      position="bottom"
      round
      teleport="body"
      :style="{ maxHeight: '72vh' }"
  >
    <div class="citation-drawer">
      <div class="drawer-header">
        <div class="drawer-title">
          <BookOpen :size="16" color="#ef4444"/>
          <span>引用来源</span>
          <span class="count">{{ list.length }}</span>
        </div>
        <button type="button" class="close-btn" aria-label="关闭" @click="show = false">
          <X :size="18"/>
        </button>
      </div>

      <div ref="listRef" class="citation-list">
        <van-empty v-if="list.length === 0" description="本次回答没有引用来源"/>

        <div
            v-for="(citation, index) in list"
            :key="citation.index !== undefined ? citation.index : index"
            class="citation-item"
            :class="{ active: isActive(citation) }"
            :data-citation-index="citation.index"
        >
          <div class="cite-index">{{ citation.index !== undefined ? citation.index : index + 1 }}</div>

          <div class="cite-body">
            <div class="cite-title">{{ citation.doc_title || '未命名文档' }}</div>

            <div class="cite-meta">
              <span v-if="citation.section" class="meta-chip section">{{ citation.section }}</span>
              <span
                  v-if="citation.page !== null && citation.page !== undefined"
                  class="meta-chip page"
              >
                第 {{ citation.page }} 页
              </span>
              <span v-if="citation.agent_code" class="meta-chip agent">{{ citation.agent_code }}</span>
            </div>

            <p v-if="citation.snippet" class="cite-snippet">{{ citation.snippet }}</p>

            <a
                v-if="citation.url"
                :href="citation.url"
                target="_blank"
                rel="noopener noreferrer"
                class="cite-link"
            >
              查看原文
              <ExternalLink :size="12"/>
            </a>
          </div>
        </div>
      </div>
    </div>
  </van-popup>
</template>

<style scoped lang="scss">
.citation-drawer {
  display: flex;
  flex-direction: column;
  max-height: 72vh;

  .drawer-header {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 16px 12px;
    border-bottom: 1px solid #f3f4f6;

    .drawer-title {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 15px;
      font-weight: 600;
      color: #111827;

      .count {
        min-width: 18px;
        height: 18px;
        padding: 0 5px;
        border-radius: 9px;
        background: #fef2f2;
        color: #ef4444;
        font-size: 11px;
        line-height: 18px;
        text-align: center;
      }
    }

    .close-btn {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 28px;
      height: 28px;
      border: none;
      border-radius: 50%;
      background: #f9fafb;
      color: #6b7280;
      cursor: pointer;

      &:hover {
        background: #f3f4f6;
        color: #374151;
      }
    }
  }

  .citation-list {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 12px 16px 20px;

    .citation-item {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 12px;
      margin-bottom: 10px;
      border: 1px solid #f3f4f6;
      border-radius: 10px;
      background: #fcfcfd;
      transition: border-color 0.15s ease, background-color 0.15s ease;

      &:last-child {
        margin-bottom: 0;
      }

      &.active {
        border-color: #fecaca;
        background: #fef2f2;
        box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.08);
      }

      .cite-index {
        flex-shrink: 0;
        width: 22px;
        height: 22px;
        border-radius: 50%;
        background: #ef4444;
        color: #fff;
        font-size: 11px;
        font-weight: 600;
        line-height: 22px;
        text-align: center;
      }

      .cite-body {
        flex: 1;
        min-width: 0;
      }

      .cite-title {
        font-size: 14px;
        font-weight: 600;
        color: #111827;
        line-height: 1.5;
        word-break: break-word;
      }

      .cite-meta {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin-top: 6px;

        .meta-chip {
          padding: 0 8px;
          border-radius: 8px;
          font-size: 11px;
          line-height: 18px;

          &.section {
            color: #2563eb;
            background: #eff6ff;
          }

          &.page {
            color: #6b7280;
            background: #f3f4f6;
          }

          &.agent {
            color: #b91c1c;
            background: #fee2e2;
          }
        }
      }

      .cite-snippet {
        margin-top: 8px;
        font-size: 13px;
        line-height: 1.7;
        color: #4b5563;
        white-space: pre-wrap;
        word-break: break-word;
      }

      .cite-link {
        display: inline-flex;
        align-items: center;
        gap: 3px;
        margin-top: 8px;
        font-size: 12px;
        color: #ef4444;
        text-decoration: none;

        &:hover {
          text-decoration: underline;
        }
      }
    }

    :deep(.van-empty) {
      padding: 32px 0;
    }
  }
}

@media (max-width: 768px) {
  .citation-drawer {
    .drawer-header {
      padding: 14px 12px 10px;
    }

    .citation-list {
      padding: 10px 12px 18px;

      .citation-item {
        padding: 10px;
      }
    }
  }
}
</style>
