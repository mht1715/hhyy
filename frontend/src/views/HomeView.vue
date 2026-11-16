<script setup>
import Navbar from '../components/Navbar.vue'
import LoginModal from '../components/LoginModal.vue'
import {Sparkles} from 'lucide-vue-next'
</script>

<template>
  <div class="home-page">
    <Navbar/>
    <main class="main-content">
      <div class="welcome-card">
        <Sparkles :size="48" color="#ef4444"/>
        <h1>你好，游客！欢迎来到花红医药 Agent。</h1>
        <p>请点击右上角登录，体验不同角色下的智能工作台。</p>
      </div>
    </main>
    <LoginModal/>
  </div>
</template>

<style scoped lang="scss">
.home-page {
  min-height: 100vh;
  background-color: #f3f4f6;
  padding-top: 64px;

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