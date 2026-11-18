# 花红 Agent 应用平台（HHAgent）

面向医药电商场景的 **多 Agent + RAG 平台** 全栈实现，同时作为投递花红药业「Agent 应用开发」岗位的作品。

核心主张：**Agent 是配置，工具是代码；知识库是数据，权限在检索层；每一步都可观测。**

- 需求文档：[docs/需求文档.md](docs/需求文档.md)
- 任务拆分：[docs/任务清单.md](docs/任务清单.md)

---

## 当前进度

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| 全栈骨架（FastAPI + Vue3/Vant + PG + Redis） | ✅ | 登录、RBAC、药品 CRUD、购物车、订单 |
| 药品入库 Agent（自然语言 → 结构化表单） | ✅ | `/api/agent/parse-product` |
| 药品咨询 Agent | ✅ | M1 已改为真 RAG：检索 + `[n]` 引用 + 低分拒答（`/api/agent/drug-consult`） |
| 统一模型工厂 | ✅ | 单一入口，温度/超时/重试集中，缺 key 给 503 而不是崩 |
| 数据库迁移 | ✅ | Alembic（老库自动 stamp，不重复建表），0001 baseline + 0002 知识库 + 0003 多 Agent/会话 |
| 分层接口契约 | ✅ | LLM / Retriever / Tool / Memory / TraceSink 六个 Protocol + 测试替身 |
| 可观测（Langfuse） | ✅ | 一键开关，未配置即 no-op，绝不阻塞回答 |
| CI | ✅ | ruff + pytest + 前端构建 |
| **多知识库 RAG（Milvus）** | ✅ | M1：解析 / 分块 / 混合检索（BM25+dense+RRF）/ 重排 / 角色 ACL / 检索测试台 |
| **多 Agent 与 `@` 协作** | ✅ | M2：Agent 配置化注册 / `@` 并行 / SSE 流式 / 引用与免责声明 / 幂等与限流 |
| 记忆系统 + 转人工 | 📋 | M3 |
| 评估集与指标看板 | 📋 | M4 |

---

## 架构

```mermaid
flowchart TB
    subgraph FE["前端 Vue3"]
        A1["Agent 广场 / 药品页"]
        A2["后台：知识库 / Agent / 工单"]
    end
    subgraph API["FastAPI"]
        B1["/api/chat/stream (SSE)"]
        B2["/api/admin/*"]
        B3["鉴权 / RBAC / 限流"]
    end
    subgraph ORCH["编排层 LangGraph"]
        C1["路由：@ / supervisor"]
        C2["子 Agent（并行）"]
        C3["检索 / 工具 / 合成 / 校验"]
    end
    subgraph CAP["能力层"]
        D1["RAG：解析 分块 召回 重排"]
        D2["Agent + Tool 注册表"]
        D3["记忆"]
    end
    subgraph DATA["数据层"]
        E1[("PostgreSQL")]
        E2[("Milvus")]
        E3[("Redis")]
    end
    OBS["Langfuse：trace / score / dataset"]

    FE --> API --> ORCH --> CAP --> DATA
    ORCH -.-> OBS
```

---

## 快速开始

**前置**：Docker Desktop、Python 3.11、Node 20+。

```powershell
# 1. 依赖
python -m venv .venv
.\.venv\Scripts\pip install -r backend\requirements.txt
cd frontend; npm install; cd ..

# 2. 配置（把 your_key 换成真实值；Langfuse 可留空）
Copy-Item .env.example .env

# 3. 起依赖（PG / Redis / Milvus），首次约 90 秒
.\script\dev.ps1 up

# 4. 建表 + 演示数据
.\script\dev.ps1 init
.\script\dev.ps1 seed

# 5. 起服务（两个终端）
.\script\dev.ps1 backend    # http://127.0.0.1:8000/docs
.\script\dev.ps1 frontend   # http://127.0.0.1:5173
```

演示账号（由 `script/seed_users.py` 生成）：`admin` / `doctor` / `patient`，密码均为 `123456`。

> 本机直接跑后端时 `POSTGRES_SERVER=localhost`；若用 compose 里的 backend 容器则应为 `db`
> （compose 已通过环境变量覆盖）。

---

## 端口

| 服务 | 端口 | 说明 |
| --- | --- | --- |
| 前端 Vite | 5173 | 开发服务器，`/api` 走代理 |
| 后端 FastAPI | 8000 | `/docs` 交互文档，`/health` 健康检查 |
| PostgreSQL | 5432 | 业务库（含 pgvector 扩展） |
| Redis | 6379 | 缓存 / 后续的会话与队列 |
| Milvus | 19530 / 9091 | gRPC / 健康检查 |
| MinIO | 9000 / 9001 | Milvus 对象存储 / 控制台 |

---

## 常用命令

| 命令 | 作用 |
| --- | --- |
| `.\script\dev.ps1 up` | 启动依赖服务 |
| `.\script\dev.ps1 status` | 查看容器状态 |
| `.\script\dev.ps1 init` | Alembic 建表 / 升级 |
| `.\script\dev.ps1 seed` | 灌演示数据（账号 + 药品） |
| `.\script\dev.ps1 kb` | 灌知识库种子（4 库 12 文档，真实调用 embedding） |
| `.\script\dev.ps1 agents` | 灌 Agent 与 Prompt 模板（4 个 Agent，纯 DB 写入） |
| `.\script\dev.ps1 test` | 单元测试（不连外部服务） |
| `.\script\dev.ps1 lint` | ruff |
| `.\script\dev.ps1 check` | **提交前跑**：lint + test + 前端构建 |
| `.\script\dev.ps1 langfuse` | Langfuse 连通性自检 |

手动执行等价命令：

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check backend
.\.venv\Scripts\python script\init_db.py
```

---

## 可观测（Langfuse）

- 开关只看 `.env` 的 `LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_BASE_URL`，
  **任一为空即整体关闭**，服务行为与未接入时完全一致。
- 自检：`.\script\dev.ps1 langfuse`，或在后台看 trace `agent.parse_product`。
- 埋点位置：`app/observability/`。业务代码只调 `get_trace_sink()`，从不直接 import SDK。
- 注意：`get_trace_url()` 会同步请求 Langfuse API，只允许出现在运维脚本里。

---

## 知识库与 RAG（M1）

### 一句话架构

知识库是**数据**不是代码：后台建库 → 传文档 → 勾权限，前台检索自动生效。
向量统一落在单个 Milvus collection `hhyy_kb_chunks`，靠 `kb_id` 标量索引隔离。

### 权限怎么生效

| 层 | 判什么 | 在哪 |
| --- | --- | --- |
| 功能 RBAC | 能不能进后台 / 调某个接口 | `Depends(require_roles([...]))` |
| 数据 ACL | 这次检索能召回哪些库的 chunk | `app/rag/acl.py` 产出 `kb_id in [...]`，**拼进 Milvus 的 filter 表达式** |

三条不能破的规则：

1. **默认拒绝**：新建库没有任何授权行 = 谁都检索不到（只有 `visibility=public` 例外）。
2. **过滤下推到向量库**：绝不「先召回 30 条再过滤」——那要么答不出，要么泄露。
3. **权限变更 ≤30s 生效**：Redis 缓存 key 带版本号，写操作 `INCR version` 即整体失效。

### 检索链路

```
query ──(有历史→LLM 改写)──> embedding
   ├─ dense:  top30 (COSINE)
   ├─ sparse: top30 (Milvus 内置 BM25，chinese analyzer)
   ├─ RRF(k=60) 融合
   ├─ gte-rerank-v2 重排 → top5
   └─ 阈值：top1 < 阈值 → 拒答（不回退、不编造）
```

**阈值有两个，因为两种分数虽然都在 0~1，分布却差一个数量级**：

| 打分口径 | 阈值 | 实测依据 |
| --- | --- | --- |
| 重排分（正常路径） | `RERANK_SCORE_THRESHOLD=0.15` | 10 正 / 10 负问题：负例最高 0.135，正例最低 0.175 |
| 余弦相似度（重排降级时） | 库级 `score_threshold`（0.35 / 0.40） | 无关问题也能到 0.69，泛问句只有 0.28 |

用一个数卡两种分数，结果是「重排路径全拒、余弦路径全放」。RRF 融合分只有 0.0x
量级，永远不能直接当阈值判据——这个取舍写在 `app/rag/retriever.py` 的模块注释里。

> 排障提示：`gte-rerank`（老模型名）在本账号返回 403 `AccessDenied`，可用的是
> `gte-rerank-v2`。重排一旦静默降级，症状是「泛问句全被拒答」，很像阈值调错了。

### 后台接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/api/admin/kb` | 列表（含文档数/chunk 数）/ 新建 |
| GET/PUT/DELETE | `/api/admin/kb/{id}` | 详情 / 修改 / 删除（连向量一起删） |
| GET/POST | `/api/admin/kb/{id}/documents` | 文档列表（状态轮询）/ 上传（file \| url \| text） |
| POST | `/api/admin/kb/{id}/documents/{doc_id}/reindex` | 重新解析（游标清零，全量重建） |
| POST | `/api/admin/kb/{id}/documents/{doc_id}/retry` | 失败重试（保留游标，断点续传） |
| GET | `/api/admin/kb/{id}/documents/{doc_id}/chunks` | 分段列表 |
| PUT | `/api/admin/kb/{id}/chunks/{chunk_id}` | 改正文 → **只重建这一条**向量 |
| GET | `/api/admin/kb/permissions` | 权限矩阵（库 × 角色） |
| PUT | `/api/admin/kb/{id}/permissions` | 保存授权（全量覆盖 + 审计 + 失效缓存） |
| POST | `/api/admin/kb/{id}/search-test` | **检索测试台**：以任意角色身份检索 |
| GET | `/api/admin/kb/stats` | 文档/chunk 数、7 日检索次数、零召回榜 |

### 五分钟演示（这是 M1 最值钱的一段）

1. `.\script\dev.ps1 kb` → 4 个库 12 篇文档全部 `ready`
2. admin 登录 → `/admin/kb` → 看到 4 个库的文档数与 chunk 数
3. `/admin/kb/permissions` → 看「说明书 = patient/doctor/support，SOP = 仅 support」
4. `/admin/kb/search-test` → 点顶部「快捷用例」里的 **游客问售后**：同一句「七天无理由退货吗」，
   `visitor` 显示「被过滤：订单与售后政策」、`low_score` 拒答；换成 **售后政策**（patient）立刻命中
   —— **权限是在检索层生效的**。另外 `越权查 SOP` 演示 `no_permission`（拒绝 ≠ 没搜到）。
5. 药品详情页问「哺乳期能吃吗」→ 回答带 `[1]` 角标，引用指向说明书【禁忌】

> 测试台默认「全部库 + patient」，页面会显示 `top_score / 阈值` 和打分口径。
> 拒答时也会把「差一点」的片段列出来——看不到分数就只能靠猜是权限、召回还是阈值的问题。

---

## 多 Agent 与流式对话（M2）

### 一句话架构

> **Agent 是配置，工具是代码**：往 `agents` 表插一行（选知识库 + 选工具 + 指定 prompt 模板）
> 就是一个新 Agent，不需要改编排、不需要发版。编排层只读 `AgentConfig`。

```mermaid
flowchart LR
    U["用户消息 + mentions[]"] --> R{"路由"}
    R -->|有 @| M["显式路由<br/>不花模型调用"]
    R -->|无 @| S["supervisor<br/>JSON: agents/confidence"]
    S -->|conf < 0.6| C["澄清：列出可用助手"]
    M --> P1["子 Agent A<br/>工具 + 检索"]
    M --> P2["子 Agent B<br/>工具 + 检索"]
    P1 --> G["合并（确定性）<br/>来源标注 + 引用重编号"]
    P2 --> G
    G --> GD["Guardrail<br/>角标过滤 + 免责声明"]
    GD --> SSE["SSE 事件流"]
```

LangGraph 图：`route → (clarify | dispatch) → compose → guardrail`。状态只放业务字段
（M3 接 checkpointer 时不动节点），数据库会话/模型/追踪挂在运行时上下文上。

### 四个内置 Agent（`dev.ps1 agents`）

| code | 名称 | 知识库 | 工具 | 可见角色 |
| --- | --- | --- | --- | --- |
| `drug_consult` | AI 药师 | `kb_drug_manual` | kb_search / product_lookup / escalate_human | 患者、医生、客服、管理员 |
| `order_after_sale` | 订单售后 | `kb_after_sale` | order_lookup / policy_search / escalate_human | 患者、医生、客服、管理员 |
| `company_intro` | 企业介绍 | `kb_company`（public） | kb_search | **游客** + 全部登录角色 |
| `customer_service` | 客服助手 | `kb_sop` + `kb_company` | kb_search / escalate_human | 仅客服、管理员 |

`@` 候选列表与广场卡片都按角色过滤——**游客只看到「企业介绍」，患者看不到内部 SOP 助手**。

### 工具（Function Calling 注册表）

| 工具 | 作用 | 关键约束 |
| --- | --- | --- |
| `kb_search` | 查 Agent 绑定的知识库 | 库 code ∩ 调用方 ACL，过滤仍在检索层 |
| `policy_search` | 售后政策快捷检索 | 固定限定 `kb_after_sale` |
| `product_lookup` | 按名称/ID 查药品 | 结构化查询，不走向量 |
| `order_lookup` | 查订单与物流 | **只能看自己的**，看别人的返回 `FORBIDDEN`；support/admin 例外 |
| `remember` | 记忆草稿 | M3 会换成真正的记忆存储 |
| `escalate_human` | 请求转人工 | 敏感词（投诉/赔偿/过量…）自动触发 |

权限在**工具层**校验（`required_roles` + 数据归属），不依赖上层「记得检查」；
工具异常一律收敛成 `ToolResult(ok=False)`，单个工具挂掉不会让整条回答 500。

### SSE 事件协议（前端契约见 `docs/接口契约-M2.md`）

```
meta → route → agent(start) → tool / retrieval → agent(done) → citation → delta… → [handoff] → done
```

- 任何异常路径都必须以 `error` 或 `done` 收尾（`to_sse` 兜底），否则前端只能干等到超时。
- `delta` 里已经出现的角标**当场过滤**：`[9]` 不在本次上下文里就丢弃（流式下「先发后校验」不成立）。
- 药品类 Agent 的回答末尾必带免责声明（`guardrail.flags` 会记录 `disclaimer_injected`）。

### 实测延迟（deepseek-flash，本机）

| 场景 | 耗时 | 说明 |
| --- | --- | --- |
| 单 Agent（supervisor + 检索 + 流式生成） | 4.2~4.9s | 路由 1s + 检索 0.8s + 生成 2.5s |
| 双 `@` 并行（两路各答一段） | **5.0s** | 两路并行 2.9s + 确定性合并（≈0s） |
| 澄清 | 1.2s | 一次路由调用，不生成 |

> 多 Agent 汇总**默认不用模型**：来源由代码拼接、引用按全局重编号。理由有三条——
> 少一次完整生成（实测 9.4s → 5.0s）、绝不会把 A 的结论说成 B 的、归因可以断言。
> 需要更连贯的措辞时把 `CHAT_LLM_SYNTHESIS=true` 打开即可切回模型融合。

### 三分钟演示

1. `.\script\dev.ps1 agents` → `/agents` 广场：游客只看到「企业介绍」，登录后 3 个
2. 药品详情页问「哺乳期能吃吗」→ 逐字流式 + 可点开的 `[1]` 角标 + 免责声明
3. 同页输入 `@` → 选「订单售后」→ 问「我这单能退吗」→ 回答只讲订单维度（不越界）
4. 一条消息 `@AI药师 @订单售后 哺乳期能吃吗？这单能退吗？`→ 两段带来源的结论（≈5s）
5. 不 `@` 直接问「你们公司是做什么的」→ supervisor 自动路由到「企业介绍」（路由理由可见）
6. `/api/admin/agents` 新建一个 Agent（选库 + 选工具）→ 刷新 `/agents` 立刻出现

---

## 测试

```powershell
.\script\dev.ps1 test
```

- 单元测试**不连任何外部服务**（LLM / Milvus / PG / Langfuse），一律用 `app/testing/fakes.py`。
- 需要真实依赖的用例打 `@pytest.mark.integration`，默认跳过；`$env:RUN_INTEGRATION=1` 开启。

---

## 目录结构

```
backend/
├── app/
│   ├── agent/          # 编排（M2）
│   ├── api/            # 路由
│   ├── core/           # 配置 / 数据库 / 安全
│   ├── guardrail/      # 输出治理（M4）
│   ├── llm/            # 模型工厂 + 契约
│   ├── memory/         # 记忆（M3）
│   ├── models/         # ORM
│   ├── observability/  # Langfuse 接入 + 追踪契约
│   ├── rag/            # 解析/分块/检索（M1）
│   ├── schemas/        # Pydantic
│   ├── services/       # 业务服务
│   ├── testing/        # 测试替身
│   └── tools/          # Function Calling 注册表
├── alembic/            # 数据库迁移（alembic.ini 必须纯 ASCII）
└── tests/              # unit / integration / eval
frontend/src/           # Vue3 + Vant
docs/                   # 需求文档、任务清单
script/                 # dev.ps1、种子数据、自检脚本
```

---

## 已知约束

- 药品咨询 Agent 目前是**过渡实现**（把说明书整段拼进 prompt），M1-17 会替换为检索 + 引用 + 拒答。
- 前端暂无 e2e，靠手工回归清单保障。
- `docs/任务清单.md` 的估时按全职 40h/周计算，约 7 周完成全部里程碑。
