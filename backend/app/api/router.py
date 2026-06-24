from fastapi import APIRouter

from app.api.admin_routes import router as admin_router
from app.api.auth_routes import router as auth_router
from app.api.chat_routes import router as chat_router
from app.api.document_routes import router as document_router
from app.api.eval_routes import router as eval_router
from app.api.feedback_routes import router as feedback_router
from app.api.retrieval_routes import router as retrieval_router
from app.api.routes import router as health_router
from app.config import get_settings

settings = get_settings()

api_router = APIRouter(prefix=settings.api_prefix)
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(document_router)
api_router.include_router(retrieval_router)
api_router.include_router(chat_router)
api_router.include_router(feedback_router)
api_router.include_router(eval_router)
api_router.include_router(admin_router)
