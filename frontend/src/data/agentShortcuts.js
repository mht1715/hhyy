/**
 * Agent 广场的「快捷体验」与示例提问。
 *
 * 为什么要有这个文件：面试官打开广场，看到的是一排 Agent 卡片和一句「选择一个开始对话」，
 * 然后就得自己想问题——想不出来就只能问「你好」，什么都演示不出来。
 *
 * 这里做两件事：
 * 1. QUICK_ENTRIES：按业务场景给出入口（药品咨询 / 订单售后 / 药品录入 / 客服台 …），
 *    每条都带一句示例提问，点一下就连问题一起带过去；
 * 2. AGENT_SAMPLES：每个 Agent 卡片下面挂 2 条示例问题，点一下直接进对话并预填。
 *
 * `roles` 是「谁能用」：不在名单里就提示去登录 / 切换身份，而不是跳过去吃 403。
 */

export const ROLE_LABELS = {
  visitor: '游客',
  patient: '患者',
  doctor: '医生',
  support: '客服',
  admin: '管理员'
}

export const QUICK_ENTRIES = [
  {
    key: 'drug',
    title: '药品咨询',
    desc: '说明书、用法用量、禁忌，回答带引用角标',
    to: '/agents/drug_consult',
    sample: '花红片怎么吃',
    roles: ['patient', 'doctor', 'support', 'admin'],
    roleLabel: '患者 / 医生'
  },
  {
    key: 'after_sale',
    title: '订单售后',
    desc: '退货退款、物流时效，可查自己的订单',
    to: '/agents/order_after_sale',
    sample: '我的订单到哪了',
    roles: ['patient', 'doctor', 'support', 'admin'],
    roleLabel: '患者 / 医生'
  },
  {
    key: 'company',
    title: '企业介绍',
    desc: '品牌故事、产品线、公益项目（游客可用）',
    to: '/agents/company_intro',
    sample: '你们公司是做什么的',
    roles: ['visitor', 'patient', 'doctor', 'support', 'admin'],
    roleLabel: '所有人'
  },
  {
    key: 'product_entry',
    title: '药品录入助手',
    desc: '一段话解析成完整药品资料，自动填表入库',
    to: '/products',
    sample: '帮我录个板蓝根颗粒，袋装的，卖 25 块，库存 800 件，24 个月保质期',
    roles: ['doctor', 'admin'],
    roleLabel: '医生 / 管理员'
  },
  {
    key: 'support',
    title: '客服工作台',
    desc: '接管会话、实时回复、结束工单',
    to: '/support',
    sample: '',
    roles: ['support', 'admin'],
    roleLabel: '客服 / 管理员'
  },
  {
    key: 'kb_test',
    title: '检索测试台',
    desc: '看召回、重排分数与拒答阈值',
    to: '/admin/kb/search-test',
    sample: '',
    roles: ['admin'],
    roleLabel: '管理员'
  }
]

/** 每个 Agent 的示例提问（点一下进对话并预填，不自动发送）。 */
export const AGENT_SAMPLES = {
  drug_consult: ['花红片怎么吃', '哺乳期能吃花红片吗', '跌打扭伤怎么办'],
  order_after_sale: ['七天无理由退货吗', '我的订单到哪了', '退款多久到账'],
  company_intro: ['你们公司是做什么的', '花红品牌有什么故事', '有哪些公益项目'],
  customer_service: ['客户投诉怎么升级处理', '用户要求退款怎么回应']
}

/** @param {string} code */
export function samplesFor(code) {
  return (AGENT_SAMPLES[String(code || '')] || []).slice(0, 2)
}

export default {QUICK_ENTRIES, AGENT_SAMPLES, ROLE_LABELS, samplesFor}
