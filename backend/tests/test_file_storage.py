"""验证统一上传读取、存储根和原子落盘契约。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import files
from app.ai import router as ai_router
from app.ai import service as ai_service
from app.ai.models import AIReport
from app.ai.schemas import ReportGenerateRequest, SourceCitation
from app.data_converter import importer as conversion_importer
from app.data_converter import exporter as conversion_exporter
from app.data_converter import router as conversion_router
from app.data_converter import validator as conversion_validator
from app.hydraulic import router as hydraulic_router
from app.import_service import router as import_router
from app.import_service import service as import_service


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class RecordingUpload:
    """记录调用方请求的读取上限。"""

    def __init__(self, filename: str, content: bytes) -> None:
        self.filename = filename
        self.content = content
        self.read_sizes: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        """模拟 UploadFile 的有界读取。"""

        self.read_sizes.append(size)
        return self.content if size < 0 else self.content[:size]


def test_limited_reader_requests_exactly_limit_plus_one() -> None:
    upload = RecordingUpload("input.bin", b"abcdef")

    content = asyncio.run(files.read_limited_upload(upload, 4))

    assert content == b"abcde"
    assert upload.read_sizes == [5]
    with pytest.raises(ValueError, match="positive"):
        asyncio.run(files.read_limited_upload(upload, 0))


def test_all_upload_routes_delegate_to_the_same_bounded_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []

    async def bounded(upload: RecordingUpload, max_bytes: int) -> bytes:
        calls.append((upload.filename, max_bytes))
        return b"payload"

    monkeypatch.setattr(files, "read_limited_upload", bounded)

    ai_upload = RecordingUpload("knowledge.txt", b"ignored")
    assert asyncio.run(ai_router._read_upload(ai_upload)) == b"payload"

    conversion_upload = RecordingUpload("map.geojson", b"ignored")
    assert asyncio.run(conversion_router._read_upload(conversion_upload)) == (
        "map.geojson",
        b"payload",
    )

    import_upload = RecordingUpload("assets.csv", b"ignored")
    assert asyncio.run(import_router._read_upload(import_upload, {".csv"})) == (
        b"payload",
        "assets.csv",
    )

    hydraulic_upload = RecordingUpload("network.nwk11", b"ignored")
    assert asyncio.run(hydraulic_router._read_upload(hydraulic_upload)) == (
        "network.nwk11",
        b"payload",
    )

    assert calls == [
        ("knowledge.txt", ai_service.MAX_UPLOAD_BYTES),
        ("map.geojson", conversion_validator.MAX_UPLOAD_BYTES),
        ("assets.csv", import_router.MAX_UPLOAD_BYTES),
        ("network.nwk11", hydraulic_router.MAX_UPLOAD_BYTES),
    ]


def test_existing_upload_error_statuses_and_messages_are_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsupported = RecordingUpload("assets.exe", b"content")
    with pytest.raises(HTTPException) as import_suffix:
        asyncio.run(import_router._read_upload(unsupported, {".csv"}))
    assert import_suffix.value.status_code == 415
    assert import_suffix.value.detail == "仅支持 .csv"
    assert unsupported.read_sizes == []

    monkeypatch.setattr(import_router, "MAX_UPLOAD_BYTES", 2)
    with pytest.raises(HTTPException) as import_size:
        asyncio.run(
            import_router._read_upload(RecordingUpload("assets.csv", b"1234"), {".csv"})
        )
    assert import_size.value.status_code == 413
    assert import_size.value.detail == "上传文件不得超过 20 MB"

    monkeypatch.setattr(hydraulic_router, "MAX_UPLOAD_BYTES", 2)
    with pytest.raises(HTTPException) as hydraulic_size:
        asyncio.run(
            hydraulic_router._read_upload(RecordingUpload("network.nwk11", b"1234"))
        )
    assert hydraulic_size.value.status_code == 413
    assert hydraulic_size.value.detail == "上传文件不得超过 100 MB"

    monkeypatch.setattr(conversion_validator, "MAX_UPLOAD_BYTES", 2)
    filename, content = asyncio.run(
        conversion_router._read_upload(RecordingUpload("map.geojson", b"1234"))
    )
    with pytest.raises(
        conversion_validator.ConversionValidationError,
        match="uploaded geospatial file exceeds 100 MB",
    ):
        conversion_validator.validate_upload(filename, content)
    assert conversion_router._error(
        conversion_validator.ConversionValidationError("oversized")
    ).status_code == 422

    monkeypatch.setattr(ai_service, "MAX_UPLOAD_BYTES", 2)
    ai_content = asyncio.run(
        ai_router._read_upload(RecordingUpload("knowledge.txt", b"1234"))
    )
    with pytest.raises(ai_service.AIServiceError, match="知识文档不能超过 10 MB"):
        ai_service._decode_document("knowledge.txt", ai_content)
    assert ai_router._http_error(ai_service.AIServiceError("oversized")).status_code == 422


def test_storage_root_uses_one_environment_variable_and_rejects_escape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured = tmp_path / "dayu-files"
    monkeypatch.setenv("DAYU_STORAGE_ROOT", str(configured))

    assert files.configured_storage_root() == configured.resolve()
    assert files.storage_directory("imports") == (configured / "imports").resolve()
    with pytest.raises(ValueError, match="one path segment"):
        files.storage_directory("../escape")
    with pytest.raises(ValueError, match="escapes"):
        files.resolve_within(configured, "..", "escape")
    with pytest.raises(ValueError, match="relative"):
        files.resolve_within(configured, tmp_path / "absolute")


def test_relative_storage_root_is_resolved_from_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DAYU_STORAGE_ROOT", "runtime/dayu-storage")

    assert files.configured_storage_root() == (
        REPOSITORY_ROOT / "runtime" / "dayu-storage"
    ).resolve()


def test_atomic_writer_publishes_complete_file_and_cleans_failed_temporary(
    tmp_path: Path,
) -> None:
    target = files.atomic_write_bytes(tmp_path, "artifact.bin", b"complete")

    assert target.read_bytes() == b"complete"
    assert list(tmp_path.glob("*.tmp")) == []
    with pytest.raises(RuntimeError, match="producer failed"):
        with files.atomic_output_path(tmp_path, "failed.bin") as (temporary, _target):
            assert not temporary.exists()
            temporary.write_bytes(b"partial")
            raise RuntimeError("producer failed")
    assert not (tmp_path / "failed.bin").exists()
    assert list(tmp_path.glob("*.tmp")) == []
    with pytest.raises(ValueError, match="one path segment"):
        files.atomic_write_bytes(tmp_path, "nested/escape.bin", b"blocked")


def test_existing_storage_constants_remain_monkeypatchable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    imports_root = tmp_path / "imports"
    monkeypatch.setattr(import_service, "STORAGE_ROOT", imports_root)
    stored_name = import_service.store_upload("../../survey.csv", b"a,b\n1,2\n")
    assert (imports_root / stored_name).read_bytes() == b"a,b\n1,2\n"
    assert (imports_root / stored_name).parent == imports_root

    conversions_root = tmp_path / "conversions"
    monkeypatch.setattr(conversion_importer, "STORAGE_ROOT", conversions_root)
    job_id, input_format, source = conversion_importer.stage_upload(
        "survey.geojson", b'{"type":"FeatureCollection","features":[]}'
    )
    assert source == conversions_root / job_id / "source.geojson"
    assert source.is_file()
    assert input_format == "GeoJSON"


def test_routes_and_container_share_the_file_boundary_contract() -> None:
    route_paths = (
        "backend/app/ai/router.py",
        "backend/app/data_converter/router.py",
        "backend/app/import_service/router.py",
        "backend/app/hydraulic/router.py",
    )
    for relative in route_paths:
        source = (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")
        assert "await file.read(" not in source
        assert "files.read_limited_upload" in source

    nginx = (REPOSITORY_ROOT / "docker/nginx.conf").read_text(encoding="utf-8")
    dockerfile = (REPOSITORY_ROOT / "docker/backend.Dockerfile").read_text(encoding="utf-8")
    compose = (REPOSITORY_ROOT / "docker/docker-compose.yml").read_text(encoding="utf-8")
    env_example = (REPOSITORY_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "client_max_body_size 102m;" in nginx
    assert "COPY outputs/HYDRO-DATA-01-20260818" in dockerfile
    assert "DAYU_STORAGE_ROOT: /app/backend/storage" in compose
    assert compose.count(
        "${DAYU_STORAGE_HOST_PATH:-../backend/storage}:/app/backend/storage"
    ) == 3  # Backend plus the legacy and dedicated native-v4 Workers.
    assert '"127.0.0.1:${BACKEND_PORT:-8001}:8000"' in compose
    assert "DAYU_STORAGE_ROOT=backend/storage" in env_example
    assert "DAYU_STORAGE_HOST_PATH=../backend/storage" in env_example


def test_failed_conversion_export_is_atomic_and_cleans_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(conversion_importer, "STORAGE_ROOT", tmp_path)
    job_id, _input_format, source = conversion_importer.stage_upload(
        "survey.geojson", b'{"type":"FeatureCollection","features":[]}'
    )

    def fail_export(_source: Path, target: Path, _srid: int) -> None:
        target.write_bytes(b"partial")
        raise RuntimeError("producer failed")

    monkeypatch.setattr(conversion_exporter.gdal_service, "vector_to_geojson", fail_export)
    with pytest.raises(RuntimeError, match="producer failed"):
        conversion_exporter.to_geojson(source, 4490)
    assert not (source.parent / "output.geojson").exists()

    conversion_importer.cleanup_job(job_id)
    assert not (tmp_path / job_id).exists()


def test_report_object_key_and_legacy_path_resolution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report_root = tmp_path / "current" / "ai-reports"
    report_root.mkdir(parents=True)
    current = report_root / "current.md"
    current.write_text("current", encoding="utf-8")
    monkeypatch.setattr(ai_service, "REPORT_ROOT", report_root)

    class ReportSession:
        def __init__(self, path: str) -> None:
            self.report = SimpleNamespace(markdown_path=path, pdf_path=path)

        def get(self, _model: object, _report_id: int) -> object:
            return self.report

    path, _media_type = ai_service.get_report_file(
        ReportSession("ai-reports/current.md"), 1, "markdown"  # type: ignore[arg-type]
    )
    assert path == current

    legacy_root = REPOSITORY_ROOT / "backend" / "storage" / "ai-reports"
    legacy_root.mkdir(parents=True, exist_ok=True)
    legacy = legacy_root / "legacy-storage-test.md"
    legacy.write_text("legacy", encoding="utf-8")
    try:
        path, _media_type = ai_service.get_report_file(
            ReportSession("backend/storage/ai-reports/legacy-storage-test.md"), 1, "markdown"  # type: ignore[arg-type]
        )
        assert path == legacy.resolve()
    finally:
        legacy.unlink(missing_ok=True)


def test_report_files_are_compensated_when_database_commit_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ai_service, "REPORT_ROOT", tmp_path)
    monkeypatch.setattr(
        ai_service,
        "_resolve_dataset_version",
        lambda _session, _version_id: SimpleNamespace(id=1),
    )
    citation = SourceCitation(
        source_type="database",
        title="受控测试来源",
        reference="test://source",
        version="v1",
    )

    def fake_tool(
        _session: object, tool_name: str, _context: object
    ) -> tuple[object, object, object]:
        return (
            {"tool": tool_name},
            citation,
            {
                "tool_name": tool_name,
                "input": {},
                "output": {},
                "duration_ms": 0,
            },
        )

    monkeypatch.setattr(ai_service, "_call_tool", fake_tool)
    monkeypatch.setattr(ai_service, "build_dispatch_report", lambda *_args: "# report")
    monkeypatch.setattr(
        ai_service,
        "markdown_to_pdf",
        lambda _markdown, path: path.write_bytes(b"%PDF-1.4"),
    )

    class FailingCommitSession:
        def __init__(self) -> None:
            self.report: AIReport | None = None
            self.rolled_back = False

        def add(self, value: object) -> None:
            if isinstance(value, AIReport):
                self.report = value

        def flush(self) -> None:
            assert self.report is not None
            self.report.id = 77

        def commit(self) -> None:
            raise RuntimeError("database commit failed")

        def rollback(self) -> None:
            self.rolled_back = True

    session = FailingCommitSession()
    with pytest.raises(RuntimeError, match="database commit failed"):
        ai_service.generate_report(  # type: ignore[arg-type]
            session, ReportGenerateRequest()
        )

    assert session.rolled_back is True
    assert list(tmp_path.iterdir()) == []
