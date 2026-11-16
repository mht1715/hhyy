<script setup>
import Navbar from '../components/Navbar.vue'
import LoginModal from '../components/LoginModal.vue'
import AdminDashboard from "../components/AdminDashboard.vue";
</script>

<template>
  <div class="admin-page">
    <Navbar/>
    <!-- 这里可以独立定制管理员的布局背景等 -->
    <main class="main-content" style="background-color: #f3f4f6; min-height: calc(100vh - 64px);">
      <AdminDashboard></AdminDashboard>
    </main>
    <LoginModal/>
  </div>
</template>

<style scoped lang="scss">
.admin-page {
  min-height: 100vh;
  background-color: #f3f4f6;
  /* 留出空间 */
  padding-top: 64px;
}
</style>