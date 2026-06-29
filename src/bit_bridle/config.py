"""Environment-based configuration for the GLM endpoint.

GLM-5.2 is reached through an OpenAI-compatible /chat/completions interface.
Point ``GLM_BASE_URL`` at whichever host serves it:

  - Zhipu (mainland):     https://open.bigmodel.cn/api/paas/v4
  - z.ai (international):  https://api.z.ai/api/paas/v4
  - self-hosted vLLM:     http://localhost:8000/v1
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_MODEL = "glm-5.2"


@dataclass(frozen=True)
class Config:
    api_key: str
    base_url: str
    model: str
    temperature: float
    max_tool_iterations: int

    @classmethod
    def from_env(cls) -> "Config":
        api_key = os.environ.get("GLM_API_KEY", "").strip()
        if not api_key:
            raise SystemExit(
                "GLM_API_KEY is not set. Export it (or put it in a .env file) "
                "before running bit-bridle. See .env.example."
            )
        return cls(
            api_key=api_key,
            base_url=os.environ.get("GLM_BASE_URL", DEFAULT_BASE_URL).strip(),
            model=os.environ.get("GLM_MODEL", DEFAULT_MODEL).strip(),
            temperature=float(os.environ.get("GLM_TEMPERATURE", "0.3")),
            max_tool_iterations=int(os.environ.get("GLM_MAX_TOOL_ITERATIONS", "25")),
        )
