<script setup>
import {ref, watch} from 'vue'
import {showToast, showConfirmDialog} from 'vant'
import {parseProductApi} from '../../api/agent'
import {uploadImageApi} from '../../api/upload'
import AgentInput from '../common/AgentInput.vue'
import {normalizeImageUrl} from '../../utils/image'

const props = defineProps({
  isOpen: {type: Boolean, default: false},
  isEdit: {type: Boolean, default: false},
  initialData: {type: Object, default: () => ({})},
  agentText: {type: String, default: ''} // 接收父组件文本
})
const emit = defineEmits(['close', 'save', 'update:agentText'])

const DRAFT_KEY = 'hhyy_product_draft'

const categoryOptions = [
  '妇科用药', '骨骼肌肉系统用药', '呼吸系统用药',
  '消化系统用药', '儿科用药', '皮肤科用药', '大健康产品'
]

const form = ref({})
const isParsing = ref(false)
const showCategoryPicker = ref(false)
const fileList = ref([])

watch(() => props.isOpen, async (val) => {
  if (val) {
    const draftStr = localStorage.getItem(DRAFT_KEY)
    let useDraft = false

    if (draftStr) {
      try {
        const draft = JSON.parse(draftStr)
        if ((!props.isEdit && !draft.id) || (props.isEdit && draft.id === props.initialData.id)) {
          await showConfirmDialog({
            title: '发现未保存的草稿',
            message: '您上次填写的内容尚未保存，是否继续编辑？',
            confirmButtonText: '恢复草稿',
            cancelButtonText: '重新填写',
          }).then(() => {
            form.value = draft.data
            useDraft = true
            showToast('已恢复草稿')
          }).catch(() => {
            localStorage.removeItem(DRAFT_KEY)
          })
        }
      } catch (e) {
        console.error('解析草稿失败', e)
      }
    }

    if (!useDraft) {
      form.value = {...props.initialData}
    }

    if (form.value.image_url) {
      fileList.value = [{url: form.value.image_url}]
    } else {
      fileList.value = []
    }
  }
})

watch(form, (newVal) => {
  if (!props.isOpen) return
  localStorage.setItem(DRAFT_KEY, JSON.stringify({
    id: props.isEdit ? props.initialData.id : null,
    data: newVal
  }))
}, {deep: true})

// 图片真实上传逻辑
const ACCEPTED_IMAGE = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']
const MAX_IMAGE_MB = 5

const afterRead = async (file) => {
  // 客户端先挡一次：类型 / 体积不对时不用等一个来回，提示也更具体
  const raw = file && file.file ? file.file : null
  if (raw && raw.type && !ACCEPTED_IMAGE.includes(raw.type)) {
    file.status = 'failed'
    file.message = '只支持 JPG / PNG / WebP / GIF'
    showToast('只支持 JPG / PNG / WebP / GIF 图片')
    return
  }
  if (raw && raw.size > MAX_IMAGE_MB * 1024 * 1024) {
    file.status = 'failed'
    file.message = `图片不能超过 ${MAX_IMAGE_MB}MB`
    showToast(`图片不能超过 ${MAX_IMAGE_MB}MB`)
    return
  }

  file.status = 'uploading'
  file.message = '上传中...'
  try {
    const res = await uploadImageApi(raw || file.file)
    file.status = 'done'
    file.message = ''
    // 后端返回的是站内绝对路径（/static/uploads/xxx.png），
    // 历史数据的反斜杠路径也在这里统一纠正
    form.value.image_url = normalizeImageUrl(res && res.url)
    showToast({type: 'success', message: '图片上传成功'})
  } catch (error) {
    file.status = 'failed'
    file.message = '上传失败'
    showToast({type: 'fail', message: (error && error.message) || '图片上传失败'})
  }
}

const onConfirmCategory = ({selectedOptions}) => {
  form.value.category = selectedOptions[0].text
  showCategoryPicker.value = false
}

// 弹窗内解析：覆盖旧数据
const handleAgentParse = async (text) => {
  isParsing.value = true
  try {
    const parsedData = await parseProductApi(text)

    const currentId = props.isEdit ? props.initialData.id : null
    form.value = {...parsedData, ...(currentId ? {id: currentId} : {})}

    if (parsedData.image_url) {
      fileList.value = [{url: parsedData.image_url}]
    } else {
      fileList.value = []
    }
    showToast({type: 'success', message: '解析成功，已覆盖表单'})
  } catch (e) {
    console.error(e)
  } finally {
    isParsing.value = false
  }
}

const submit = () => {
  if (!form.value.name) return showToast('请填写商品名称')
  emit('save', form.value)
  localStorage.removeItem(DRAFT_KEY)
}
</script>

<template>
  <teleport to="body">
    <van-popup
        :show="isOpen"
        position="bottom"
        round
        closeable
        :style="{ height: '90%' }"
        @update:show="val => !val && emit('close')"
    >
      <div class="form-modal-content">
        <div class="modal-title">{{ isEdit ? '编辑药品信息' : '录入新药品' }}</div>

        <div class="agent-section">
          <!-- 同步文本 -->
          <AgentInput
              :model-value="agentText"
              @update:model-value="val => emit('update:agentText', val)"
              :is-parsing="isParsing"
              @parse="handleAgentParse"
          />
        </div>

        <div class="scrollable-form">
          <van-form @submit="submit">
            <van-cell-group inset title="基础信息">
              <van-field v-model="form.name" label="商品名称" placeholder="例如：花红消肿止痛酊" required/>
              <van-field v-model="form.generic_name" label="通用名" placeholder="例如：消肿止痛酊"/>

              <van-field name="uploader" label="商品主图">
                <template #input>
                  <div class="uploader-box">
                    <van-uploader v-model="fileList" :max-count="1" accept="image/*" :after-read="afterRead"/>
                    <p class="upload-hint">支持 JPG / PNG / WebP / GIF，≤ {{ MAX_IMAGE_MB }}MB</p>
                  </div>
                </template>
              </van-field>

              <van-field name="stepper" label="价格(元)" required>
                <template #input>
                  <van-stepper v-model="form.price" step="0.1" min="0" input-width="80px"/>
                </template>
              </van-field>
              <van-field name="stepper" label="原价(元)">
                <template #input>
                  <van-stepper v-model="form.original_price" step="0.1" min="0" input-width="80px"/>
                </template>
              </van-field>
              <van-field name="stepper" label="库存" required>
                <template #input>
                  <van-stepper v-model="form.stock" step="10" min="0" input-width="80px"/>
                </template>
              </van-field>
            </van-cell-group>

            <van-cell-group inset title="规格与分类">
              <van-field v-model="form.category" is-link readonly label="分类" placeholder="请选择分类"
                         @click="showCategoryPicker = true"/>
              <van-field v-model="form.dosage_form" label="剂型" placeholder="如：酊剂 / 片剂"/>
              <van-field v-model="form.spec" label="规格" placeholder="如：45ml"/>
              <van-field v-model="form.shelf_life" label="有效期" placeholder="如：36个月"/>
            </van-cell-group>

            <van-cell-group inset title="说明书属性">
              <van-field v-model="form.indications" rows="2" autosize label="功能主治" type="textarea"
                         placeholder="请填写适应症..."/>
              <van-field v-model="form.contraindications" rows="2" autosize label="禁忌" type="textarea"
                         placeholder="如：孕妇禁用。"/>
              <van-field v-model="form.precautions" rows="2" autosize label="注意事项" type="textarea"
                         placeholder="请填写注意事项..."/>
              <van-field v-model="form.adverse_reactions" rows="2" autosize label="不良反应" type="textarea"
                         placeholder="如：尚不明确。"/>
            </van-cell-group>

            <van-cell-group inset title="生产信息">
              <van-field v-model="form.approval_number" label="批准文号" placeholder="如：国药准字..."/>
              <van-field v-model="form.manufacturer" label="生产企业" placeholder="如：广西壮族自治区花红药业..."/>
            </van-cell-group>

            <div class="submit-btn-wrap">
              <van-button round block type="danger" native-type="submit">
                保存入库
              </van-button>
            </div>
          </van-form>
        </div>

        <van-popup v-model:show="showCategoryPicker" position="bottom" round teleport="body">
          <van-picker
              :columns="categoryOptions.map(c => ({ text: c, value: c }))"
              @confirm="onConfirmCategory"
              @cancel="showCategoryPicker = false"
          />
        </van-popup>
      </div>
    </van-popup>
  </teleport>
</template>

<style scoped lang="scss">
.form-modal-content {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #f7f8fa;

  .modal-title {
    padding: 16px;
    font-size: 16px;
    font-weight: 600;
    text-align: center;
    background: white;
    flex-shrink: 0;
  }

  .agent-section {
    padding: 12px 16px 0;
    flex-shrink: 0;
  }

  .scrollable-form {
    flex: 1;
    overflow-y: auto;
    padding-bottom: 24px;
  }

  .submit-btn-wrap {
    padding: 16px;
    margin-top: 10px;
  }
}

:deep(.van-cell-group__title) {
  padding-left: 16px;
  font-weight: 600;
}

.uploader-box {
  display: flex;
  flex-direction: column;
  gap: 4px;

  .upload-hint {
    margin: 0;
    font-size: 11px;
    color: #9ca3af;
  }
}
</style>