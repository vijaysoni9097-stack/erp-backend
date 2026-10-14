from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


settings = get_settings()

database_url = make_url(settings.database_url)
if database_url.drivername in ('postgres', 'postgresql'):
    database_url = database_url.set(drivername='postgresql+psycopg')
is_postgres = database_url.get_backend_name() == 'postgresql'
if settings.require_postgres and not is_postgres:
    raise RuntimeError('Hosted testing requires persistent PostgreSQL; SQLite is not allowed')
connect_args = {"check_same_thread": False} if database_url.get_backend_name() == 'sqlite' else {}
if is_postgres:
    connect_args.update(options=f'-csearch_path={settings.database_schema}', prepare_threshold=None)
engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)

if is_postgres:
    @event.listens_for(engine, "connect")
    def configure_postgres(connection, _):
        # Poolers may ignore startup options; set the schema on every connection.
        previous_autocommit = connection.autocommit
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute(f'SET SESSION search_path TO "{settings.database_schema}"')
        finally:
            connection.autocommit = previous_autocommit


def initialize_schema():
    if is_postgres:
        from sqlalchemy.schema import CreateSchema
        with engine.begin() as connection:
            connection.execute(CreateSchema(settings.database_schema, if_not_exists=True))


def lock_inventory(db):
    """Serialize stock transactions across hosted API instances."""
    if db.bind.dialect.name == 'postgresql':
        from sqlalchemy import text
        db.execute(text('SELECT pg_advisory_xact_lock(hashtext(current_schema()), 73142)'))


if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """Provide one database session per request and always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
