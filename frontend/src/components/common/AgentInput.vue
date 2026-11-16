<script setup>
import {computed, ref} from 'vue'
import {Sparkles, ChevronDown, ChevronUp} from 'lucide-vue-next'

const props = defineProps({
  modelValue: {type: String, default: ''},
  isParsing: {type: Boolean, default: false}
})
const emit = defineEmits(['update:modelValue', 'parse'])

const isExpanded = ref(false)

const text = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

const toggleExpand = () => {
  if (props.isParsing) return
  isExpanded.value = !isExpanded.value
}

const handleParse = () => {
  if (props.isParsing) return
  if (!text.value.trim()) return
  emit('parse', text.value)
}
</script>

<template>
  <div class="agent-input-card">
    <div class="agent-header" @click="toggleExpand">
      <div class="title-left">
        <Sparkles :size="18" color="#ef4444"/>
        <span>AI 智能录入助手</span>
      </div>
      <div class="toggle-icon">
        <ChevronUp v-if="isExpanded" :size="20" color="#b91c1c"/>
        <ChevronDown v-else :size="20" color="#b91c1c"/>
      </div>
    </div>

    <div class="expand-wrapper" :class="{ 'is-expanded': isExpanded }">
      <div class="expand-content">
        <div class="agent-body">
          <van-field
              v-model="text"
              type="textarea"
              rows="3"
              autosize
              :disabled="isParsing"
              placeholder="请用自然语言描述药品信息..."
              class="custom-textarea"
          />

          <div class="agent-footer">
            <p class="tips">支持提取名称、分类、价格、说明书等。</p>
            <van-button
                type="danger"
                class="parse-btn"
                :loading="isParsing"
                loading-text="智能解析中..."
                @click="handleParse"
            >
              一键解析填表
            </van-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.agent-input-card {
  background: linear-gradient(to right, #fff, #fef2f2);
  border-radius: 12px;
  padding: 12px 16px;
  border: 1px solid #fca5a5;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  transition: all 0.3s ease;

  .agent-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    cursor: pointer;
    padding: 4px 0;

    .title-left {
      display: flex;
      align-items: center;
      gap: 8px;
      font-weight: 600;
      color: #b91c1c;
      font-size: 15px;
    }

    .toggle-icon {
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 4px;
      border-radius: 50%;
      background: rgba(239, 68, 68, 0.1);
    }
  }

  .expand-wrapper {
    display: grid;
    grid-template-rows: 0fr;
    transition: grid-template-rows 0.3s ease-in-out;

    &.is-expanded {
      grid-template-rows: 1fr;
    }

    .expand-content {
      overflow: hidden;
    }
  }

  .agent-body {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding-top: 12px;
  }

  :deep(.custom-textarea) {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    padding: 12px;
    transition: border-color 0.2s;

    &:focus-within {
      border-color: #ef4444;
      box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.1);
    }

    &.van-field--disabled {
      background: #f3f4f6;
    }

    .van-field__control {
      font-family: inherit;
      font-size: 14px;
      line-height: 1.6;
      color: #374151;
    }
  }

  .agent-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;

    .tips {
      font-size: 12px;
      color: #9ca3af;
      flex: 1;
    }

    .parse-btn {
      min-width: 120px;
      border-radius: 8px;
      font-weight: 600;
    }
  }

  @media (max-width: 768px) {
    .agent-footer {
      flex-direction: column;
      align-items: stretch;

      .tips {
        text-align: center;
        margin-bottom: 8px;
      }

      .parse-btn {
        width: 100%;
      }
    }
  }
}
</style>