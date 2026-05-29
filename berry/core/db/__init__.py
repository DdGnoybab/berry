"""数据库模型 + session。

为了让 alembic --autogenerate 检测到所有表,
任何新加的 SQLModel 都必须确保被 import 一次。

我们在 alembic/env.py 里 import berry.db.models,
所以模型类都放在 models.py 里一次性导出。
"""

from berry.core.db import models  # noqa: F401  确保 models 被加载,SQLModel.metadata 里有表
