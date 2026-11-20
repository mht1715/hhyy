<script setup>
import {useAuthStore} from '../store/auth'
import {useRouter, useRoute} from 'vue-router' // 补充引入 useRoute
import {X, ShieldCheck, Stethoscope, User, Headphones} from 'lucide-vue-next'
import {showToast} from 'vant' // 建议把 alert 换成 Vant 的 Toast
import {siteConfig as site} from '../config/site'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute() // 实例化 route

// 账号列表来自 src/config/site.js（落地页「按角色体验」用的是同一份），
// 这里只负责图标与配色——它们是组件和视觉细节，不属于站点信息
const ROLE_ICONS = {admin: ShieldCheck, doctor: Stethoscope, patient: User, support: Headphones}
const ROLE_BG = {admin: 'bg-red', doctor: 'bg-blue', patient: 'bg-green', support: 'bg-purple'}
const accounts = site.demo.accounts

const quickLogin = async (account) => {
  try {
    await auth.login(account.username)
    // 用 route.path 判断当前是否在游客首页
    if (route.path === '/') {
      router.push(account.homePath)
    }
  } catch (err) {
    showToast({type: 'fail', message: '登录失败，请确保后端服务已启动'})
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="auth.isLoginModalOpen" class="modal-overlay" @click.self="auth.isLoginModalOpen = false">
      <div class="modal-content">
        <button class="close-btn" @click="auth.isLoginModalOpen = false">
          <X :size="20"/>
        </button>

        <h2 class="title">{{ site.login.title }}</h2>
        <p class="subtitle">{{ site.login.subtitle }}</p>

        <div class="account-list">
          <div
              v-for="account in accounts"
              :key="account.username"
              class="account-card"
              @click="quickLogin(account)"
          >
            <div class="icon-wrapper" :class="ROLE_BG[account.role]">
              <component :is="ROLE_ICONS[account.role] || User" :size="28" color="white"/>
            </div>
            <div class="info">
              <div class="role-name">{{ account.title }}</div>
              <div class="username">{{ account.username }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped lang="scss">
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(2px);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;

  .modal-content {
    background: white;
    width: 440px;
    padding: 32px;
    border-radius: 16px;
    box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
    position: relative;
    animation: slideUp 0.3s ease-out;

    .close-btn {
      position: absolute;
      top: 16px;
      right: 16px;
      background: transparent;
      border: none;
      cursor: pointer;
      color: #9ca3af;
      padding: 4px;
      border-radius: 50%;
      display: flex;
      transition: all 0.2s;

      &:hover {
        background: #f3f4f6;
        color: #4b5563;
      }
    }

    .title {
      font-size: 20px;
      color: #111827;
      margin-bottom: 8px;
      text-align: center;
    }

    .subtitle {
      font-size: 13px;
      color: #6b7280;
      text-align: center;
      margin-bottom: 24px;
    }

    .account-list {
      display: flex;
      flex-direction: column;
      gap: 12px;

      .account-card {
        display: flex;
        align-items: center;
        gap: 16px;
        padding: 12px;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        cursor: pointer;
        transition: all 0.2s;

        &:hover {
          border-color: #ef4444;
          background: #fef2f2;
          transform: translateY(-2px);
          box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        }

        .icon-wrapper {
          width: 48px;
          height: 48px;
          border-radius: 10px;
          display: flex;
          justify-content: center;
          align-items: center;

          &.bg-red {
            background: #ef4444;
          }

          &.bg-blue {
            background: #3b82f6;
          }

          &.bg-green {
            background: #10b981;
          }

          &.bg-purple {
            background: #8b5cf6;
          }
        }

        .info {
          .role-name {
            font-weight: 600;
            color: #374151;
            font-size: 15px;
            margin-bottom: 2px;
          }

          .username {
            font-size: 13px;
            color: #9ca3af;
          }
        }
      }
    }
  }
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 768px) {
  .modal-overlay {
    .modal-content {
      width: 90% !important; // 手机上占屏幕 90%
      padding: 24px 16px !important;
      max-width: 400px;

      .account-list {
        .account-card {
          padding: 10px !important;

          .icon-wrapper {
            width: 40px !important;
            height: 40px !important;
          }

          .info {
            .role-name {
              font-size: 14px !important;
            }

            .username {
              font-size: 12px !important;
            }
          }
        }
      }
    }
  }
}
</style>