import sys
import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# 1. Force the current directory into the path
sys.path.insert(0, os.getcwd())

# 2. Verify we are in the right place
print(f"DEBUG: Current working directory is {os.getcwd()}")
print(f"DEBUG: sys.path is {sys.path}")

# 3. Import models
# If your folder structure is hirematch-backend/app/models/base.py
# then 'from app.models.base import Base' is correct ONLY IF 
# the terminal is in 'hirematch-backend'
from app.db.base import Base
import app.models

target_metadata = Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

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
        context.configure(
            connection=connection, 
            target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()