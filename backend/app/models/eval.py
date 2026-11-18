"""评估运行结果（M4-02 / M4-04）。

一次运行一行：指标与失败样例都放 JSONB，字段结构随评估器演进，
不需要每加一个指标就改表。看板只关心「最新一次」和「历史趋势」。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # retrieval（不调模型，快）/ full（走完整链路）
    mode: Mapped[str] = mapped_column(String(16), default="retrieval")
    cases: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    failures: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    ran_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )


__all__ = ["EvalRun"]
