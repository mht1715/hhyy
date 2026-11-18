<script setup>
import {computed} from 'vue'
import {marked} from 'marked'
import ContributorTags from './ContributorTags.vue'

const props = defineProps({
  message: {type: Object, required: true}
})

const emit = defineEmits(['cite'])

const CITATION_RE = /\[(\d{1,3})\]/g

// 只在真正的文本节点上替换 [n]，避免误伤链接、代码块和属性
const decorateCitations = (html) => {
  if (!html) return ''

  if (typeof DOMParser === 'undefined') {
    return html.replace(/\[(\d{1,3})\]/g, '<sup class="cite" data-index="$1">[$1]</sup>')
  }

  const doc = new DOMParser().parseFromString(`<div>${html}</div>`, 'text/html')
  const root = doc.body.firstElementChild
  if (!root) return html

  const walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT, null)
  const textNodes = []
  while (walker.nextNode()) {
    const node = walker.currentNode
    if (!node.nodeValue || !/\[\d{1,3}\]/.test(node.nodeValue)) continue
    const parent = node.parentElement
    if (parent && parent.closest('code, pre, a, sup')) continue
    textNodes.push(node)
  }

  textNodes.forEach((node) => {
    const text = node.nodeValue
    const fragment = doc.createDocumentFragment()
    let last = 0

    text.replace(CITATION_RE, (match, number, offset) => {
      if (offset > last) {
        fragment.appendChild(doc.createTextNode(text.slice(last, offset)))
      }
      const sup = doc.createElement('sup')
      sup.className = 'cite'
      sup.dataset.index = number
      sup.textContent = `[${number}]`
      fragment.appendChild(sup)
      last = offset + match.length
    })

    if (last < text.length) {
      fragment.appendChild(doc.createTextNode(text.slice(last)))
    }
    node.parentNode.replaceChild(fragment, node)
  })

  return root.innerHTML
}

const content = computed(() => props.message.content || '')
const isUser = computed(() => props.message.role === 'user')
// M3：人工客服消息单独一套气泡（左侧、蓝底、头像「客服」）
const isHumanAgent = computed(() => props.message.role === 'human_agent')
const isAssistant = computed(() => !isUser.value && !isHumanAgent.value)
const isStreaming = computed(() => props.message.status === 'streaming')
// 会话已由人工接管：AI 被静默，不能再显示「生成中 / 正在输入」
const silenced = computed(() => !!props.message.silenced)
const actorName = computed(() => (
  props.message.actor_name || props.message.actorName || '人工客服'
))
const bubbleClass = computed(() => {
  if (isUser.value) return 'is-user'
  if (isHumanAgent.value) return 'is-human'
  return 'is-assistant'
})
const contributors = computed(() => (Array.isArray(props.message.contributors) ? props.message.contributors : []))
const stopped = computed(() => !!props.message.stopped)

const html = computed(() => {
  if (!content.value) return ''
  const rendered = marked.parse(content.value, {breaks: true, gfm: true})
  return decorateCitations(typeof rendered === 'string' ? rendered : '')
})

const showBubble = computed(() => {
  if (isUser.value) return !!content.value
  if (isHumanAgent.value) return !!content.value
  return !!content.value
    || silenced.value
    || (isStreaming.value && !silenced.value)
    || contributors.value.length > 0
    || stopped.value
})

const showFooter = computed(() => (
  isAssistant.value && !silenced.value && (contributors.value.length > 0 || stopped.value)
))

const handleContentClick = (event) => {
  const target = event.target
  if (!target || typeof target.closest !== 'function') return
  const cite = target.closest('sup.cite[data-index]')
  if (!cite) return
  const index = Number(cite.dataset.index)
  if (!Number.isNaN(index)) emit('cite', index)
}
</script>

<template>
  <div
      v-if="showBubble"
      :class="['message-bubble', bubbleClass]"
  >
    <template v-if="isUser">
      <div class="bubble user-bubble">{{ content }}</div>
    </template>

    <template v-else-if="isHumanAgent">
      <div class="human-head">
        <span class="human-avatar">客服</span>
        <span class="human-name">{{ actorName }}</span>
      </div>
      <div class="bubble human-bubble">{{ content }}</div>
    </template>

    <template v-else>
      <div class="bubble assistant-bubble" :class="{ 'is-streaming': isStreaming && !silenced }">
        <div
            v-if="content"
            class="markdown-body"
            v-html="html"
            @click="handleContentClick"
        ></div>
        <div v-else-if="silenced" class="silenced-hint">客服已接入，消息将由客服回复</div>
        <div v-else-if="isStreaming" class="empty-thinking">
          <span class="dot"></span>
          <span class="dot"></span>
          <span class="dot"></span>
        </div>

        <div v-if="showFooter" class="bubble-footer">
          <ContributorTags v-if="contributors.length" :contributors="contributors"/>
          <span v-if="stopped" class="stopped-text">已停止生成</span>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped lang="scss">
.message-bubble {
  display: flex;
  flex-direction: column;
  max-width: 82%;

  &.is-user {
    align-self: flex-end;
    align-items: flex-end;
  }

  &.is-assistant {
    align-self: flex-start;
    align-items: flex-start;
  }

  &.is-human {
    align-self: flex-start;
    align-items: flex-start;

    .human-head {
      display: flex;
      align-items: center;
      gap: 6px;
      margin-bottom: 4px;
      padding-left: 2px;

      .human-avatar {
        width: 22px;
        height: 22px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 7px;
        background: linear-gradient(135deg, #3b82f6, #1d4ed8);
        color: #fff;
        font-size: 10px;
        font-weight: 600;
        letter-spacing: 0.5px;
      }

      .human-name {
        font-size: 12px;
        font-weight: 600;
        color: #2563eb;
      }
    }

    .human-bubble {
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      color: #1e3a8a;
      border-radius: 0 12px 12px 12px;
      white-space: pre-wrap;
    }
  }

  .bubble {
    max-width: 100%;
    padding: 10px 14px;
    font-size: 14px;
    line-height: 1.6;
    word-break: break-word;
  }

  .user-bubble {
    background: #ef4444;
    color: #fff;
    border-radius: 12px 0 12px 12px;
    white-space: pre-wrap;
  }

  .assistant-bubble {
    background: #f9fafb;
    color: #374151;
    border-radius: 0 12px 12px 12px;

    &.is-streaming :deep(.markdown-body > *:last-child::after) {
      content: '';
      display: inline-block;
      width: 6px;
      height: 14px;
      margin-left: 3px;
      border-radius: 2px;
      background: #ef4444;
      vertical-align: -2px;
      animation: bubble-blink 1s steps(1) infinite;
    }

    .empty-thinking {
      display: flex;
      align-items: center;
      gap: 4px;
      height: 20px;

      .dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: #fca5a5;
        animation: bubble-bounce 1.2s ease-in-out infinite;

        &:nth-child(2) {
          animation-delay: 0.15s;
        }

        &:nth-child(3) {
          animation-delay: 0.3s;
        }
      }
    }

    .silenced-hint {
      font-size: 12.5px;
      line-height: 1.6;
      color: #6b7280;
    }

    .bubble-footer {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      margin-top: 8px;

      .stopped-text {
        font-size: 11px;
        color: #9ca3af;
      }
    }
  }

  .markdown-body {
    font-size: 14px;
    line-height: 1.6;
    word-break: break-word;

    :deep(p) {
      margin-bottom: 8px;

      &:last-child {
        margin-bottom: 0;
      }
    }

    :deep(strong) {
      font-weight: 600;
      color: #b91c1c;
    }

    :deep(ul),
    :deep(ol) {
      padding-left: 20px;
      margin-bottom: 8px;
    }

    :deep(li) {
      margin-bottom: 4px;
    }

    :deep(br) {
      display: block;
      content: '';
      margin-top: 4px;
    }

    :deep(a) {
      color: #ef4444;
      text-decoration: underline;
      word-break: break-all;
    }

    :deep(code) {
      padding: 1px 4px;
      border-radius: 4px;
      background: #f3f4f6;
      font-size: 12.5px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }

    :deep(pre) {
      margin: 8px 0;
      padding: 10px 12px;
      border-radius: 8px;
      background: #0f172a;
      color: #e2e8f0;
      overflow-x: auto;

      code {
        padding: 0;
        background: transparent;
        color: inherit;
        font-size: 12.5px;
      }
    }

    :deep(blockquote) {
      margin: 8px 0;
      padding-left: 10px;
      border-left: 3px solid #fca5a5;
      color: #6b7280;
    }

    :deep(table) {
      width: 100%;
      margin: 8px 0;
      border-collapse: collapse;
      font-size: 13px;
    }

    :deep(th),
    :deep(td) {
      padding: 6px 8px;
      border: 1px solid #f3f4f6;
      text-align: left;
    }

    :deep(th) {
      background: #fef2f2;
      color: #b91c1c;
      font-weight: 600;
    }

    :deep(.cite) {
      display: inline-block;
      margin: 0 1px;
      padding: 0 4px;
      border-radius: 6px;
      background: #fef2f2;
      border: 1px solid #fecaca;
      color: #ef4444;
      font-size: 10px;
      font-weight: 700;
      line-height: 1.4;
      vertical-align: super;
      cursor: pointer;
      user-select: none;

      &:hover {
        background: #fee2e2;
      }
    }
  }
}

@keyframes bubble-blink {
  0%,
  50% {
    opacity: 1;
  }

  50.01%,
  100% {
    opacity: 0;
  }
}

@keyframes bubble-bounce {
  0%,
  80%,
  100% {
    transform: translateY(0);
    opacity: 0.6;
  }

  40% {
    transform: translateY(-4px);
    opacity: 1;
  }
}
</style>
