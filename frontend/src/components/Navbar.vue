<script setup>
import {computed, ref} from 'vue'
import {useAuthStore} from '../store/auth'
import {useRoute, useRouter} from 'vue-router'
import {Bot, Hexagon, UserCircle, ChevronDown, LogOut, RefreshCw} from 'lucide-vue-next'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const isDropdownOpen = ref(false)

const isAgentsActive = computed(() => route.path === '/agents' || route.path.startsWith('/agents/'))

const toggleDropdown = () => {
  if (auth.isLoggedIn) {
    isDropdownOpen.value = !isDropdownOpen.value
  } else {
    auth.isLoginModalOpen = true // 触发弹窗
  }
}

const switchAccount = async (username, rolePath) => {
  try {
    await auth.login(username)
    isDropdownOpen.value = false
    router.push(rolePath)
  } catch (e) {
    alert('切换失败')
  }
}

const handleLogout = () => {
  auth.logout()
  isDropdownOpen.value = false
  router.push('/')
}

const roleColorMap = {admin: '#ef4444', doctor: '#3b82f6', patient: '#10b981'}
const roleNameMap = {admin: '管理员', doctor: '医生', patient: '患者'}
</script>

<template>
  <header class="navbar">
    <!-- 左侧 Logo 不变 -->
    <div class="left-brand">
      <Hexagon color="#ef4444" :size="28" fill="#ef4444"/>
      <span class="brand-name">花红agent（demo）</span>
    </div>

    <nav class="nav-links">
      <RouterLink to="/agents" class="nav-link" :class="{ active: isAgentsActive }">
        <Bot :size="16"/>
        <span>Agent 广场</span>
      </RouterLink>
    </nav>

    <div class="right-user">
      <div v-if="!auth.isLoggedIn" class="login-btn" @click="auth.isLoginModalOpen = true">
        点击登录
      </div>

      <div v-else class="user-profile">
        <div class="profile-trigger" @click="toggleDropdown">
          <UserCircle :size="24" color="#4b5563"/>
          <span class="username">{{ auth.username }}</span>
          <span class="role-badge" :style="{ backgroundColor: roleColorMap[auth.role] }">
            {{ roleNameMap[auth.role] }}
          </span>
          <ChevronDown :size="16" class="arrow" :class="{ 'is-open': isDropdownOpen }"/>
        </div>

        <!-- 下拉菜单 -->
        <div v-if="isDropdownOpen" class="dropdown-menu">
          <div class="dropdown-header">
            <RefreshCw :size="14"/>
            快捷切换账号
          </div>
          <div class="dropdown-item" @click="switchAccount('admin', '/admin')">admin (管理员)</div>
          <div class="dropdown-item" @click="switchAccount('doctor', '/doctor')">doctor (医生)</div>
          <div class="dropdown-item" @click="switchAccount('patient', '/patient')">patient (患者)</div>
          <div class="dropdown-divider"></div>
          <div class="dropdown-item text-danger" @click="handleLogout">
            <LogOut :size="14"/>
            退出登录
          </div>
        </div>
      </div>
    </div>

    <div v-if="isDropdownOpen" class="dropdown-overlay" @click="isDropdownOpen = false"></div>
  </header>
</template>

<style scoped lang="scss">
.navbar {
  height: 64px;
  /* 核心：固定定位 */
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 1000;

  /* 毛玻璃质感（半透明白底 + 背景模糊） */
  background-color: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px); /* 兼容 Safari */
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);

  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 24px;

  .left-brand {
    display: flex;
    align-items: center;
    gap: 12px;
    white-space: nowrap;

    .brand-name {
      font-size: 18px;
      font-weight: 700;
      color: #1f2937;
      letter-spacing: 0.5px;
    }
  }

  .nav-links {
    display: flex;
    align-items: center;
    margin-left: auto;
    margin-right: 18px;

    .nav-link {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 6px 12px;
      border-radius: 999px;
      color: #4b5563;
      font-size: 13px;
      font-weight: 500;
      text-decoration: none;
      white-space: nowrap;
      transition: background-color 0.2s, color 0.2s;

      &:hover {
        background: #f9fafb;
        color: #ef4444;
      }

      &.active {
        background: #fef2f2;
        color: #b91c1c;
      }
    }
  }

  .right-user {
    .login-btn {
      color: #ef4444;
      font-weight: 600;
      cursor: pointer;
      padding: 8px 16px;
      border-radius: 6px;
      border: 1px solid #fca5a5;
      background: #fef2f2;
      transition: all 0.2s;

      &:hover {
        background: #fee2e2;
      }
    }

    .user-profile {
      position: relative;

      .profile-trigger {
        display: flex;
        align-items: center;
        gap: 8px;
        cursor: pointer;
        padding: 6px 12px;
        border-radius: 20px;
        transition: background 0.2s;

        &:hover {
          background: #f3f4f6;
        }

        .username {
          font-size: 14px;
          font-weight: 500;
          color: #374151;
        }

        .role-badge {
          font-size: 12px;
          color: white;
          padding: 2px 8px;
          border-radius: 10px;
        }

        .arrow {
          color: #6b7280;
          transition: transform 0.2s;

          &.is-open {
            transform: rotate(180deg);
          }
        }
      }

      .dropdown-menu {
        position: absolute;
        top: 48px;
        right: 0;
        width: 220px;
        background: white;
        border-radius: 8px;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
        border: 1px solid #e5e7eb;
        padding: 8px 0;
        z-index: 1001;

        .dropdown-header {
          font-size: 12px;
          color: #9ca3af;
          padding: 8px 16px;
          display: flex;
          align-items: center;
          gap: 6px;
          font-weight: 600;
        }

        .dropdown-item {
          padding: 10px 16px;
          font-size: 14px;
          color: #374151;
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 8px;

          &:hover {
            background: #f3f4f6;
          }

          &.text-danger {
            color: #ef4444;

            &:hover {
              background: #fef2f2;
            }
          }
        }

        .dropdown-divider {
          height: 1px;
          background: #e5e7eb;
          margin: 6px 0;
        }
      }
    }
  }

  .dropdown-overlay {
    position: fixed;
    inset: 0;
    z-index: 99;
    background: transparent;
  }
}

@media (max-width: 768px) {
  .navbar {
    padding: 0 12px !important; // 减小两侧留白

    .left-brand {
      gap: 8px !important;

      .brand-name {
        font-size: 15px !important; // 调小 Logo 文字，给广场入口留位置
      }
    }

    .nav-links {
      margin-right: 6px !important;

      .nav-link {
        gap: 3px !important;
        padding: 4px 8px !important;
        font-size: 11px !important;

        svg {
          width: 14px;
          height: 14px;
        }
      }
    }

    .right-user {
      .login-btn {
        padding: 6px 10px !important;
        font-size: 12px !important;
        white-space: nowrap;
      }

      .user-profile {
        .profile-trigger {
          padding: 4px 8px !important;
          gap: 4px !important;

          .username {
            display: none; // 手机端隐藏用户名，只留头像和角色
          }

          .role-badge {
            font-size: 11px !important;
            padding: 1px 6px !important;
          }
        }
      }
    }
  }
}
</style>