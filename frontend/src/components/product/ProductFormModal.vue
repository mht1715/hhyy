<script setup>
import {ref, watch} from 'vue'
import {X} from 'lucide-vue-next'
import AgentInput from '../common/AgentInput.vue'
import NumberInput from '../common/NumberInput.vue'
import request from '../../utils/request'

const props = defineProps({
  isOpen: {type: Boolean, default: false},
  isEdit: {type: Boolean, default: false},
  initialData: {type: Object, default: () => ({})}
})
const emit = defineEmits(['close', 'save'])

const categoryOptions = [
  '妇科用药', '骨骼肌肉系统用药', '呼吸系统用药',
  '消化系统用药', '儿科用药', '皮肤科用药', '大健康产品'
]

const form = ref({})
const isParsing = ref(false)

watch(() => props.isOpen, (val) => {
  if (val) {
    form.value = {...props.initialData}
  }
})

// 弹窗内的 Agent 解析
const handleAgentParse = async (text) => {
  isParsing.value = true
  try {
    const parsedData = await request.post('/agent/parse-product', {text})
    if (parsedData.error) {
      alert(parsedData.error)
      return
    }
    // 增量合并到当前表单，未提及的字段保留原样
    form.value = {...form.value, ...parsedData}
  } catch (e) {
    alert('解析失败：' + e.message)
  } finally {
    isParsing.value = false
  }
}

const submit = () => {
  if (!form.value.name) return alert('请填写商品名称')
  emit('save', form.value)
}
</script>

<template>
  <Teleport to="body">
    <div v-if="isOpen" class="modal-overlay" @click.self="emit('close')">
      <div class="modal-content large-modal">
        <div class="modal-header">
          <h3>{{ isEdit ? '编辑药品信息' : '录入新药品' }}</h3>
          <button class="close-btn" @click="emit('close')">
            <X :size="24"/>
          </button>
        </div>

        <!-- 顶部固定 AI 助手 -->
        <div class="modal-agent-top">
          <AgentInput :is-parsing="isParsing" @parse="handleAgentParse"/>
        </div>

        <!-- 滚动表单区 -->
        <div class="form-body scrollable-form">
          <div class="form-section">
            <h4>基础信息</h4>
            <div class="form-row">
              <div class="form-group flex-2">
                <label>商品名称 <span class="required">*</span></label>
                <input v-model="form.name" type="text" placeholder="例如：花红消肿止痛酊"/>
              </div>
              <div class="form-group flex-1">
                <label>通用名</label>
                <input v-model="form.generic_name" type="text" placeholder="例如：消肿止痛酊"/>
              </div>
            </div>
            <div class="form-group">
              <label>商品主图 URL</label>
              <input v-model="form.image_url" type="text" placeholder="https://..."/>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label>价格 (元) <span class="required">*</span></label>
                <NumberInput v-model="form.price" :step="0.1" min="0" placeholder="如：15.73"/>
              </div>
              <div class="form-group">
                <label>原价 (元)</label>
                <NumberInput v-model="form.original_price" :step="0.1" min="0" placeholder="如：18.00"/>
              </div>
              <div class="form-group">
                <label>库存 <span class="required">*</span></label>
                <NumberInput v-model="form.stock" :step="10" min="0" placeholder="如：1000"/>
              </div>
            </div>
          </div>

          <div class="form-section">
            <h4>规格与分类</h4>
            <div class="form-row">
              <div class="form-group">
                <label>分类</label>
                <select v-model="form.category">
                  <option v-for="cat in categoryOptions" :key="cat" :value="cat">{{ cat }}</option>
                </select>
              </div>
              <div class="form-group">
                <label>剂型</label>
                <input v-model="form.dosage_form" type="text" placeholder="如：酊剂 / 片剂"/>
              </div>
              <div class="form-group">
                <label>规格</label>
                <input v-model="form.spec" type="text" placeholder="如：45ml"/>
              </div>
              <div class="form-group">
                <label>有效期</label>
                <input v-model="form.shelf_life" type="text" placeholder="如：36个月"/>
              </div>
            </div>
          </div>

          <div class="form-section">
            <h4>说明书属性</h4>
            <div class="form-group">
              <label>适应症/功能主治</label>
              <textarea v-model="form.indications" rows="2" placeholder="请填写适应症..."></textarea>
            </div>
            <div class="form-group">
              <label>禁忌</label>
              <textarea v-model="form.contraindications" rows="2" placeholder="如：孕妇禁用。"></textarea>
            </div>
            <div class="form-group">
              <label>注意事项</label>
              <textarea v-model="form.precautions" rows="2" placeholder="请填写注意事项..."></textarea>
            </div>
            <div class="form-group">
              <label>不良反应</label>
              <textarea v-model="form.adverse_reactions" rows="2" placeholder="如：尚不明确。"></textarea>
            </div>
          </div>

          <div class="form-section">
            <h4>生产信息</h4>
            <div class="form-row">
              <div class="form-group">
                <label>批准文号</label>
                <input v-model="form.approval_number" type="text" placeholder="如：国药准字..."/>
              </div>
              <div class="form-group flex-2">
                <label>生产企业</label>
                <input v-model="form.manufacturer" type="text" placeholder="如：广西壮族自治区花红药业..."/>
              </div>
            </div>
          </div>
        </div>

        <div class="modal-footer">
          <button class="cancel-btn" @click="emit('close')">取消</button>
          <button class="save-btn" @click="submit">保存入库</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped lang="scss">
/* 弹窗样式 */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;

  .large-modal {
    background: white;
    width: 800px;
    max-width: 95%;
    border-radius: 12px;
    display: flex;
    flex-direction: column;
    max-height: 80vh; /* 核心：不超过屏幕 80% */
    overflow: hidden;

    .modal-header {
      padding: 16px 24px;
      border-bottom: 1px solid #e5e7eb;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-shrink: 0;

      h3 {
        font-size: 18px;
        color: #111827;
      }

      .close-btn {
        background: none;
        border: none;
        cursor: pointer;
        color: #9ca3af;

        &:hover {
          color: #ef4444;
        }
      }
    }

    .modal-agent-top {
      padding: 16px 24px 0;
      flex-shrink: 0;
    }

    .scrollable-form {
      padding: 24px;
      overflow-y: auto;
      flex: 1;

      .form-section {
        margin-bottom: 24px;
        padding-bottom: 20px;
        border-bottom: 1px dashed #e5e7eb;

        &:last-child {
          border-bottom: none;
          margin-bottom: 0;
        }

        h4 {
          font-size: 15px;
          color: #374151;
          margin-bottom: 16px;
          font-weight: 600;
          background: #f3f4f6;
          padding: 6px 12px;
          border-radius: 4px;
          display: inline-block;
        }
      }

      .form-group {
        margin-bottom: 16px;

        label {
          display: block;
          font-size: 13px;
          color: #4b5563;
          margin-bottom: 6px;
          font-weight: 500;
        }

        .required {
          color: #ef4444;
        }

        input, select, textarea {
          width: 100%;
          padding: 10px;
          border: 1px solid #d1d5db;
          border-radius: 6px;
          outline: none;
          font-family: inherit;
          font-size: 14px;
          background: white;

          &:focus {
            border-color: #ef4444;
            box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.1);
          }
        }
      }

      .form-row {
        display: flex;
        gap: 16px;

        .flex-1 {
          flex: 1;
        }

        .flex-2 {
          flex: 2;
        }

        .form-group {
          flex: 1;
          margin-bottom: 16px;
        }
      }
    }

    .modal-footer {
      padding: 16px 24px;
      border-top: 1px solid #e5e7eb;
      display: flex;
      justify-content: flex-end;
      gap: 12px;
      flex-shrink: 0;
      background: #f9fafb;

      button {
        padding: 10px 24px;
        border-radius: 6px;
        font-weight: 600;
        cursor: pointer;
        border: none;
      }

      .cancel-btn {
        background: white;
        border: 1px solid #d1d5db;
        color: #4b5563;
      }

      .save-btn {
        background: #ef4444;
        color: white;

        &:hover {
          background: #dc2626;
        }
      }
    }
  }
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  100% {
    transform: rotate(360deg);
  }
}

@media (max-width: 768px) {
  .modal-overlay {
    .large-modal {
      width: 100% !important;
      height: 80% !important;
      max-height: 80% !important;
      border-radius: 5px !important;
    }

    .form-row {
      flex-direction: column;
      gap: 0;
    }
  }
}
</style>