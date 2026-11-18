<script setup>
import {ref, computed, onMounted} from 'vue'
import {useRouter} from 'vue-router'
import {showToast} from 'vant'
import {ArrowLeft, ShieldCheck, RefreshCw, Lock} from 'lucide-vue-next'
import Navbar from '../../components/Navbar.vue'
import {getKbPermissionsApi, updateKbPermissionsApi} from '../../api/kb'

const router = useRouter()

// 表格列：与后端 ALL_ROLES 保持一致
const ROLES = [
  {value: 'admin', label: '管理员', hint: '天然可见全部'},
  {value: 'doctor', label: '医生'},
  {value: 'patient', label: '患者'},
  {value: 'support', label: '客服'},
  {value: 'visitor', label: '访客'}
]

const matrix = ref([])
const loading = ref(true)
const savingId = ref('')
const lastLoadedAt = ref('')

// 用角色勾选状态的签名判断「有没有改过」，避免依赖 checkbox 的 change 事件
// （Vant 的 change 在程序回填时也会触发，会把刚保存的行又标成未保存）
const rolesSignature = (roles) =>
    ROLES.map((role) => `${role.value}:${roles[role.value] ? 1 : 0}`).join('|')
const isDirty = (row) => rolesSignature(row.roles) !== row.savedSignature
const dirtyCount = computed(() => matrix.value.filter((row) => isDirty(row)).length)

const shortId = (id) => (id ? String(id).slice(0, 8) : '—')

// 把后端矩阵整理成前端可编辑的结构：roles 固定 5 个键，避免列缺失
const normalize = (list) => {
  return (list || []).map((item) => {
    const granted = {}
    let visitorAvailable = false
    ;(item.rows || []).forEach((row) => {
      granted[row.role] = !!row.can_read
      if (row.role === 'visitor') visitorAvailable = true
    })
    const roles = {}
    ROLES.forEach((role) => {
      // admin 天然可见全部，UI 上固定勾选
      roles[role.value] = role.value === 'admin' ? true : !!granted[role.value]
    })
    return {
      kb_id: item.kb_id,
      kb_code: item.kb_code,
      roles,
      // 私有库后端不会返回 visitor 行，此时访客列不可编辑
      visitorAvailable,
      savedSignature: rolesSignature(roles)
    }
  })
}

const loadMatrix = async () => {
  loading.value = true
  try {
    const list = await getKbPermissionsApi()
    matrix.value = normalize(list)
    lastLoadedAt.value = new Date().toLocaleTimeString('zh-CN', {hour12: false})
  } catch (e) {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

const saveRow = async (row) => {
  if (savingId.value) return
  savingId.value = row.kb_id
  try {
    // 只提交 can_read 为 true 的项；后端按全量覆盖处理
    const permissions = ROLES
        .filter((role) => row.roles[role.value])
        .filter((role) => role.value !== 'visitor' || row.visitorAvailable)
        .map((role) => ({role: role.value, can_read: true}))

    const res = await updateKbPermissionsApi(row.kb_id, permissions)

    // 用后端的返回回填，保证页面与库里一致
    if (res && Array.isArray(res.rows)) {
      const granted = {}
      res.rows.forEach((item) => {
        granted[item.role] = !!item.can_read
      })
      ROLES.forEach((role) => {
        row.roles[role.value] = role.value === 'admin' ? true : !!granted[role.value]
      })
    }
    row.savedSignature = rolesSignature(row.roles)
    showToast({type: 'success', message: '已保存，≤30s 内生效', duration: 2500})
  } catch (e) {
    // 拦截器已提示
  } finally {
    savingId.value = ''
  }
}

onMounted(loadMatrix)
</script>

<template>
  <div class="kb-perm-page">
    <Navbar/>

    <div class="page-container">
      <button class="back-link" @click="router.push('/admin')">
        <ArrowLeft :size="16"/>
        返回工作台
      </button>

      <div class="page-header">
        <div class="title-block">
          <h2>
            <ShieldCheck :size="22"/>
            知识库权限矩阵
          </h2>
          <p>
            默认拒绝：没有勾选的角色检索不到该库。修改会失效 ACL 缓存，最多 30 秒生效。
          </p>
        </div>
        <div class="header-actions">
          <span v-if="lastLoadedAt" class="muted">加载于 {{ lastLoadedAt }}</span>
          <van-button size="small" plain round @click="loadMatrix">
            <RefreshCw :size="14"/>
            刷新
          </van-button>
        </div>
      </div>

      <div class="tips-grid">
        <div class="tip-card">
          <Lock :size="16"/>
          <div>
            <strong>默认拒绝</strong>
            <p>没有授权的角色一律不可检索，不存在「未配置 = 放行」。</p>
          </div>
        </div>
        <div class="tip-card">
          <ShieldCheck :size="16"/>
          <div>
            <strong>admin 天然可见</strong>
            <p>管理员列固定勾选且不可取消，避免把自己锁在门外。</p>
          </div>
        </div>
        <div class="tip-card">
          <RefreshCw :size="16"/>
          <div>
            <strong>缓存失效</strong>
            <p>保存时后端会递增 ACL 版本号，旧缓存自动过期（≤30s）。</p>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-header">
          <h3>库 × 角色</h3>
          <span class="muted">
            共 {{ matrix.length }} 个库
            <template v-if="dirtyCount > 0">· {{ dirtyCount }} 个库有未保存修改</template>
          </span>
        </div>

        <p class="panel-hint">
          访客列只对「公开」库可编辑；私有库的访客访问会被 ACL 直接拒绝。访客实际可见性由知识库的可见性字段决定。
        </p>

        <div v-if="loading" class="loading-wrap">
          <van-loading size="22">加载权限矩阵…</van-loading>
        </div>

        <van-empty v-else-if="matrix.length === 0" description="还没有知识库，先去创建并配置可见性"/>

        <div v-else class="matrix-wrap">
          <table class="matrix-table">
            <thead>
            <tr>
              <th class="kb-col">知识库</th>
              <th v-for="role in ROLES" :key="role.value" class="role-col">
                <div class="role-name">{{ role.label }}</div>
                <div class="role-en">{{ role.value }}</div>
              </th>
              <th class="action-col">操作</th>
            </tr>
            </thead>
            <tbody>
            <tr v-for="row in matrix" :key="row.kb_id">
              <td class="kb-col">
                <div class="kb-code">{{ row.kb_code }}</div>
                <div class="kb-id">{{ shortId(row.kb_id) }}</div>
                <span v-if="isDirty(row)" class="dirty-dot">未保存</span>
              </td>
              <td
                  v-for="role in ROLES"
                  :key="role.value"
                  class="role-col cell"
                  :class="{disabled: role.value === 'visitor' && !row.visitorAvailable}"
              >
                <van-checkbox
                    v-model="row.roles[role.value]"
                    shape="square"
                    :disabled="role.value === 'admin' || (role.value === 'visitor' && !row.visitorAvailable)"
                />
                <div v-if="role.value === 'admin'" class="cell-hint">固定</div>
                <div v-else-if="role.value === 'visitor' && !row.visitorAvailable" class="cell-hint">私有库</div>
              </td>
              <td class="action-col">
                <van-button
                    size="small"
                    round
                    :type="isDirty(row) ? 'danger' : 'default'"
                    :disabled="!isDirty(row)"
                    :loading="savingId === row.kb_id"
                    @click="saveRow(row)"
                >
                  保存
                </van-button>
              </td>
            </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.kb-perm-page {
  min-height: 100vh;
  background: #f3f4f6;
  padding-top: 64px;
  padding-bottom: 32px;

  .page-container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 24px;
  }

  .back-link {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    border: none;
    background: transparent;
    color: #6b7280;
    font-size: 13px;
    padding: 0;
    margin-bottom: 12px;
    cursor: pointer;

    &:hover {
      color: #ef4444;
    }
  }

  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;
    margin-bottom: 16px;

    .title-block {
      h2 {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 22px;
        color: #111827;
        margin-bottom: 6px;
      }

      p {
        font-size: 13px;
        color: #6b7280;
      }
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-shrink: 0;
    }

    .muted {
      font-size: 12px;
      color: #9ca3af;
    }
  }

  .tips-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    margin-bottom: 20px;

    .tip-card {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      background: #fff;
      border-radius: 10px;
      padding: 14px 16px;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
      color: #3b82f6;

      strong {
        display: block;
        font-size: 13px;
        color: #374151;
        margin-bottom: 2px;
      }

      p {
        font-size: 12px;
        color: #9ca3af;
        line-height: 1.5;
      }
    }
  }

  .panel {
    background: #fff;
    border-radius: 12px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    padding: 20px 24px;
    margin-bottom: 20px;

    .panel-header {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 6px;

      h3 {
        font-size: 16px;
        color: #374151;
      }
    }

    .panel-hint {
      font-size: 12px;
      color: #9ca3af;
      margin-bottom: 14px;
      line-height: 1.6;
    }

    .muted {
      font-size: 13px;
      color: #9ca3af;
    }

    .loading-wrap {
      padding: 48px 0;
      display: flex;
      justify-content: center;
    }
  }

  .matrix-wrap {
    overflow-x: auto;
    border: 1px solid #f3f4f6;
    border-radius: 8px;
  }

  .matrix-table {
    width: 100%;
    border-collapse: collapse;
    min-width: 760px;

    th,
    td {
      border-bottom: 1px solid #f3f4f6;
      padding: 12px 10px;
      font-size: 13px;
      color: #374151;
      text-align: center;
    }

    th {
      background: #f9fafb;
      font-weight: 500;
      color: #6b7280;
      position: sticky;
      top: 0;
    }

    tbody tr:hover {
      background: #fafafa;
    }

    .kb-col {
      text-align: left;
      padding-left: 16px;
      position: sticky;
      left: 0;
      background: #fff;
      z-index: 1;
      min-width: 190px;
      border-right: 1px solid #f3f4f6;
    }

    thead .kb-col {
      background: #f9fafb;
      z-index: 2;
    }

    .kb-code {
      font-weight: 600;
      color: #111827;
      font-size: 13px;
      word-break: break-all;
    }

    .kb-id {
      font-size: 11px;
      color: #9ca3af;
      margin-top: 2px;
    }

    .dirty-dot {
      display: inline-block;
      margin-top: 6px;
      font-size: 11px;
      color: #d97706;
      background: #fffbeb;
      border-radius: 8px;
      padding: 1px 6px;
    }

    .role-col {
      width: 88px;
    }

    .role-name {
      font-size: 13px;
      color: #4b5563;
    }

    .role-en {
      font-size: 11px;
      color: #9ca3af;
      font-weight: 400;
    }

    .cell {
      .cell-hint {
        margin-top: 4px;
        font-size: 11px;
        color: #d1d5db;
      }

      &.disabled {
        opacity: 0.6;
      }
    }

    .action-col {
      width: 92px;
    }
  }

  @media (max-width: 900px) {
    .tips-grid {
      grid-template-columns: 1fr;
    }
  }

  @media (max-width: 768px) {
    .page-container {
      padding: 12px;
    }

    .page-header {
      flex-direction: column;
      align-items: stretch;

      .title-block h2 {
        font-size: 19px;
      }
    }

    .panel {
      padding: 16px 12px;
    }
  }
}
</style>
