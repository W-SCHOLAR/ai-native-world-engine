"""Runtime repository selection for the product API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .repository import (
    InMemoryRunRepository,
    JsonFileRunRepository,
    RunRepository,
    SQLiteRunRepository,
)


REPOSITORY_ENV = "AI_NATIVE_WORLD_REPOSITORY"
DATA_DIR_ENV = "AI_NATIVE_WORLD_DATA_DIR"
SQLITE_PATH_ENV = "AI_NATIVE_WORLD_SQLITE_PATH"
JSON_DATA_DIR_ENV = "AI_NATIVE_WORLD_JSON_DATA_DIR"
DATABASE_URL_ENV = "AI_NATIVE_WORLD_DATABASE_URL"
DEFAULT_REPOSITORY = "sqlite"
DEFAULT_DATA_DIR = ".data"
DEFAULT_SQLITE_FILENAME = "ai-native-world.sqlite3"


@dataclass(frozen=True, slots=True)
class RepositoryRuntimeConfig:
    mode: str = DEFAULT_REPOSITORY
    data_dir: Path = Path(DEFAULT_DATA_DIR)
    sqlite_path: Path | None = None
    json_data_dir: Path | None = None
    database_url: str = ""

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "RepositoryRuntimeConfig":
        values = env if env is not None else os.environ
        mode = str(values.get(REPOSITORY_ENV, DEFAULT_REPOSITORY)).strip().lower()
        data_dir = Path(values.get(DATA_DIR_ENV, DEFAULT_DATA_DIR))
        sqlite_path = values.get(SQLITE_PATH_ENV)
        json_data_dir = values.get(JSON_DATA_DIR_ENV)
        return cls(
            mode=mode,
            data_dir=data_dir,
            sqlite_path=Path(sqlite_path) if sqlite_path else None,
            json_data_dir=Path(json_data_dir) if json_data_dir else None,
            database_url=str(values.get(DATABASE_URL_ENV, "")).strip(),
        )

    def resolved_sqlite_path(self) -> Path:
        return self.sqlite_path or self.data_dir / DEFAULT_SQLITE_FILENAME

    def resolved_json_data_dir(self) -> Path:
        return self.json_data_dir or self.data_dir / "json-repository"


def create_run_repository(env: Mapping[str, str] | None = None) -> RunRepository:
    config = RepositoryRuntimeConfig.from_env(env)
    if config.mode == "memory":
        return InMemoryRunRepository()
    if config.mode == "json":
        return JsonFileRunRepository(config.resolved_json_data_dir())
    if config.mode == "sqlite":
        return SQLiteRunRepository(config.resolved_sqlite_path())
    if config.mode == "postgres":
        if not config.database_url:
            raise ValueError(f"{DATABASE_URL_ENV} is required for PostgreSQL repository mode")
        from .postgres_repository import PostgresRunRepository

        return PostgresRunRepository(config.database_url)
    raise ValueError(
        f"unsupported {REPOSITORY_ENV}: {config.mode}. "
        "Expected one of: memory, json, sqlite, postgres."
    )
