/**
 * 站点信息（唯一来源）。
 *
 * 想改站名 / 品牌后缀 / 描述 / 主题色 / 演示账号 / 页脚，**只改这个文件**：
 * - `vite.config.js` 直接 import 它 → `<title>`、meta description、PWA 名称与主题色
 * - 应用内 `Navbar` / `HomeView` / `LoginModal` / `GuideDrawer` / `MvpBanner` 也读它
 *
 * 两条约束，别破坏：
 * 1. **纯数据、零 import**——`vite.config.js` 跑在 Node 里，不能有 .vue / 浏览器 API；
 * 2. 不要在这里放页面正文（hero 文案、能力卡片这些属于页面），
 *    否则「站点信息」会变成第二个 content 系统，改起来反而更慢。
 */

export const siteConfig = {
  // ── 基本信息：标题栏 / 顶栏品牌 / PWA 名称 / 描述 ──
  name: '花红医药 Agent',
  fullName: '花红医药 Agent 系统',
  shortName: '花红Agent',
  brand: '花红',
  brandSuffix: 'agent（demo）',
  description: '面向医药电商场景的多 Agent + RAG 平台：Agent 编排、RAG 检索带引用、三层记忆、转人工闭环，以及一套能跑出指标的输出治理。',
  keywords: ['医药电商', 'Agent', 'RAG', '知识库问答', 'LangGraph', 'Milvus', 'FastAPI', 'Vue 3'],
  lang: 'zh-CN',
  themeColor: '#ef4444',
  backgroundColor: '#ffffff',
  // 顶栏徽标 / 说明条上的版本标识
  version: 'MVP',

  // ── 标题：浏览器标签页 = titleTemplate 里的 {page} 换成 titles[路由 name] ──
  titleTemplate: '{page} · 花红医药 Agent',
  // 没登记的路由直接用 fullName
  titles: {
    VisitorHome: '首页',
    Agents: 'Agent 广场',
    AgentChat: 'AI 对话',
    Patient: '患者工作台',
    Doctor: '医生工作台',
    Admin: '管理员工作台',
    Support: '客服工作台',
    KbList: '知识库',
    KbDetail: '知识库文档',
    KbPermissions: '知识库权限',
    KbSearchTest: '检索测试台',
    AdminObserve: '指标看板',
    AdminPrompts: 'Prompt 版本',
    Drugs: '药品广场',
    ProductDetail: '药品详情',
    Products: '药品管理',
    Cart: '购物车',
    Checkout: '确认订单',
    Orders: '我的订单',
    OrderDetail: '订单详情',
    Service: '消息',
    Memory: '记忆管理'
  },

  // ── 公司与官网（页脚、关于页可引用）──
  company: {
    name: '花红药业',
    url: 'https://hhyy.com'
  },

  // ── 演示账号：落地页「按角色体验」与登录弹窗共用这一份 ──
  // role 用来取图标 / 配色，homePath 是登录后落地的页面
  demo: {
    password: '123456',
    accounts: [
      {username: 'patient', role: 'patient', title: '患者', desc: '问药、查单、看记忆', homePath: '/patient'},
      {username: 'doctor', role: 'doctor', title: '医生', desc: '药品资料 + AI 辅助', homePath: '/doctor'},
      {username: 'support', role: 'support', title: '客服', desc: '接管队列、人工回复', homePath: '/support'},
      {username: 'admin', role: 'admin', title: '管理员', desc: '指标、治理、评估', homePath: '/admin'}
    ]
  },

  // ── 演示数据里会展示给用户的常量 ──
  // 收货地址是模拟的（不接真实物流），但它在结算页与订单详情各出现一次，
  // 所以也收进配置，避免两处文案改一处忘一处
  demoAddress: {
    name: '张药师',
    phone: '138****8888',
    detail: '广西壮族自治区南宁市青秀区民族大道 123 号 花红药业大厦 8 楼'
  },

  // ── 登录弹窗文案 ──
  login: {
    title: '选择体验身份',
    subtitle: '系统内置四种角色，点击即用演示账号登录；客服与患者建议各开一个标签页，互不影响'
  },

  // ── 导览抽屉抬头 ──
  guide: {
    title: '花红医药 Agent · MVP',
    subtitle: 'Agent 编排 + RAG 检索 + 输出治理，全链路可解释、可评估。'
  },

  // ── 页脚 ──
  footer: {
    stack: ['FastAPI', 'LangGraph', 'Milvus', 'PostgreSQL', 'Redis', 'Vue 3']
  }
}

export default siteConfig
