import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api import jobs as jobs_api
from app.services import retrieval_service
from app.services.retrieval_service import RetrievalService


def test_lexical_mode_does_not_require_embedding_model(monkeypatch):
    lexical_query = object()
    captured = {}

    monkeypatch.setattr(
        retrieval_service,
        "_build_default_query_embedding_model",
        lambda: (_ for _ in ()).throw(AssertionError("embedding model should not be loaded")),
    )
    monkeypatch.setattr(retrieval_service, "build_lexical_query", lambda db, scope: lexical_query)
    monkeypatch.setattr(
        jobs_api,
        "_build_search_response",
        lambda query, **kwargs: captured.setdefault("response", (query, kwargs)),
    )

    request = SimpleNamespace(
        retrieval_mode="lexical",
        scope=SimpleNamespace(layers=[]),
        page=1,
        page_size=20,
    )

    result = RetrievalService(db=object()).search(request)

    assert result == captured["response"]
    assert captured["response"][0] is lexical_query
    assert captured["response"][1]["page"] == 1
    assert captured["response"][1]["page_size"] == 20


def test_semantic_mode_with_empty_query_text_does_not_require_embedding_model(monkeypatch):
    lexical_query = object()
    captured = {}

    monkeypatch.setattr(
        retrieval_service,
        "_build_default_query_embedding_model",
        lambda: (_ for _ in ()).throw(AssertionError("embedding model should not be loaded")),
    )
    monkeypatch.setattr(retrieval_service, "build_lexical_query", lambda db, scope: lexical_query)
    monkeypatch.setattr(retrieval_service, "extract_semantic_query_text", lambda scope: "")
    monkeypatch.setattr(
        jobs_api,
        "_build_search_response",
        lambda query, **kwargs: captured.setdefault("response", (query, kwargs)),
    )

    request = SimpleNamespace(
        retrieval_mode="semantic",
        scope=SimpleNamespace(layers=[]),
        page=2,
        page_size=10,
    )

    result = RetrievalService(db=object()).search(request)

    assert result == captured["response"]
    assert captured["response"][0] is lexical_query
    assert captured["response"][1]["page"] == 2
    assert captured["response"][1]["page_size"] == 10
