<script setup>
// KeepAlive 依赖组件名（App.vue 的 CACHED 白名单按 name 匹配）
defineOptions({name: 'ProductView'})

import {ref, onMounted, computed} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import Navbar from '../components/Navbar.vue'
import {showToast, showConfirmDialog} from 'vant'
import {getProductsApi, createProductApi, updateProductApi, deleteProductApi} from '../api/product'
import {parseProductApi} from '../api/agent'
import {goBackOr} from '../utils/nav'

import AgentInput from '../components/common/AgentInput.vue'
import ProductFormModal from '../components/product/ProductFormModal.vue'
import ProductCard from '../components/product/ProductCard.vue'

const router = useRouter()
const route = useRoute()
const products = ref([])
const loading = ref(false)

const isModalOpen = ref(false)
const isEdit = ref(false)
const currentFormData = ref({})
const isParsing = ref(false)

// 全局共用的 AI 输入文本。Agent 广场的「药品录入助手」会带 ?q= 过来，
// 带过来就优先用它的示例，省得面试官自己编一段药品描述。
const DEFAULT_AGENT_TEXT = `帮我录个板蓝根颗粒，袋装的，卖25块，原价30，库存还有800件。
这药属于呼吸系统用药，是颗粒剂，规格是10克×20小袋，能放24个月。
功能主治是清热解毒、凉血利咽，用来治咽喉肿痛、口干咽燥，还有急性扁桃体炎。
成份是板蓝根，辅料有蔗糖和糊精。吃法是开水冲服，一次5到10克，一天3到4次。
禁忌和不良反应都没啥，写尚不明确就行。批号是国药准字Z45020920。
厂家是广西壮族自治区花红药业集团股份公司。`

const sharedAgentText = ref(
    route.query.q ? String(route.query.q) : DEFAULT_AGENT_TEXT
)

const activeCategory = ref('全部')
const categories = [
  '全部', '妇科用药', '骨骼肌肉系统用药', '呼吸系统用药',
  '消化系统用药', '儿科用药', '皮肤科用药', '大健康产品'
]

const filteredProducts = computed(() => {
  if (activeCategory.value === '全部') return products.value
  return products.value.filter(item => item.category === activeCategory.value)
})

const defaultForm = {
  name: '', generic_name: '', image_url: '',
  price: 0, original_price: 0, stock: 0,
  spec: '', category: '大健康产品', dosage_form: '', shelf_life: '',
  indications: '', contraindications: '', precautions: '', adverse_reactions: '',
  approval_number: '', manufacturer: ''
}

const loadProducts = async () => {
  loading.value = true
  try {
    products.value = await getProductsApi()
  } catch (e) {
    showToast({type: 'fail', message: e.message})
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

const handlePageAgentParse = async (text) => {
  isParsing.value = true
  try {
    // 拦截器已经剥壳，parsedData 直接就是数据字典
    const parsedData = await parseProductApi(text)

    isEdit.value = false
    currentFormData.value = {...defaultForm, ...parsedData}
    localStorage.removeItem('hhyy_product_draft')
    isModalOpen.value = true
    showToast({type: 'success', message: '解析成功，请核对表单'})
  } catch (e) {
    // 异常已经被拦截器 Toast 过了，这里静默处理即可
    console.error(e)
  } finally {
    isParsing.value = false
  }
}

const handleDelete = async (id) => {
  try {
    await showConfirmDialog({title: '确认删除', message: '此操作不可恢复'})
    await deleteProductApi(id)
    showToast({type: 'success', message: '删除成功'})
    await loadProducts()
  } catch (e) {
    // showConfirmDialog 取消抛出的是 'cancel'，拦截器不会处理这个
    if (e !== 'cancel') console.error(e)
  }
}

const handleSave = async (formData) => {
  try {
    if (isEdit.value) {
      await updateProductApi(formData.id, formData)
    } else {
      await createProductApi(formData)
    }
    isModalOpen.value = false
    showToast({type: 'success', message: '保存成功'})
    await loadProducts()
  } catch (e) {
    showToast({type: 'fail', message: e.message})
  }
}

onMounted(loadProducts)
</script>

<template>
  <div class="product-page">
    <Navbar/>

    <div class="header-container">
      <div class="header-actions">
        <van-button icon="arrow-left" plain size="small" @click="goBackOr(router, '/admin')">返回</van-button>
        <div class="title">药品库管理</div>
        <van-button v-permission="['admin', 'doctor']" type="danger" size="small" icon="plus" round @click="openCreate">
          录入
        </van-button>
      </div>
      <!-- 绑定全局输入文本 -->
      <AgentInput v-permission="['admin', 'doctor']" v-model="sharedAgentText" :is-parsing="isParsing"
                  @parse="handlePageAgentParse"/>
    </div>

    <van-tabs v-model:active="activeCategory" sticky offset-top="64" color="#ef4444" title-active-color="#ef4444"
              line-width="20px">
      <van-tab v-for="cat in categories" :key="cat" :title="cat" :name="cat"/>
    </van-tabs>

    <div class="product-list-container">
      <van-empty v-if="!loading && filteredProducts.length === 0" description="该分类下暂无药品"/>
      <div class="grid-layout">
        <ProductCard
            v-for="item in filteredProducts"
            :key="item.id"
            variant="manage"
            :item="item"
            @edit="openEdit"
            @delete="handleDelete"
        />
      </div>
    </div>

    <!-- 传入 v-model:agent-text -->
    <ProductFormModal
        v-model:agent-text="sharedAgentText"
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
  background-color: #f7f8fa;
  padding-top: 64px;
  padding-bottom: 24px;

  .header-container {
    padding: 16px;
    background: #fff;
    margin-bottom: 8px;
  }

  .header-actions {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
    max-width: 1200px;
    margin: 0 auto 16px;

    .title {
      font-size: 18px;
      font-weight: 600;
      color: #323233;
    }
  }

  .product-list-container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 16px;

    .grid-layout {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 12px;
    }

    @media (min-width: 768px) {
      .grid-layout {
        grid-template-columns: repeat(3, 1fr);
        gap: 16px;
      }
    }

    @media (min-width: 1024px) {
      .grid-layout {
        grid-template-columns: repeat(4, 1fr);
        gap: 24px;
      }
    }
  }
}
</style>