<script setup>
import Navbar from '../components/Navbar.vue'
import LoginModal from '../components/LoginModal.vue'
import {useAuthStore} from '../store/auth'

const auth = useAuthStore()
</script>

<template>
  <div class="home-page">
    <Navbar/>

    <main class="main-content">
      <div class="welcome-card">
        <h1 v-if="!auth.isLoggedIn" class="greeting">
          你好，游客！欢迎来到花红医药 Agent。
        </h1>
        <h1 v-else class="greeting">
          你好，{{ auth.username }}！欢迎回来。
        </h1>
        <p class="subtitle">这是一个基于 LangGraph 构建的医药智能体系统。</p>
      </div>
    </main>

    <!-- 全局登录弹窗 -->
    <LoginModal/>
  </div>
</template>

<style scoped lang="scss">
.home-page {
  min-height: 100vh;
  background-color: #f3f4f6;

  .main-content {
    display: flex;
    justify-content: center;
    padding-top: 100px;

    .welcome-card {
      background: white;
      padding: 40px 60px;
      border-radius: 12px;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
      text-align: center;

      .greeting {
        font-size: 28px;
        color: #1f2937;
        margin-bottom: 12px;
      }

      .subtitle {
        color: #6b7280;
        font-size: 16px;
      }
    }
  }
}
</style>