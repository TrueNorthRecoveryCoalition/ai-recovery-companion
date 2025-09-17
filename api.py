from fastapi import APIRouter

from app.api.v1.endpoints import messaging, voice, escalations, checkins

api_router = APIRouter()

# Include all endpoint routers
api_router.include_router(
    messaging.router,
    prefix="/messaging",
    tags=["messaging"]
)

api_router.include_router(
    voice.router,
    prefix="/voice",
    tags=["voice"]
)

api_router.include_router(
    escalations.router,
    prefix="/escalations",
    tags=["escalations"]
)

api_router.include_router(
    checkins.router,
    prefix="/checkins",
    tags=["checkins"]
)

# Health check endpoint
@api_router.get("/health")
async def health_check():
    """API health check"""
    return {
        "status": "healthy",
        "service": "arc-api",
        "version": "1.0.0"
    }
