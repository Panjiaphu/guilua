from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.templates import context, templates
from app.db.session import get_db
from app.services.rates import latest_rates


router = APIRouter()


@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request=request, name="home.html", context=context(request, rates=latest_rates(db)))
