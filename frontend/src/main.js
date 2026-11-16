import {createApp} from 'vue'
import {createPinia} from 'pinia'
import App from './App.vue'
import router from './router'
import './styles/index.scss'
// 1. 引入 Vant 组件库
import Vant from 'vant'
// 2. 引入 Vant 样式文件
import 'vant/lib/index.css'

// 引入虚拟模块进行注册
import {registerSW} from 'virtual:pwa-register'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(Vant)
app.mount('#app')

// 注册 Service Worker
if ('serviceWorker' in navigator) {
    registerSW({
        onNeedRefresh() {
            console.log('检测到新内容，刷新即可更新到最新版本。')
            // 这里可以接入你的 UI 提示，比如弹出一个 Element Plus 的 Notification
            if (confirm('检测到新内容，是否刷新页面以更新？')) {
                window.location.reload()
            }
        },
        onOfflineReady() {
            console.log('应用已准备好离线工作。')
        },
    })
}