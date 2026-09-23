from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.offertoday_keyword_pack import (
    OfferTodayKeywordCsvConfirmRequestV1,
    OfferTodayKeywordCsvConfirmV1,
    OfferTodayKeywordCsvPreviewRequestV1,
    OfferTodayKeywordCsvPreviewV1,
    OfferTodayKeywordEntryV1,
    OfferTodayKeywordPackListV1,
)
from app.services.offertoday_keyword_catalog import (
    OfferTodayKeywordCatalog,
    OfferTodayKeywordCatalogError,
)


router = APIRouter(
    prefix="/offertoday-keyword-packs",
    tags=["offertoday-keyword-packs"],
)
KEYWORD_PACK_API_ACTOR = "local-operator"


def _http_error(exc: OfferTodayKeywordCatalogError) -> HTTPException:
    return HTTPException(
        status_code=(
            status.HTTP_409_CONFLICT
            if exc.code == "KEYWORD_CSV_REVIEW_STALE"
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        ),
        detail=exc.to_detail(),
    )


@router.get("", response_model=OfferTodayKeywordPackListV1)
def list_keyword_packs(
    db: Session = Depends(get_db),
) -> OfferTodayKeywordPackListV1:
    catalog = OfferTodayKeywordCatalog(db)
    items = tuple(OfferTodayKeywordEntryV1.model_validate(item) for item in catalog.list_entries())
    enabled_counts = Counter(
        item.classification_id for item in items if item.enabled
    )
    return OfferTodayKeywordPackListV1(
        items=items,
        enabled_counts=dict(sorted(enabled_counts.items())),
        catalog_fingerprint=catalog.catalog_fingerprint(),
        catalog_updated_at=catalog.catalog_updated_at(),
    )


@router.get("/csv")
def export_keyword_packs_csv(db: Session = Depends(get_db)) -> Response:
    return Response(
        content=OfferTodayKeywordCatalog(db).export_csv(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                'attachment; filename="offertoday-keyword-packs.csv"'
            )
        },
    )


@router.post("/csv/preview", response_model=OfferTodayKeywordCsvPreviewV1)
def preview_keyword_packs_csv(
    request: OfferTodayKeywordCsvPreviewRequestV1,
    db: Session = Depends(get_db),
) -> OfferTodayKeywordCsvPreviewV1:
    try:
        preview = OfferTodayKeywordCatalog(db).preview_csv(
            request.csv_content.encode("utf-8"),
            actor=KEYWORD_PACK_API_ACTOR,
        )
        return OfferTodayKeywordCsvPreviewV1.model_validate(preview.to_payload())
    except OfferTodayKeywordCatalogError as exc:
        raise _http_error(exc) from exc


@router.post("/csv/confirm", response_model=OfferTodayKeywordCsvConfirmV1)
def confirm_keyword_packs_csv(
    request: OfferTodayKeywordCsvConfirmRequestV1,
    db: Session = Depends(get_db),
) -> OfferTodayKeywordCsvConfirmV1:
    try:
        result = OfferTodayKeywordCatalog(db).confirm_csv(
            confirmation_token=request.confirmation_token,
            csv_hash=request.csv_hash,
            actor=KEYWORD_PACK_API_ACTOR,
        )
        return OfferTodayKeywordCsvConfirmV1.model_validate(result)
    except OfferTodayKeywordCatalogError as exc:
        raise _http_error(exc) from exc


__all__ = ["router"]
