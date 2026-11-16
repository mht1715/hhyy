<script setup>
import {ref, watch} from 'vue'
import {Sparkles, Loader2} from 'lucide-vue-next'

const props = defineProps({
  isParsing: {type: Boolean, default: false},
  initialText: {type: String, default: ''}
})
const emit = defineEmits(['parse'])

// 默认提供一个极佳的测试用例
const text = ref(props.initialText || `帮我录个板蓝根颗粒，袋装的，卖25块，原价30，库存还有800件。
这药属于呼吸系统用药，是颗粒剂，规格是10克×20小袋，能放24个月。
功能主治是清热解毒、凉血利咽，用来治咽喉肿痛、口干咽燥，还有急性扁桃体炎。
成份是板蓝根，辅料有蔗糖和糊精。吃法是开水冲服，一次5到10克，一天3到4次。
禁忌和不良反应都没啥，写尚不明确就行。批号是国药准字Z45020920。
厂家是广西壮族自治区花红药业集团股份公司。`)
watch(() => props.initialText, (val) => {
  if (val) text.value = val
})

const handleParse = () => {
  if (!text.value.trim()) return
  emit('parse', text.value)
}
</script>

<template>
  <div class="agent-input-card">
    <div class="agent-header">
      <Sparkles :size="18" color="#ef4444"/>
      <span>AI 智能录入助手</span>
    </div>
    <div class="agent-input-row">
      <textarea
          v-model="text"
          rows="6"
          placeholder="请用自然语言描述药品信息，例如：录入花红片，妇科用药，价格25元，库存500..."
          :disabled="isParsing"
          @keydown.enter.prevent="handleParse"
      ></textarea>
      <button class="parse-btn" @click="handleParse" :disabled="isParsing">
        <Loader2 v-if="isParsing" :size="18" class="spin"/>
        <span v-else>解析并填表</span>
      </button>
    </div>
    <p class="tips">支持自然语言一键提取药品名称、分类、价格、库存、说明书等信息。</p>
  </div>
</template>

<style scoped lang="scss">
.agent-input-card {
  background: linear-gradient(to right, #fff, #fef2f2);
  border-radius: 12px;
  padding: 16px;
  border: 1px solid #fca5a5;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);

  .agent-header {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 600;
    color: #b91c1c;
    margin-bottom: 12px;
    font-size: 15px;
  }

  .agent-input-row {
    display: flex;
    gap: 12px;
    align-items: stretch;

    textarea {
      flex: 1;
      padding: 12px;
      border: 1px solid #d1d5db;
      border-radius: 8px;
      outline: none;
      font-size: 14px;
      font-family: inherit;
      resize: vertical;
      min-height: 80px;

      &:focus {
        border-color: #ef4444;
        box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.1);
      }
    }

    .parse-btn {
      background: #ef4444;
      color: white;
      border: none;
      padding: 0 24px;
      border-radius: 8px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      justify-content: center;
      align-items: center;
      gap: 6px;
      white-space: nowrap;

      &:disabled {
        background: #fca5a5;
        cursor: not-allowed;
      }
    }
  }

  .tips {
    margin-top: 8px;
    font-size: 12px;
    color: #9ca3af;
  }

  @media (max-width: 768px) {
    .agent-input-row {
      flex-direction: column;

      .parse-btn {
        padding: 12px;
      }
    }
  }
}
</style>