<script setup>
/**
 * 消息反馈条（挂在 assistant 气泡底部）。
 *
 * 👍 一步提交；👎 先选原因再提交（契约的 reason 是可选字段，但「为什么差」比「差」有用）。
 * 提交成功后本组件自己记住状态：同一条消息不重复提交，后端也不会给第二次机会（400）。
 */
import {computed, ref, watch} from 'vue'
import {showToast} from 'vant'
import {ThumbsUp, ThumbsDown} from 'lucide-vue-next'
import {sendFeedback} from '../../api/feedback'

const props = defineProps({
  messageId: {type: String, default: ''},
  feedback: {type: Object, default: null}
})

// 👎 的四个原因，与后端 feedback.reason 的演示取值保持一致
const REASONS = ['答非所问', '引用不对', '太啰嗦', '不该拒答']

const localSubmitted = ref(false)
const submitting = ref(false)
const showReasons = ref(false)

// 服务端已带回 feedback（历史消息 / 近期对话回放）时直接显示「已反馈」
const submitted = computed(() => {
  if (localSubmitted.value) return true
  return !!(props.feedback && props.feedback.rating)
})

// 换了一条消息（列表复用组件）时把展开态收起来
watch(() => props.messageId, () => {
  showReasons.value = false
})

const submit = async (rating, reason = '') => {
  if (!props.messageId || submitting.value || submitted.value) return
  submitting.value = true
  try {
    await sendFeedback({messageId: props.messageId, rating, reason})
    localSubmitted.value = true
    showReasons.value = false
    showToast({type: 'success', message: '已记录，我们会跟进'})
  } catch (e) {
    // 400 多为「重复提交」：当成已反馈收口，免得用户以为没点上一直点
    if (e && e.status === 400) {
      localSubmitted.value = true
      showReasons.value = false
      showToast({type: 'fail', message: (e && e.message) || '这条消息已经反馈过了'})
    } else {
      showToast({type: 'fail', message: (e && e.message) || '反馈失败，请稍后重试'})
    }
  } finally {
    submitting.value = false
  }
}

const submitUp = () => submit('up')

const toggleReasons = () => {
  if (submitting.value || submitted.value) return
  showReasons.value = !showReasons.value
}

const submitDown = (reason) => submit('down', reason)
</script>

<template>
  <div v-if="messageId" class="feedback-bar">
    <template v-if="submitted">
      <span class="feedback-done">已反馈</span>
    </template>

    <template v-else>
      <button
          type="button"
          class="fb-btn"
          :disabled="submitting"
          title="有帮助"
          aria-label="有帮助"
          @click="submitUp"
      >
        <ThumbsUp :size="14"/>
      </button>
      <button
          type="button"
          class="fb-btn"
          :class="{ 'is-open': showReasons }"
          :disabled="submitting"
          title="没帮助"
          aria-label="没帮助"
          @click="toggleReasons"
      >
        <ThumbsDown :size="14"/>
      </button>

      <div v-if="showReasons" class="reason-row">
        <span class="reason-label">哪里不好？</span>
        <button
            v-for="reason in REASONS"
            :key="reason"
            type="button"
            class="reason-chip"
            :disabled="submitting"
            @click="submitDown(reason)"
        >
          {{ reason }}
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped lang="scss">
.feedback-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;

  .fb-btn {
    width: 24px;
    height: 22px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    border: 1px solid transparent;
    border-radius: 6px;
    background: transparent;
    color: #9ca3af;
    cursor: pointer;
    transition: color 0.15s ease, background-color 0.15s ease, border-color 0.15s ease;

    &:hover:not(:disabled) {
      background: #fff;
      border-color: #e5e7eb;
      color: #ef4444;
    }

    &.is-open {
      color: #ef4444;
      background: #fff;
      border-color: #fecaca;
    }

    &:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }
  }

  .feedback-done {
    font-size: 11px;
    color: #9ca3af;
  }

  .reason-row {
    flex-basis: 100%;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    margin-top: 2px;
  }

  .reason-label {
    font-size: 11px;
    color: #9ca3af;
  }

  .reason-chip {
    padding: 1px 8px;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    background: #fff;
    color: #6b7280;
    font-size: 11px;
    line-height: 18px;
    cursor: pointer;
    transition: all 0.15s ease;

    &:hover:not(:disabled) {
      border-color: #fca5a5;
      background: #fef2f2;
      color: #b91c1c;
    }

    &:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }
  }
}
</style>
