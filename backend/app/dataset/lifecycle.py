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
    """Allow edits unless the operator explicitly marked the version read-only.

    Workflow status and write permission are deliberately independent. Editing a
    previously approved or published version invalidates its certification and
    returns it to draft, while completed task snapshots remain immutable.
    """

    version = lock_dataset_version(session, version_id)
    if version.is_read_only:
        raise ValueError(
            f"数据版本 {version_id} 已由用户设为只读；请先解除只读后再修改。"
        )
    if version.status != "draft":
        version.status = "draft"
        version.content_hash = None
        version.change_summary = None
        version.reviewed_by = None
        version.reviewed_at = None
        version.approved_by = None
        version.approved_at = None
        version.published_at = None
        version.retired_at = None
    return version
