"""Dataset-version immutability guards shared by every legacy write entry point."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.gis.models import DatasetVersion


def assert_dataset_version_mutable(session: Session, version_id: int) -> DatasetVersion:
    """Allow core edits only while a version remains an explicit draft."""

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
    if version.status != "draft":
        raise ValueError(
            f"Dataset version {version_id} is {version.status} and is immutable."
        )
    return version
