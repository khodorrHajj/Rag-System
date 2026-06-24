import logging
import sys

from fastapi import FastAPI

from app.api.router import api_router
from app.config import get_settings
from app.core.database import close_database_pool, warm_database_pool
from app.core.error_handlers import register_exception_handlers
from app.core.middleware import register_middlewares
from app.core.redis import close_redis_client
from app.services.embedding_service import get_embedding_model

_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(
    logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
)
_handler.setLevel(logging.INFO)
logging.getLogger("app").addHandler(_handler)
logging.getLogger("app").setLevel(logging.INFO)
logger = logging.getLogger(__name__)


def warm_startup_dependencies() -> None:
    settings = get_settings()

    if settings.warm_database_pool_on_startup:
        try:
            warm_database_pool(settings)
        except Exception:
            logger.warning(
                "Database pool warmup failed; continuing startup.", exc_info=True
            )

    if settings.warm_embedding_model_on_startup:
        try:
            get_embedding_model(settings)
        except Exception:
            logger.warning(
                "Embedding model warmup failed; continuing startup.", exc_info=True
            )


def create_app() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
    )
    register_middlewares(application)
    register_exception_handlers(application)
    application.include_router(api_router)
    application.add_event_handler("startup", warm_startup_dependencies)
    application.add_event_handler("shutdown", close_redis_client)
    application.add_event_handler("shutdown", close_database_pool)

    return application


app = create_app()
