/**
 * 导览抽屉的状态。放 store 是因为触发点有三个：右下角浮标、顶栏的 MVP 徽标、
 * 页面里的「去试试」按钮——它们散在不同组件里，各自管 state 会打架。
 */

import {reactive} from 'vue'

const state = reactive({
  open: false,
  tab: 'intro',
  // 从「去这里看」跳转后，目标页可以读它来决定要不要高亮某块
  focus: ''
})

export function openGuide(tab = 'intro', focus = '') {
  state.tab = tab
  state.focus = focus
  state.open = true
}

export function closeGuide() {
  state.open = false
}

export function setGuideTab(tab) {
  state.tab = tab
}

export function useGuideState() {
  return {state, openGuide, closeGuide, setGuideTab}
}

export default {useGuideState, openGuide, closeGuide, setGuideTab}
