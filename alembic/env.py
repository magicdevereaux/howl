from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Pull settings so DATABASE_URL overrides the ini file
from app.config import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url from our settings (reads from .env)
config.set_main_option("sqlalchemy.url", settings.database_url)

# Import all models here so autogenerate can detect them.
# Example: from app.models.user import User  # noqa: F401
from app.models import *  # noqa: F401, F403

target_metadata = None  # replaced with Base.metadata once models exist


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
