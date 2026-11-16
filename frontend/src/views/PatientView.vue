<script setup>
import Navbar from '../components/Navbar.vue'
import LoginModal from '../components/LoginModal.vue'
</script>

<template>
  <div class="doctor-page">
    <Navbar/>
    <main style="text-align: center; padding: 100px;">
      <h2>病人工作台</h2>
      <p>此处将作为病人专属路由页面的开发起点...</p>
    </main>
    <LoginModal/>
  </div>
</template>