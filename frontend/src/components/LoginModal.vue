<script setup>
import {useAuthStore} from '../store/auth'
import {X, ShieldCheck, Stethoscope, User} from 'lucide-vue-next'

const auth = useAuthStore()

const quickLogin = async (username) => {
  try {
    await auth.login(username)
  } catch (err) {
    alert('登录失败，请确保后端服务已启动')
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

        <h2 class="title">选择体验身份</h2>
        <p class="subtitle">系统内置了三种角色，点击即可快速登录体验对应权限</p>

        <div class="account-list">
          <!-- 管理员 -->
          <div class="account-card" @click="quickLogin('admin')">
            <div class="icon-wrapper bg-red">
              <ShieldCheck :size="28" color="white"/>
            </div>
            <div class="info">
              <div class="role-name">系统管理员</div>
              <div class="username">admin</div>
            </div>
          </div>

          <!-- 医生 -->
          <div class="account-card" @click="quickLogin('doctor')">
            <div class="icon-wrapper bg-blue">
              <Stethoscope :size="28" color="white"/>
            </div>
            <div class="info">
              <div class="role-name">平台医生</div>
              <div class="username">doctor</div>
            </div>
          </div>

          <!-- 患者 -->
          <div class="account-card" @click="quickLogin('patient')">
            <div class="icon-wrapper bg-green">
              <User :size="28" color="white"/>
            </div>
            <div class="info">
              <div class="role-name">普通患者</div>
              <div class="username">patient</div>
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
</style>