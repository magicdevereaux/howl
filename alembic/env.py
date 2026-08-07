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

from app.models import Base  # noqa: F401 — imports User too via __init__

target_metadata = Base.metadata

# Without these, `alembic revision --autogenerate` silently ignores column type
# changes (String(50) -> String(100), Integer -> BigInteger) and server-default
# changes, so drift between the models and the migrations accumulates unseen.
# Keeping them on means a clean checkout must autogenerate an *empty* migration;
# if it doesn't, models and migrations have diverged.
COMPARE_OPTS = {
    "compare_type": True,
    "compare_server_default": True,
}


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **COMPARE_OPTS,
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
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            **COMPARE_OPTS,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
