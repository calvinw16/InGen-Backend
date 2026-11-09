from alembic import context

from app.core.config import settings
from app.models.telemetry import metadata
from app.services.telemetry_store import make_engine

if context.is_offline_mode():
    context.configure(
        url=settings.database_url, target_metadata=metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied = context.config.attributes.get("connection")
    if supplied is not None:
        context.configure(connection=supplied, target_metadata=metadata)
        with context.begin_transaction():
            context.run_migrations()
    else:
        with make_engine(settings.database_url).connect() as connection:
            context.configure(connection=connection, target_metadata=metadata)
            with context.begin_transaction():
                context.run_migrations()
