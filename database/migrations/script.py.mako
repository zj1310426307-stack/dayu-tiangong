"""${message}

修订号：${up_revision}
上一修订：${down_revision | comma,n}
创建时间：${create_date}
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}


revision: str = ${repr(up_revision)}
down_revision: Union[str, Sequence[str], None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    """执行向前迁移。"""

    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """执行回退迁移。"""

    ${downgrades if downgrades else "pass"}
