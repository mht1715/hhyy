/**
 * 演示用快捷提问（面试官不用自己想问题）。
 *
 * 设计原则：
 * - **按「能演示什么」分组**，而不是按知识点分组：知识库引用 / 上下文追问 / 长期记忆 /
 *   转人工 / 多 Agent。点之前就知道会看到什么，演示时不用解释。
 * - 每条都带 `expect`：一句话说明「这一问应该看到什么」，方便对照验收。
 * - `mention` 场景直接在数据里带 `mentions`，避免文本里的 `@` 不生效（后端按结构化 mentions 路由）。
 *
 * 记忆那组必须在**新会话**里回忆：写入会话 → 点右上角「新会话」→ 再点回忆那条。
 */

export const DEMO_SECTIONS = {
  drug_consult: [
    {
      title: '知识库问答',
      note: '引用角标 [n] 可点开看原文；药品类回答末尾自带免责声明',
      items: [
        {text: '跌打扭伤怎么办', expect: '命中《花红消肿止痛酊说明书》'},
        {text: '花红片怎么吃', expect: '剂量 / 频次 / 疗程 + 引用'},
        {text: '哺乳期能吃花红片吗', expect: '说明书【禁忌】原文 + 免责声明'}
      ]
    },
    {
      title: '上下文追问',
      note: '先问上面任意一条，再点这里 —— 看 AI 是否接得上「它 / 这个药」',
      items: [
        {text: '它有什么禁忌', expect: '指代消解成上一轮的具体药名'},
        {text: '这个药怎么购买', expect: '改写药名 + 购药与下单流程'}
      ]
    },
    {
      title: '长期记忆',
      note: '① 点第 1 条写入记忆 ② 点右上角「新会话」 ③ 再点第 2 条',
      items: [
        {text: '我对青霉素过敏', expect: '后台抽取成 risk 记忆，不阻塞回答'},
        {text: '这个药我能吃吗', expect: '注入过敏史：回答含「您上次提到…」'}
      ]
    },
    {
      title: '转人工',
      note: '敏感场景在生成之前就建单，坐席工作台 1 秒内可见',
      items: [
        {text: '我吃了不舒服，我要投诉', expect: '立刻 handoff 事件 + 工单 + 排队位次'},
        {text: '你们必须赔偿我，不然我就曝光', expect: '敏感词识别 → 建单'}
      ]
    },
    {
      title: '多 Agent 协作',
      note: '一条消息里 @ 两个 Agent，两段结论并行生成',
      items: [
        {
          text: '@AI药师 @订单售后 哺乳期能吃花红片吗？我这单能退吗？',
          expect: '两段带来源的结论 + 两个贡献者标签',
          mentions: [
            {agent_code: 'drug_consult', name: 'AI药师', offset: 0},
            {agent_code: 'order_after_sale', name: '订单售后', offset: 8}
          ]
        }
      ]
    }
  ],
  order_after_sale: [
    {
      title: '售后政策',
      note: '回答应引用《退换货政策》《配送与时效说明》等文档',
      items: [
        {text: '七天无理由退货吗', expect: '7 天 / 未拆封条件 + 引用'},
        {text: '退款多久到账', expect: '1-3 个工作日 + 引用'},
        {text: '运费怎么算', expect: '满 99 包邮 / 8 元运费'}
      ]
    },
    {
      title: '订单工具',
      note: '工具只能查自己的订单（越权会被拦）',
      items: [
        {text: '我的订单到哪了', expect: 'order_lookup 工具调用 + 物流状态'},
        {text: '怎么申请售后', expect: '流程步骤 + 引用'}
      ]
    },
    {
      title: '转人工',
      note: '说不清诉求时也可以直接转人工',
      items: [{text: '我要退货，但订单找不到', expect: '建单 + 交接摘要带订单实体'}]
    }
  ],
  company_intro: [
    {
      title: '企业介绍',
      note: '游客也能问：这个库是 public，用来演示「权限在检索层生效」',
      items: [
        {text: '你们公司是做什么的', expect: '企业简介 + 引用'},
        {text: '花红品牌有什么故事', expect: '品牌故事文档'},
        {text: '有哪些公益项目', expect: '社会责任文档'}
      ]
    },
    {
      title: '权限边界',
      note: '问售后会被 ACL 过滤（企业介绍库没有售后内容）',
      items: [{text: '七天无理由退货吗', expect: '低分拒答 / 提示换个助手'}]
    }
  ],
  customer_service: [
    {
      title: '客服 SOP',
      note: '仅 support / admin 可见：游客与患者问同样的问题会被 ACL 挡住',
      items: [
        {text: '客户投诉怎么升级处理', expect: 'SOP 流程 + 引用'},
        {text: '用户要求退款怎么回应', expect: '标准话术 + 引用'},
        {text: '客服标准话术有哪些', expect: '话术库文档'}
      ]
    }
  ]
}

/** 没有专门配置的 Agent 用这组通用提问。 */
const FALLBACK_SECTIONS = [
  {
    title: '试试这些',
    note: '覆盖知识库问答、上下文追问、转人工',
    items: [
      {text: '你好，你能做什么？', expect: '自我介绍 + 能力边界'},
      {text: '跌打扭伤怎么办', expect: '知识库检索 + 引用'},
      {text: '我吃了不舒服，我要投诉', expect: '敏感场景转人工'}
    ]
  }
]

/** @param {string} agentCode @returns {Array} */
export function sectionsForAgent(agentCode) {
  const key = String(agentCode || '')
  return DEMO_SECTIONS[key] || FALLBACK_SECTIONS
}

/** 空态时直接铺在前面的三条（不放多 Agent 这类需要额外操作的）。 */
export function quickStarters(agentCode) {
  const sections = sectionsForAgent(agentCode)
  const first = sections[0]
  return first ? first.items.slice(0, 3) : []
}

export default {DEMO_SECTIONS, sectionsForAgent, quickStarters}
