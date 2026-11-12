"""Settings and configuration schemas."""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class AppSettings(BaseModel):
    llm_provider: str = "openai"  # openai, anthropic, local
    openai_model: str = "gpt-4o"
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_model: str = "claude-sonnet-4-20250514"
    local_model_url: str = "http://localhost:11434"
    local_model_name: str = "llama3"
    
    fl_mcp_host: str = "127.0.0.1"
    fl_mcp_port: int = 9787
    
    hcu_enabled: bool = True
    
    sample_directories: List[str] = Field(default_factory=list)
    language: str = "tr"  # tr, en
    auto_verify: bool = True
    safe_mode: bool = True

