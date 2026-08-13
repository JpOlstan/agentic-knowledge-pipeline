from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from knowledge_agents.domain.budgets import ContextBudget


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    env: Literal["dev", "test", "prod"] = "dev"
    vault_path: Path = Path("vault")
    vault_allowed_paths: tuple[str, ...] = ("01-inbox/agent-runs",)
    runtime_path: Path = Path("runtime")

    openai_model_agent_1: str = "gpt-5.6-terra"
    openai_model_agent_2: str = "gpt-5.6-terra"
    openai_model_agent_3: str = "gpt-5.6-terra"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dimensions: int = Field(default=1_536, gt=0)
    openai_api_key: SecretStr | None = None

    qdrant_url: AnyHttpUrl = "http://127.0.0.1:6333"
    aws_region: str = "us-east-1"
    aws_profile: str | None = None
    sqs_queue_url: AnyHttpUrl | None = None
    lambda_function_url: AnyHttpUrl | None = None
    langfuse_host: AnyHttpUrl = "https://cloud.langfuse.com"
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None

    max_input_tokens_per_call: int = Field(default=48_000, gt=0)
    max_main_calls: int = Field(default=7, gt=0)
    max_input_tokens_per_run: int = Field(default=250_000, gt=0)
    max_output_tokens_per_run: int = Field(default=50_000, gt=0)
    max_cost_usd: float = Field(default=10.0, gt=0, allow_inf_nan=False)
    max_duration_seconds: float = Field(default=45 * 60, gt=0, allow_inf_nan=False)
    max_source_bytes: int = Field(default=5 * 1024 * 1024, gt=0)

    def context_budget(self) -> ContextBudget:
        return ContextBudget(
            max_input_tokens_per_call=self.max_input_tokens_per_call,
            max_main_calls=self.max_main_calls,
            max_input_tokens_per_run=self.max_input_tokens_per_run,
            max_output_tokens_per_run=self.max_output_tokens_per_run,
            max_cost_usd=self.max_cost_usd,
            max_duration_seconds=self.max_duration_seconds,
            max_source_bytes=self.max_source_bytes,
        )
