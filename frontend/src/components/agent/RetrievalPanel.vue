<script setup>
import {computed} from 'vue'
import {Database, ShieldX} from 'lucide-vue-next'

const props = defineProps({
  retrievals: {type: Array, default: () => []}
})

const list = computed(() => (Array.isArray(props.retrievals) ? props.retrievals : []))

const formatScore = (score) => {
  const value = Number(score)
  return Number.isFinite(value) ? value.toFixed(3) : '—'
}
</script>

<template>
  <div class="retrieval-panel">
    <div class="panel-title">
      <Database :size="13"/>
      <span>检索命中</span>
      <span class="count">{{ list.length }} 次</span>
    </div>

    <p v-if="list.length === 0" class="empty">本轮没有检索事件（可能直接回答）。</p>

    <div v-for="(item, index) in list" :key="index" class="retrieval-item">
      <div class="item-head">
        <span class="agent">{{ item.agent_code || 'agent' }}</span>
        <span v-if="item.top_score !== undefined && item.top_score !== null" class="score">
          top {{ formatScore(item.top_score) }}
        </span>
        <span v-if="item.refused" class="refused">
          <ShieldX :size="11"/>
          拒答
        </span>
        <span v-if="item.kb_ids && item.kb_ids.length" class="kb">
          {{ item.kb_ids.length }} 个库
        </span>
      </div>

      <div v-if="item.hits && item.hits.length" class="hits">
        <div v-for="(hit, hitIndex) in item.hits" :key="hitIndex" class="hit">
          <span class="hit-title">{{ hit.doc_title || '未命名文档' }}</span>
          <span v-if="hit.section" class="hit-section">{{ hit.section }}</span>
          <span v-if="hit.score !== undefined && hit.score !== null" class="hit-score">
            {{ formatScore(hit.score) }}
          </span>
        </div>
      </div>
      <p v-else class="no-hit">没有命中片段</p>
    </div>
  </div>
</template>

<style scoped lang="scss">
.retrieval-panel {
  padding: 10px 12px;
  border: 1px dashed #e5e7eb;
  border-radius: 10px;
  background: #fcfcfd;

  .panel-title {
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 12px;
    font-weight: 600;
    color: #6b7280;

    .count {
      margin-left: auto;
      font-weight: 400;
      color: #9ca3af;
    }
  }

  .empty {
    margin-top: 6px;
    font-size: 12px;
    color: #9ca3af;
  }

  .retrieval-item {
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px dashed #f3f4f6;

    &:first-of-type {
      border-top: none;
    }

    .item-head {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      font-size: 11px;

      .agent {
        padding: 0 6px;
        border-radius: 6px;
        background: #fef2f2;
        color: #b91c1c;
        line-height: 18px;
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      }

      .score {
        color: #059669;
        font-variant-numeric: tabular-nums;
      }

      .refused {
        display: inline-flex;
        align-items: center;
        gap: 2px;
        color: #dc2626;
      }

      .kb {
        color: #9ca3af;
      }
    }

    .hits {
      margin-top: 4px;

      .hit {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        padding: 2px 0;
        font-size: 11px;
        line-height: 1.6;

        .hit-title {
          color: #4b5563;
        }

        .hit-section {
          color: #2563eb;
        }

        .hit-score {
          margin-left: auto;
          color: #9ca3af;
          font-variant-numeric: tabular-nums;
        }
      }
    }

    .no-hit {
      margin-top: 4px;
      font-size: 11px;
      color: #9ca3af;
    }
  }
}
</style>
