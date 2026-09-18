"""Helpers shared by independently routed API features."""

from fastapi import HTTPException
from sqlalchemy.orm import Session


def get_or_404(db: Session, model: type, entity_id: int, label: str):
    entity = db.get(model, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"{label} {entity_id} was not found")
    return entity
