from pydantic_settings import BaseSettings
from typing import List, Optional
import os
from functools import lru_cache

class Settings(BaseSettings):
    # Application
    ENVIRONMENT: str = "development"
    SECRET_KEY: str
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    DEBUG: bool = True
    BASE_URL: str = "https://yourapp.com"
    WEBHOOK_BASE_URL: str = "https://yourapp.com/api"
    
    # Database
    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Twilio
    TWILIO_ACCOUNT_SID: str
    TWILIO_AUTH_TOKEN: str
    TWILIO_PHONE_NUMBER: str
    TWILIO_MESSAGING_SERVICE_SID: str
    TWILIO_WORKSPACE_SID: str
    TWILIO_WORKFLOW_SID: str
    TWILIO_CONVERSATIONS_SERVICE_SID: str
    
    # AI Configuration
    OPENAI_API_KEY: str
    RISK_CLASSIFICATION_MODEL: str = "gpt-4"
    LLM_MODEL: str = "gpt-4"
    RISK_THRESHOLD_HIGH: float = 0.8
    RISK_THRESHOLD_MEDIUM: float = 0.5
    
    # Security
    ENCRYPTION_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24
    
    # Crisis Configuration
    CRISIS_KEYWORDS: str = "suicide,kill myself,end it all,can't go on,hopeless"
    EMERGENCY_CONTACT: str = "+1800273talk"
    CRISIS_RESPONSE_TIMEOUT_MINUTES: int = 5
    
    # Logging
    LOG_LEVEL: str = "INFO"
    SENTRY_DSN: Optional[str] = None
    
    @property
    def crisis_keywords_list(self) -> List[str]:
        return [kw.strip().lower() for kw in self.CRISIS_KEYWORDS.split(",")]
    
    class Config:
        env_file = ".env"
        case_sensitive = True

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
