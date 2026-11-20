from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 动态计算 .env 的绝对路径
# config.py 的路径是 backend/app/core/config.py
# parents[0]=core, parents[1]=app, parents[2]=backend, parents[3]=hhyy(项目根目录)
BASE_DIR = Path(__file__).resolve().parents[3]
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    # ── 站点信息（显示在 /docs 的抬头与 OpenAPI 里，改这里不用动代码）──
    app_name: str = "花红医药 Agent 系统"
    app_description: str = (
        "面向医药电商场景的多 Agent + RAG 平台："
        "Agent 配置化编排、知识库检索带引用、三层记忆、转人工闭环，以及一套可评估的输出治理。"
    )
    app_version: str = "MVP"

    # ── 应用 ──
    app_env: str = "development"
    log_level: str = "INFO"
    secret_key: str = "SECRET_KEY"

    # --- DeepSeek 配置 ---
    # 凭据默认留空：缺失时不让整个服务崩，而在真正调用时给出明确错误（见 llm.client）
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_chat_model: str = "deepseek-flash"

    # --- 模型调用通用参数 ---
    llm_temperature: float = 0.3
    llm_timeout: int = 60
    llm_max_retries: int = 2

    # ── DashScope（Embedding）──
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_embedding_model: str = "text-embedding-v4"
    embedding_dimensions: int = 1024
    embedding_batch_size: int = 10

    # --- 检索（RAG）---
    rag_collection: str = "hhyy_kb_chunks"
    retrieval_top_k: int = 30
    rerank_top_n: int = 5
    # 余弦相似度阈值：仅在重排不可用、退回 dense 检索时使用，库未配置时取这个默认值
    score_threshold: float = Field(default=0.30, ge=0.0, le=1.0)
    rerank_model: str = "gte-rerank-v2"
    rerank_base_url: str = "https://dashscope.aliyuncs.com"
    rerank_enabled: bool = True
    # 重排分阈值：重排分和余弦分是两套分布，不能共用一个数（实测见 rag/reranker.py）。
    # 0.15 来自 10 正 / 10 负问题的实测分界：负例最高 0.135，正例最低 0.175。
    rerank_score_threshold: float = Field(default=0.15, ge=0.0, le=1.0)
    # ACL 缓存存活时间：PRD §3.4 要求权限变更 ≤30s 生效
    acl_cache_ttl: int = 30

    # --- 知识库（M1）---
    kb_storage_dir: str = "backend/static/kb"  # 相对仓库根
    kb_max_file_mb: int = 20
    kb_chunk_max_chars: int = 800

    # --- 记忆 ---
    memory_collection: str = "hhyy_memory"
    memory_enabled: bool = True
    memory_ttl_days: int = 180
    # 每次注入 prompt 的记忆条数（PRD FR6.5 的 top 3）
    memory_inject_limit: int = 3
    # 关闭后连抽取都不跑（省一次后台模型调用）；用户级开关在 user_profiles.memory_enabled
    memory_extract_enabled: bool = True
    # 短期记忆：原文保留轮数 + token 预算（PRD FR6.1 / §13）
    memory_window_turns: int = 10
    memory_history_budget: int = 1500

    # --- LangGraph checkpointer（M3-01）---
    # 关掉后图状态不落库（对话仍可用，只是重启后没有图上下文）
    checkpointer_enabled: bool = True

    # --- 人工介入 ---
    handoff_queue_timeout: int = 90
    # 连续 N 次拒答 / N 轮负面情绪 → 建议转人工（PRD FR5.1）
    handoff_refusal_streak: int = 2    # WebSocket 短期 ticket 有效期（先 HTTP 拿 ticket，再连 WS）
    ws_ticket_ttl: int = 60
    # 服务端心跳间隔：客户端 90s 收不到任何帧就该重连
    ws_heartbeat_seconds: int = 25

    # --- 多 Agent / 对话（M2）---
    # Agent 配置缓存 TTL：后台改完会主动失效，这个 TTL 只是多 worker 下的兜底
    agent_registry_ttl: int = 60
    # 单个子 Agent 的硬超时（PRD FR1.7）：超时用已得结果作答，不让整条回答挂住
    agent_timeout_seconds: float = 8.0
    # 每用户（或每 IP）每分钟对话次数上限
    chat_rate_limit_per_minute: int = 20
    # 幂等窗口：同一 client_message_id 在窗口内重放上次结果（PRD FR1.8）
    chat_idempotency_seconds: int = 300
    # 带进 prompt 的历史轮数（一问一答算一轮）
    chat_history_turns: int = 6
    # supervisor 置信度低于该值时先澄清/给转人工（PRD FR1.4）。
    # 0.5 是实测校准值：小模型对「这个药怎么购买」这种短句常给 0.55~0.65，
    # 定 0.6 会把本来能答的问题变成一句「请问你问的是哪一类」。
    supervisor_confidence_floor: float = 0.5
    # 关闭后所有「没有 @ 的提问」都直连主 Agent（省一次模型调用，但多 Agent 就没入口了）
    supervisor_enabled: bool = True
    # 多 Agent 汇总是否再花一次模型调用做「语言融合」。默认关：
    # 确定性合并（代码拼来源）更快、也不会把 A 的结论说成 B 的。
    chat_llm_synthesis: bool = False

    # --- Langfuse（可观测）---
    # 三个值任一缺失即视为未启用，服务照常运行，仅不做上报
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = ""

    # --- 数据库配置 ---
    postgres_server: str = "localhost"
    postgres_user: str = "agent_user"
    postgres_password: str = "agent_password"
    postgres_db: str = "agent_db"
    postgres_port: int = 5432

    # --- Redis 配置 ---
    redis_host: str = "localhost"
    redis_port: int = 6379

    # --- Milvus 配置 ---
    milvus_uri: str = "http://localhost:19530"
    milvus_token: str = ""  # 本地 standalone 不需要认证，留空即可

    # --- M4：成本估算（元 / 千 token）---
    # 看板里的「成本」是按单价估算，不是账单；官方调价时改这两个值即可，
    # 不要让看板去猜（Langfuse 的 cost 只有接了它的 cost 表才有）。
    llm_price_input_per_1k: float = 0.0005
    llm_price_output_per_1k: float = 0.002

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_server}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def observability_enabled(self) -> bool:
        """Langfuse 三要素齐全才启用，否则全链路按 no-op 处理。"""
        return bool(
            self.langfuse_public_key
            and self.langfuse_secret_key
            and self.langfuse_base_url
        )

    @property
    def llm_configured(self) -> bool:
        return bool(self.deepseek_api_key)

    @property
    def embedding_configured(self) -> bool:
        return bool(self.dashscope_api_key and self.dashscope_base_url)

    # 强制指定读取绝对路径的 .env
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
