<script setup>
/**
 * 全局壳：登录弹窗 + 导览 + 返回顶部。
 *
 * 这里多了一层 KeepAlive：用户在「药品广场 → 详情 → 返回」或「工作台 Tab → 别的页 → 回来」
 * 之后，筛选条件、已加载的列表、滚动位置都还在。否则每返回一次就重新请求一遍，
 * 面试官会明显感觉「点了就跳、回来还得重来」。
 *
 * 只缓存「列表型 / 工作台」页面：对话页和详情页带参数，缓存会让不同 id 复用同一实例。
 */
import LoginModal from './components/LoginModal.vue'
import GuideDrawer from './components/guide/GuideDrawer.vue'
import BackTop from './components/common/BackTop.vue'

// 与各页面 defineOptions({name}) 保持一致；新增页面时在这里登记一行
const CACHED = [
  'PatientView',
  'DoctorView',
  'AdminView',
  'DrugsView',
  'CartView',
  'AgentsView',
  'OrderView',
  'MemoryView',
  'ServiceView',
  'ProductView',
  'ObserveView',
  'PromptView',
  'KbListView',
  'SearchTestView'
]

const isCached = (name) => CACHED.includes(name)

/**
 * 只按「路由名 + 路径参数」做 key，**不要把 query 算进去**：
 * 对话页会在第一轮之后把 `?c=<会话 id>` 写进 URL，如果 key 含 query，
 * 每次写参数都会重建组件——正流式输出的回答会当场断掉。
 */
const pageKey = (route) => {
  if (isCached(route.name)) return String(route.name)
  const params = route.params || {}
  const id = params.id || params.code || params.conversationId || ''
  return `${String(route.name || route.path)}:${id}`
}
</script>

<template>
  <router-view v-slot="{ Component, route }">
    <!-- 注意：注释必须写在 <keep-alive> 外面——KeepAlive 只允许一个子节点，
         写在里面会被当成多出来的一个 child（dev 编译直接报错，build 因为去注释才看不出来） -->
    <keep-alive :include="CACHED" :max="10">
      <component :is="Component" :key="pageKey(route)"/>
    </keep-alive>
  </router-view>
  <LoginModal/>
  <GuideDrawer/>
  <BackTop/>
</template>
