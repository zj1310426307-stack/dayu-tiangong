"""Dataset-version editability guards shared by every data write entry point."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.gis.models import DatasetVersion


def lock_dataset_version(session: Session, version_id: int) -> DatasetVersion:
    """Reload and lock one Dataset Version for a serialized state decision."""

    # Lock the version identity for the complete caller transaction.  Content
    # mutations and publication therefore serialize on the same row instead
    # of racing between a draft check and the eventual write/commit.
    version = session.scalar(
        select(DatasetVersion)
        .where(DatasetVersion.id == version_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if version is None:
        raise ValueError("Dataset version does not exist.")
    return version


def assert_dataset_version_mutable(session: Session, version_id: int) -> DatasetVersion:
    """Allow content writes only to an explicitly writable Draft Version.

    A DatasetVersion is an engineering identity, not a mutable container.  Its
    lifecycle state therefore cannot be silently rewritten by a content write.
    ``is_read_only`` is deliberately only the manual edit lock for a Draft.
    """

    version = lock_dataset_version(session, version_id)
    if version.status != "draft":
        raise ValueError(
            "DAYU_DATASET_VERSION_IMMUTABLE: 该数据版本已审核、批准、发布或退役，"
            "不能原地修改；请基于当前版本创建新的草稿版本。"
        )
    if version.is_read_only:
        raise ValueError(
            f"数据版本 {version_id} 已由用户设为只读；请先解除只读后再修改。"
        )
    return version
