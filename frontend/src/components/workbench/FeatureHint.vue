<script setup>
/**
 * 面板级提示条：说明「这块在展示什么能力」。
 *
 * 可关闭，关闭状态记在 localStorage（按 key 区分），下次进来不再打扰——
 * 面试官第一次需要它，第二次只想看数据。
 *
 * 标签（tags）是可点的：点了打开导览的「设计思考」，省得自己找。
 */
import {computed, ref} from 'vue'
import {Lightbulb, X} from 'lucide-vue-next'

const props = defineProps({
  title: {type: String, default: ''},
  text: {type: String, default: ''},
  tags: {type: Array, default: () => []}, // [{label, key}]
  storageKey: {type: String, default: 'hhyy.hint'}
})

const emit = defineEmits(['tag-click'])

const KEY = `hhyy.dismissed.${props.storageKey}`
const dismissed = ref(false)
try {
  dismissed.value = window.localStorage.getItem(KEY) === '1'
} catch (e) {
  dismissed.value = false
}

const visible = computed(() => !dismissed.value && !!props.text)

const close = () => {
  dismissed.value = true
  try {
    window.localStorage.setItem(KEY, '1')
  } catch (e) {
    // 隐私模式下 localStorage 会抛，忽略即可
  }
}
</script>

<template>
  <div v-if="visible" class="feature-hint">
    <Lightbulb :size="15" class="hint-icon"/>
    <div class="hint-body">
      <strong v-if="title">{{ title }}</strong>
      <span>{{ text }}</span>
      <div v-if="tags.length" class="hint-tags">
        <button
            v-for="tag in tags"
            :key="tag.key || tag.label"
            type="button"
            class="hint-tag"
            @click="emit('tag-click', tag)"
        >
          {{ tag.label }}
        </button>
      </div>
    </div>
    <button type="button" class="hint-close" aria-label="不再提示" @click="close">
      <X :size="14"/>
    </button>
  </div>
</template>

<style scoped lang="scss">
.feature-hint {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 12px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 10px;
  font-size: 12px;
  line-height: 1.6;
  color: #92400e;

  .hint-icon {
    flex-shrink: 0;
    margin-top: 2px;
    color: #d97706;
  }

  .hint-body {
    flex: 1;
    min-width: 0;

    strong {
      display: block;
      margin-bottom: 2px;
      color: #78350f;
    }
  }

  .hint-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 6px;
  }

  .hint-tag {
    padding: 2px 8px;
    border: 1px solid #fcd34d;
    border-radius: 999px;
    background: #fff;
    color: #b45309;
    font-size: 11px;
    cursor: pointer;

    &:hover {
      background: #fef3c7;
    }
  }

  .hint-close {
    flex-shrink: 0;
    display: grid;
    place-items: center;
    width: 22px;
    height: 22px;
    border: none;
    border-radius: 6px;
    background: transparent;
    color: #b45309;
    cursor: pointer;

    &:hover {
      background: #fef3c7;
    }
  }
}
</style>
