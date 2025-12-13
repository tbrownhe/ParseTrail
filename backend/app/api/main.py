from fastapi import APIRouter

from app.api.routes import (
    clients,
    items,
    keys,
    login,
    models,
    plugins,
    statements,
    users,
    utils,
)

api_router = APIRouter()
api_router.include_router(login.router, tags=["login"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(utils.router, prefix="/utils", tags=["utils"])
api_router.include_router(items.router, prefix="/items", tags=["items"])
api_router.include_router(keys.router, prefix="/keys", tags=["keys"])
api_router.include_router(models.router, prefix="/models", tags=["models"])
api_router.include_router(plugins.router, prefix="/plugins", tags=["plugins"])
api_router.include_router(clients.router, prefix="/clients", tags=["clients"])
api_router.include_router(statements.router, prefix="/statements", tags=["statements"])
