<script setup>
import {ref, onMounted} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import {getProductDetailApi} from '../api/product'
import {useCartStore} from '../store/cart'
import {showToast, showImagePreview} from 'vant'
import {ArrowLeft, Headphones} from 'lucide-vue-next'
import CartFloating from '../components/cart/CartFloating.vue'
import DrugAIAssistant from '../components/product/DrugAIAssistant.vue'
import {useAuthStore} from '../store/auth'
import {imageUrl} from '../utils/image'
import {goBackOr} from '../utils/nav'
import {writeDirectItem} from '../utils/checkout'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const cartStore = useCartStore()

const product = ref(null)
const loading = ref(true)

// 直接打开链接（分享/刷新）时 history 里没有上一条，router.back() 会把用户送出站外
const goBack = () => goBackOr(router, '/drugs')


const loadDetail = async () => {
  try {
    const res = await getProductDetailApi(route.params.id)
    product.value = res
  } catch (e) {
    showToast({type: 'fail', message: '药品加载失败'})
    router.back()
  } finally {
    loading.value = false
  }
}

const handlePreview = () => {
  if (!product.value) return
  showImagePreview([imageUrl(product.value.image_url)])
}

const addToCart = async () => {
  if (!product.value) return

  // 拦截未登录
  if (!auth.isLoggedIn) {
    auth.isLoginModalOpen = true
    return showToast('请先登录后再加入购物车')
  }

  await cartStore.add(product.value.id, 1)
  showToast({type: 'success', message: '已加入购物车'})
}

const buyNow = () => {
  if (!product.value) return
  if (!auth.isLoggedIn) {
    auth.isLoginModalOpen = true
    return showToast('请先登录后再购买')
  }

  // 「立即购买」清单交给结算页（utils/checkout 会顺手清掉购物车结算的残留）
  writeDirectItem({
    product_id: product.value.id,
    quantity: 1,
    name: product.value.name,
    price: product.value.price,
    image_url: product.value.image_url,
    spec: product.value.spec
  })

  router.push('/checkout?mode=direct')
}

const goToService = () => {
  router.push('/service')
}

onMounted(async () => {
  await loadDetail()
  if (auth.isLoggedIn) {
    cartStore.fetchCart()
  }
})
</script>

<template>
  <div class="detail-page">
    <!-- 顶部返回栏 -->
    <div class="nav-bar">
      <div class="back-btn" @click="goBack">
        <ArrowLeft :size="24"/>
      </div>
      <div class="title">药品详情</div>
      <!-- 直接打开链接时没有上一页，给一个明确出口，别让用户卡在详情页 -->
      <button type="button" class="nav-link" @click="router.push('/drugs')">
        药品广场
      </button>
    </div>

    <div v-if="loading" style="padding: 100px; text-align: center;">加载中...</div>

    <template v-else-if="product">
      <!-- PC 端内容区限宽 -->
      <div class="content-wrapper">
        <!-- 商品主图与基础信息 -->
        <div class="product-header">
          <van-image
              :src="imageUrl(product.image_url)"
              fit="contain"
              class="main-img"
              @click="handlePreview"
          >
            <template #loading>
              <van-loading type="spinner"/>
            </template>
          </van-image>

          <div class="info">
            <div class="price-box">
              <span class="price">¥{{ product.price }}</span>
              <span class="origin-price" v-if="product.original_price > product.price">原价 ¥{{
                  product.original_price
                }}</span>
            </div>
            <h1 class="name">{{ product.name }}</h1>
            <p class="generic">{{ product.generic_name }} | {{ product.dosage_form }} / {{ product.spec }}</p>
            <div class="tags">
              <van-tag type="danger" plain>{{ product.category }}</van-tag>
              <van-tag type="primary" plain>库存 {{ product.stock }}</van-tag>
            </div>
          </div>
        </div>

        <!-- AI 助手直接嵌入页面 -->
        <DrugAIAssistant :product-id="product.id" :product-name="product.name"/>

        <!-- 说明书参数区 -->
        <van-cell-group inset title="药品说明书" class="manual-group">
          <van-cell title="功能主治" :label="product.indications" title-class="cell-title"/>
          <van-cell title="禁忌" :label="product.contraindications" title-class="cell-title"/>
          <van-cell title="注意事项" :label="product.precautions" title-class="cell-title"/>
          <van-cell title="不良反应" :label="product.adverse_reactions" title-class="cell-title"/>
          <van-cell title="生产企业" :label="product.manufacturer" title-class="cell-title"/>
          <van-cell title="批准文号" :label="product.approval_number" title-class="cell-title"/>
        </van-cell-group>
      </div>
    </template>

    <!-- 左下角悬浮购物车 -->
    <CartFloating/>

    <!-- 底部固定购买栏 (PC端自适应限宽) -->
    <div class="bottom-action-bar-wrapper" v-if="product">
      <van-action-bar>
        <!-- 左侧客服 -->
        <div class="service-btn" @click="goToService">
          <van-icon name="service-o" size="20"/>
          <span>客服</span>
        </div>

        <!-- 右侧按钮组，固定宽度，中间留出空隙 -->
        <div class="action-btns">
          <van-button color="#ff976a" round class="btn-item" @click="addToCart">
            加入购物车
          </van-button>
          <van-button color="#ee0a24" round class="btn-item" @click="buyNow">
            立即购买
          </van-button>
        </div>
      </van-action-bar>
    </div>

    <!-- Vant 返回顶部组件 -->
    <van-back-top :right="20" :bottom="80"/>
  </div>
</template>

<style scoped lang="scss">
.detail-page {
  min-height: 100vh;
  background: #f7f8fa;
  /* 解决遮挡问题：底部留出足够空间给悬浮购物车和底部操作栏 */
  padding-bottom: 100px;

  .nav-bar {
    position: sticky;
    top: 0;
    z-index: 10;
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #fff;
    height: 46px;
    padding: 0 12px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);

    .back-btn {
      cursor: pointer;
      display: grid;
      place-items: center;
      width: 32px;
      height: 32px;
    }

    /* 标题绝对居中：左侧返回、右侧出口宽度不同，用 flex 居中会偏 */
    .title {
      position: absolute;
      left: 50%;
      transform: translateX(-50%);
      font-size: 16px;
      font-weight: 600;
      pointer-events: none;
    }

    .nav-link {
      padding: 4px 10px;
      border: 1px solid #fecaca;
      border-radius: 999px;
      background: #fff;
      color: #b91c1c;
      font-size: 12px;
      cursor: pointer;
      white-space: nowrap;

      &:hover {
        background: #fef2f2;
      }
    }
  }

  /* 核心：PC端限制最大宽度 */
  .content-wrapper {
    max-width: 800px;
    margin: 0 auto;
  }

  .product-header {
    background: #fff;
    padding: 16px;
    margin-bottom: 12px;

    .main-img {
      width: 100%;
      height: 300px;
      background: #f9f9f9;
      border-radius: 8px;
      margin-bottom: 16px;
      cursor: zoom-in;
      display: flex;
      justify-content: center;
    }

    .info {
      .price-box {
        display: flex;
        align-items: baseline;
        gap: 8px;
        margin-bottom: 8px;

        .price {
          color: #ee0a24;
          font-size: 24px;
          font-weight: bold;
        }

        .origin-price {
          color: #969799;
          font-size: 13px;
          text-decoration: line-through;
        }
      }

      .name {
        font-size: 18px;
        color: #323233;
        margin-bottom: 8px;
      }

      .generic {
        font-size: 13px;
        color: #969799;
        margin-bottom: 12px;
      }

      .tags {
        display: flex;
        gap: 8px;
      }
    }
  }

  .manual-group {
    margin-top: 12px;
    margin-bottom: 24px;
  }

  :deep(.cell-title) {
    font-weight: bold;
    color: #323233;
    margin-bottom: 6px;
  }

  /* 底部操作栏美化 */
  .bottom-action-bar-wrapper {
    position: fixed;
    bottom: 0;
    left: 0;
    width: 100%;
    z-index: 999;
    background: #fff;
    box-shadow: 0 -1px 3px rgba(0, 0, 0, 0.05);

    @media (min-width: 768px) {
      max-width: 800px;
      left: 50%;
      transform: translateX(-50%);
      border-radius: 12px 12px 0 0;
    }

    /* 自定义 ActionBar 内部布局 */
    :deep(.van-action-bar) {
      display: flex;
      align-items: center;
      padding: 8px 16px;
      padding-bottom: calc(8px + env(safe-area-inset-bottom)); // 适配 iPhone 底部黑条

      /* 客服按钮 */
      .service-btn {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 4px;
        font-size: 11px;
        color: #666;
        padding-right: 20px;
        cursor: pointer;

        &:active {
          opacity: 0.7;
        }
      }

      /* 右侧按钮组 */
      .action-btns {
        flex: 1;
        display: flex;
        gap: 12px; // 按钮之间的间距
        justify-content: flex-end; // 靠右对齐

        .btn-item {
          flex: none; // 取消平分，不占满
          width: 110px; // 固定宽度
          height: 40px;
          font-size: 14px;
          font-weight: 600;
        }
      }
    }
  }
}
</style>