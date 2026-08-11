import io

from PIL import Image

from app.pipeline.pipeline import VerificationPipeline
from app.providers.bailian_kb import MockKBAdapter
from app.providers.bailian_search import MockSearchAdapter
from app.providers.dashscope_llm import MockLLMAdapter
from app.providers.local_storage import LocalStorageAdapter
from app.services.analysis_service import AnalysisService
from app.services.source_registry import get_source_registry


def _jpeg() -> bytes:
    image = Image.new("RGB", (80, 80), color=(100, 120, 140))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def test_original_image_never_persisted_even_if_legacy_flag_is_true(
    session, settings, tmp_path
):
    configured = settings.model_copy(
        update={"keep_original_image": True, "storage_local_dir": str(tmp_path / "images")}
    )
    llm = MockLLMAdapter()
    pipeline = VerificationPipeline(
        configured, llm, MockKBAdapter(), MockSearchAdapter(), get_source_registry()
    )
    service = AnalysisService(configured, pipeline, LocalStorageAdapter(configured))

    analysis = service.create_task(session, _jpeg(), "private-photo.jpg")
    session.flush()

    assert analysis.image_path is None
    assert analysis.expires_at is None
    assert not configured.storage_dir.exists() or not any(configured.storage_dir.iterdir())
