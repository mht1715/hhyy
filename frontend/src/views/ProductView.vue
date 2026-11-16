<script setup>
import {ref, onMounted} from 'vue'
import {useRouter} from 'vue-router'
import Navbar from '../components/Navbar.vue'
import {Plus, Edit, Trash2, ArrowLeft} from 'lucide-vue-next'
import request from '../utils/request'
import {getProductsApi, createProductApi, updateProductApi, deleteProductApi} from '../api/product'

// 引入封装好的组件
import AgentInput from '../components/common/AgentInput.vue'
import ProductFormModal from '../components/product/ProductFormModal.vue'

const router = useRouter()
const products = ref([])
const loading = ref(false)

const isModalOpen = ref(false)
const isEdit = ref(false)
const currentFormData = ref({})
const isParsing = ref(false)

// 默认空表单，供手动新增使用
const defaultForm = {
  name: '', generic_name: '', image_url: '',
  price: 0, original_price: 0, stock: 0,
  spec: '', category: '大健康药品', dosage_form: '', shelf_life: '',
  indications: '', contraindications: '', precautions: '', adverse_reactions: '',
  approval_number: '', manufacturer: ''
}

const loadProducts = async () => {
  loading.value = true
  try {
    products.value = await getProductsApi()
  } catch (e) {
    alert(e.message)
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  isEdit.value = false
  currentFormData.value = {...defaultForm}
  isModalOpen.value = true
}

const openEdit = (row) => {
  isEdit.value = true
  currentFormData.value = {...row}
  isModalOpen.value = true
}

// 首页面的 Agent 解析
const handlePageAgentParse = async (text) => {
  isParsing.value = true
  try {
    const parsedData = await request.post('/agent/parse-product', {text})
    if (parsedData.error) {
      alert(parsedData.error)
      return
    }
    isEdit.value = false
    currentFormData.value = {...defaultForm, ...parsedData}
    isModalOpen.value = true
  } catch (e) {
    alert('解析失败：' + e.message)
  } finally {
    isParsing.value = false
  }
}

// 保存表单
const handleSave = async (formData) => {
  try {
    if (isEdit.value) {
      await updateProductApi(formData.id, formData)
    } else {
      await createProductApi(formData)
    }
    isModalOpen.value = false
    await loadProducts()
  } catch (e) {
    alert(e.message)
  }
}

const handleDelete = async (id) => {
  if (!confirm('确认删除该药品吗？')) return
  try {
    await deleteProductApi(id)
    await loadProducts()
  } catch (e) {
    alert(e.message)
  }
}

onMounted(loadProducts)
</script>

<template>
  <div class="product-page">
    <Navbar/>
    <div class="container">
      <div class="header-actions">
        <div class="left">
          <button class="back-btn" @click="router.back()">
            <ArrowLeft :size="18"/>
            返回
          </button>
          <h2>药品库管理</h2>
        </div>
        <button class="add-btn" @click="openCreate">
          <Plus :size="18"/>
          手动录入
        </button>
      </div>

      <!-- 页面级 Agent 输入框 -->
      <AgentInput :is-parsing="isParsing" @parse="handlePageAgentParse"/>

      <div class="table-wrapper">
        <table class="data-table" v-if="!loading">
          <thead>
          <tr>
            <th width="80">商品图</th>
            <th>药品信息</th>
            <th>分类 / 规格</th>
            <th>价格</th>
            <th>库存</th>
            <th width="140">操作</th>
          </tr>
          </thead>
          <tbody>
          <tr v-if="products.length === 0">
            <td colspan="6" style="text-align: center; color: #999; padding: 40px;">暂无药品数据，请录入或运行预置脚本
            </td>
          </tr>
          <tr v-for="item in products" :key="item.id">
            <td>
              <img
                  :src="item.image_url || ''"
                  class="prod-img" alt="图片"/>
            </td>
            <td>
              <div class="prod-name">{{ item.name }}</div>
              <div class="prod-generic">通用名：{{ item.generic_name }}</div>
            </td>
            <td>
              <div class="tag">{{ item.category }}</div>
              <div class="tag">{{ item.dosage_form }} / {{ item.spec }}</div>
            </td>
            <td>
              <div class="price">¥{{ item.price }}</div>
            </td>
            <td>{{ item.stock }}</td>
            <td>
              <button class="icon-btn edit" @click="openEdit(item)">
                <Edit :size="16"/>
                编辑
              </button>
              <button class="icon-btn delete" @click="handleDelete(item.id)">
                <Trash2 :size="16"/>
                删除
              </button>
            </td>
          </tr>
          </tbody>
        </table>
        <div v-else style="padding: 20px; text-align: center;">加载中...</div>
      </div>
    </div>

    <!-- 引入弹窗组件 -->
    <ProductFormModal
        :is-open="isModalOpen"
        :is-edit="isEdit"
        :initial-data="currentFormData"
        @close="isModalOpen = false"
        @save="handleSave"
    />
  </div>
</template>

<style scoped lang="scss">
.product-page {
  min-height: 100vh;
  background-color: #f3f4f6;
  padding-top: 64px;

  .container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 24px;

    .header-actions {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 20px;

      .left {
        display: flex;
        align-items: center;
        gap: 16px;

        h2 {
          color: #111827;
          font-size: 20px;
        }

        .back-btn {
          display: flex;
          align-items: center;
          gap: 4px;
          background: white;
          border: 1px solid #e5e7eb;
          padding: 8px 12px;
          border-radius: 6px;
          cursor: pointer;
          color: #4b5563;
        }
      }

      .add-btn {
        display: flex;
        align-items: center;
        gap: 6px;
        background: #ef4444;
        color: white;
        border: none;
        padding: 10px 16px;
        border-radius: 6px;
        cursor: pointer;
        font-weight: 600;
      }
    }

    .table-wrapper {
      background: white;
      border-radius: 12px;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
      overflow-y: auto;
      max-height: 500px;
      margin-top: 24px;

      .data-table {
        width: 100%;
        border-collapse: separate;
        border-spacing: 0;
        min-width: 800px;

        th, td {
          padding: 16px;
          text-align: left;
          border-bottom: 1px solid #f3f4f6;
        }

        th {
          background: #f9fafb;
          color: #6b7280;
          font-weight: 500;
          position: sticky;
          top: 0;
          z-index: 10;
          box-shadow: 0 1px 0 #e5e7eb;
        }

        .prod-img {
          width: 60px;
          height: 60px;
          object-fit: cover;
          border-radius: 6px;
          border: 1px solid #e5e7eb;
        }

        .prod-name {
          font-weight: 600;
          color: #111827;
          font-size: 15px;
          margin-bottom: 4px;
        }

        .prod-generic {
          font-size: 13px;
          color: #6b7280;
        }

        .tag {
          display: inline-block;
          background: #f3f4f6;
          border: 1px solid #e5e7eb;
          font-size: 12px;
          padding: 2px 8px;
          border-radius: 4px;
          color: #4b5563;
          margin-right: 4px;
          margin-bottom: 4px;
        }

        .price {
          font-size: 16px;
          font-weight: bold;
          color: #ef4444;
        }

        .icon-btn {
          background: transparent;
          border: none;
          cursor: pointer;
          padding: 6px;
          margin: 0 6px 0 0;
          border-radius: 4px;
          display: inline-flex;
          align-items: center;
          gap: 4px;

          &.edit {
            color: #3b82f6;
            background: #eff6ff;
            font-size: 13px;
          }

          &.delete {
            color: #ef4444;
            background: #fef2f2;
          }
        }
      }
    }
  }
}
</style>