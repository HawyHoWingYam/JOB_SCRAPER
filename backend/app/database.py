from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings


def should_echo_sql(*, debug: bool, sqlalchemy_echo: bool) -> bool:
    """Keep auto-reload/debug separate from SQL trace logging."""
    return sqlalchemy_echo


# Create database engine
engine = create_engine(
    settings.database_url,
    echo=should_echo_sql(
        debug=settings.debug,
        sqlalchemy_echo=settings.sqlalchemy_echo,
    ),
    pool_pre_ping=True,  # Verify connections before using them
    pool_size=10,
    max_overflow=20,
)

# Create session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# Base class for ORM models
Base = declarative_base()


def get_db():
    """Dependency for FastAPI to inject database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
