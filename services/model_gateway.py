"""Optional public SDK transport; provider credentials stay in the host."""

from __future__ import annotations

import asyncio


class ModelGateway:
    def __init__(self, context, logger=lambda: None):
        self.context = context
        self.logger = logger
        self.status = {}

    def readiness(self, usage):
        models = getattr(self.context, "models", None)
        if not callable(getattr(models, "get_client", None)):
            return "no_model"
        return self.status.get(usage, "unverified")

    async def chat(self, usage, prompt, *, timeout_sec, max_completion_tokens, raise_timeout=False):
        try:
            async with asyncio.timeout(timeout_sec):
                client = await self.context.models.get_client()
                response = await client.chat.completions.create(
                    model=usage,
                    messages=[{"role": "user", "content": prompt}],
                    max_completion_tokens=max_completion_tokens,
                )
            content = response.choices[0].message.content
            self.status[usage] = ""
            return content if isinstance(content, str) and content.strip() else None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            unavailable = getattr(exc, "code", None) == "MODEL_GATEWAY_UNAVAILABLE"
            self.status[usage] = "no_model" if unavailable or status in (401, 403, 409) else "rejected"
            logger = self.logger()
            if logger is not None:
                logger.warning("plugin model gateway {} failed: {}", usage, type(exc).__name__)
            if raise_timeout and (isinstance(exc, TimeoutError) or type(exc).__name__ == "APITimeoutError"):
                raise TimeoutError() from None
            return None
