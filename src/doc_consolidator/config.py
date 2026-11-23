"""Settings. No list-typed fields: Pydantic Settings parses those as JSON, so `DC_X=a,b`
would fail with a decode error that reads like a bug in the tool rather than a bad value.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .outline import Reading
from .tables import FlattenPolicy


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DC_", env_file=".env", extra="ignore"
    )

    docs: Path = Path("data/docs")
    target: str = "markdown"
    """Defaults to markdown because that is what people pick, and it is the target this
    tool has the most to say about."""

    reading: Reading = Reading.PROMOTE
    policy: FlattenPolicy = FlattenPolicy.DUPLICATE
    max_list_depth: int = Field(default=3, ge=1)
    """Beyond this a nested list is reported as DEGRADED. A limit, not a fact -- most
    formats have no hard cap, and deep nesting stops surviving round trips in practice."""
