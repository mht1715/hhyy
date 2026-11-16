<script setup>
import {useRouter} from 'vue-router'
import {Users, ShoppingCart, MessageSquare, TrendingUp, Settings, Database} from 'lucide-vue-next'

const router = useRouter()
// 模拟数据看板
const stats = [
  {title: '总注册用户', value: '1,284', icon: Users, color: '#3b82f6', bg: '#eff6ff'},
  {title: '今日新增订单', value: '56', icon: ShoppingCart, color: '#10b981', bg: '#ecfdf5'},
  {title: 'Agent 对话数', value: '8,392', icon: MessageSquare, color: '#f59e0b', bg: '#fffbeb'},
  {title: '系统负载', value: '32%', icon: TrendingUp, color: '#ef4444', bg: '#fef2f2'},
]

const recentOrders = [
  {id: 'ORD-20231116-001', user: 'patient_01', amount: '¥ 128.00', status: '已支付'},
  {id: 'ORD-20231116-002', user: 'doctor_02', amount: '¥ 345.50', status: '待发货'},
  {id: 'ORD-20231116-003', user: 'patient_03', amount: '¥ 89.90', status: '已发货'},
]
</script>

<template>
  <div class="admin-dashboard">
    <div class="dashboard-header">
      <h2>管理员工作台</h2>
      <p>欢迎回来，这里是花红医药 Agent 系统的全局概览。</p>
    </div>

    <!-- 数据统计卡片 -->
    <div class="stats-grid">
      <div class="stat-card" v-for="(item, index) in stats" :key="index">
        <div class="icon-box" :style="{ backgroundColor: item.bg, color: item.color }">
          <component :is="item.icon" :size="24"/>
        </div>
        <div class="stat-info">
          <div class="stat-title">{{ item.title }}</div>
          <div class="stat-value">{{ item.value }}</div>
        </div>
      </div>
    </div>

    <!-- 下方内容区 -->
    <div class="content-grid">
      <!-- 最近订单 -->
      <div class="panel recent-orders">
        <div class="panel-header">
          <h3>最近订单</h3>
          <a href="#">查看全部</a>
        </div>
        <table class="data-table">
          <thead>
          <tr>
            <th>订单号</th>
            <th>用户</th>
            <th>金额</th>
            <th>状态</th>
          </tr>
          </thead>
          <tbody>
          <tr v-for="order in recentOrders" :key="order.id">
            <td>{{ order.id }}</td>
            <td>{{ order.user }}</td>
            <td>{{ order.amount }}</td>
            <td><span class="status-badge">{{ order.status }}</span></td>
          </tr>
          </tbody>
        </table>
      </div>

      <!-- 快捷操作 -->
      <div class="panel quick-actions">
        <div class="panel-header">
          <h3>快捷操作</h3>
        </div>
        <div class="action-list">
          <button class="action-btn" @click="router.push('/products')">
            <Database :size="18"/>
            药品管理
          </button>
          <button class="action-btn">
            <Settings :size="18"/>
            Agent 提示词配置
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.admin-dashboard {
  max-width: 1200px;
  margin: 0 auto;
  padding: 32px 24px;

  .dashboard-header {
    margin-bottom: 32px;

    h2 {
      font-size: 24px;
      color: #111827;
      margin-bottom: 8px;
    }

    p {
      color: #6b7280;
    }
  }

  .stats-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 24px;
    margin-bottom: 32px;

    .stat-card {
      background: white;
      padding: 24px;
      border-radius: 12px;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
      display: flex;
      align-items: center;
      gap: 16px;

      .icon-box {
        width: 48px;
        height: 48px;
        border-radius: 10px;
        display: flex;
        justify-content: center;
        align-items: center;
      }

      .stat-info {
        .stat-title {
          font-size: 14px;
          color: #6b7280;
          margin-bottom: 4px;
        }

        .stat-value {
          font-size: 24px;
          font-weight: 700;
          color: #111827;
        }
      }
    }
  }

  .content-grid {
    display: grid;
    grid-template-columns: 2fr 1fr;
    gap: 24px;

    .panel {
      background: white;
      border-radius: 12px;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
      padding: 24px;

      .panel-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 20px;

        h3 {
          font-size: 16px;
          color: #374151;
        }

        a {
          font-size: 14px;
          color: #3b82f6;
          text-decoration: none;
        }
      }
    }

    .recent-orders {
      .data-table {
        width: 100%;
        border-collapse: collapse;

        th, td {
          text-align: left;
          padding: 12px;
          border-bottom: 1px solid #f3f4f6;
          font-size: 14px;
        }

        th {
          color: #6b7280;
          font-weight: 500;
        }

        td {
          color: #374151;
        }

        .status-badge {
          background: #ecfdf5;
          color: #10b981;
          padding: 4px 8px;
          border-radius: 4px;
          font-size: 12px;
        }
      }
    }

    .quick-actions {
      .action-list {
        display: flex;
        flex-direction: column;
        gap: 12px;

        .action-btn {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px 16px;
          background: #f9fafb;
          border: 1px solid #e5e7eb;
          border-radius: 8px;
          cursor: pointer;
          color: #374151;
          font-size: 14px;
          transition: all 0.2s;
          text-align: left;

          &:hover {
            background: #f3f4f6;
            border-color: #d1d5db;
          }
        }
      }
    }
  }
}

@media (max-width: 768px) {
  .admin-dashboard {
    padding: 16px 12px !important; // 减小边距

    .dashboard-header {
      margin-bottom: 20px !important;

      h2 {
        font-size: 20px !important;
      }
    }

    // 1. 统计卡片：从 4 列变成 2 列
    .stats-grid {
      grid-template-columns: repeat(2, 1fr) !important;
      gap: 12px !important;

      .stat-card {
        padding: 16px !important;
        gap: 12px !important;

        .icon-box {
          width: 36px !important;
          height: 36px !important;
        }

        .stat-info {
          .stat-value {
            font-size: 18px !important;
          }
        }
      }
    }

    // 2. 内容区：从两列变成垂直堆叠
    .content-grid {
      grid-template-columns: 1fr !important; // 变成 1 列
      gap: 16px !important;

      .panel {
        padding: 16px !important;
      }

      // 3. 表格适配（重点）：给表格容器加横向滚动，防止撑破屏幕
      .recent-orders {
        overflow-x: auto; // 允许横向滑动
        .data-table {
          min-width: 500px; // 保证表格列不被挤压变形，超出则滑动
        }
      }
    }
  }
}
</style>