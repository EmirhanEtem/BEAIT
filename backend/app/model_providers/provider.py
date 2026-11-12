"""Model Provider Abstraction, Context Prompt Builder, and Privacy Controls (Phase 8 & Section 7).

Supports local and cloud model provider configurations while:
1. Redacting API keys from logs and serialized configurations.
2. Explicitly disclosing which project context fields are sent to the model provider.
3. Blocking automatic upload of local audio/sample/project binary files by default.
4. Providing a deterministic fallback intent/planning provider for offline and test execution.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


SECRET_PATTERNS = [
    re.compile(r"(sk-[a-zA-Z0-9_\-]{6,})"),
    re.compile(r"(AIza[a-zA-Z0-9_\-]{10,})"),
    re.compile(r"(Bearer\s+[a-zA-Z0-9_\-\.]{8,})", re.IGNORECASE),
]


def redact_secrets(text: str) -> str:
    """Redact API keys and bearer tokens from logs or error messages."""
    if not text:
        return text
    redacted = text
    for pat in SECRET_PATTERNS:
        redacted = pat.sub("[REDACTED_SECRET]", redacted)
    return redacted


@dataclass
class ProviderConfig:
    """Configuration for an LLM provider with built-in secret redaction."""
    provider_name: str = "deterministic_local"  # deterministic_local, ollama, openai, anthropic, gemini
    model_name: str = "fl-producer-rule-v1"
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    allow_cloud_context: bool = False
    allow_audio_upload: bool = False  # Never true by default per Section 7.6

    def to_safe_dict(self) -> Dict[str, Any]:
        """Serialize provider configuration without exposing raw API keys."""
        has_key = bool(self.api_key and len(self.api_key.strip()) > 0)
        masked_key = "[REDACTED_SECRET]" if has_key else None
        return {
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "base_url": self.base_url,
            "api_key_configured": has_key,
            "api_key_preview": masked_key,
            "allow_cloud_context": self.allow_cloud_context,
            "allow_audio_upload": self.allow_audio_upload,
        }


@dataclass
class PromptDisclosureEnvelope:
    """Transparently records what data is sent to a model provider (Section 7.7)."""
    provider_name: str
    model_name: str
    is_local: bool
    disclosed_fields: List[str] = field(default_factory=list)
    audio_or_project_files_attached: bool = False
    prompt_text: str = ""


class ModelProviderAdapter:
    """Builds context-aware prompts and enforces privacy/redaction rules."""

    def __init__(self, config: Optional[ProviderConfig] = None):
        self.config = config or ProviderConfig()

    @property
    def is_local_provider(self) -> bool:
        return self.config.provider_name.lower() in ("deterministic_local", "ollama", "local")

    def build_context_prompt(
        self,
        user_prompt: str,
        project_context: Optional[Dict[str, Any]] = None,
        user_preferences: Optional[Dict[str, Any]] = None,
    ) -> PromptDisclosureEnvelope:
        """Build a context-enriched prompt and disclose every field included."""
        ctx = project_context or {}
        prefs = user_preferences or {}
        disclosed: List[str] = ["user_prompt"]

        lines = [
            "=== FL STUDIO AI ASSISTANT PRODUCER PROMPT ===",
            f"User Request: {redact_secrets(user_prompt)}",
        ]

        if ctx:
            safe_ctx_summary = {}
            if "bpm" in ctx:
                safe_ctx_summary["bpm"] = ctx["bpm"]
                disclosed.append("project_context.bpm")
            if "playing" in ctx:
                safe_ctx_summary["playing"] = ctx["playing"]
                disclosed.append("project_context.playing")
            if "channel_count" in ctx:
                safe_ctx_summary["channel_count"] = ctx["channel_count"]
                disclosed.append("project_context.channel_count")
            if "channels" in ctx and isinstance(ctx["channels"], list):
                names = [
                    c.get("name", f"Ch_{i}") if isinstance(c, dict) else str(c)
                    for i, c in enumerate(ctx["channels"][:16])
                ]
                safe_ctx_summary["channel_names"] = names
                disclosed.append("project_context.channel_names")
            if "pattern_count" in ctx:
                safe_ctx_summary["pattern_count"] = ctx["pattern_count"]
                disclosed.append("project_context.pattern_count")
            lines.append(f"FL Studio Context: {safe_ctx_summary}")

        if prefs:
            disclosed.append("user_preferences")
            lines.append(f"User Preferences: {prefs}")

        return PromptDisclosureEnvelope(
            provider_name=self.config.provider_name,
            model_name=self.config.model_name,
            is_local=self.is_local_provider,
            disclosed_fields=disclosed,
            audio_or_project_files_attached=False,
            prompt_text="\n".join(lines),
        )

