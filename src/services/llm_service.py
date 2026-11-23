"""LLM Service orchestrating multi-provider fallback and structured JSON generation.

Supports:
- Primary: Gemini (Google AI Studio)
- Fallback 1: Groq
- Fallback 2: DeepSeek

Features:
- Pure aiohttp REST client without heavyweight SDKs.
- Automatic provider fallback on errors, timeouts, or invalid JSON.
- Exponential backoff for HTTP 429 rate limits.
- Payload size bounding and chunking to guard against HTTP 413.
"""

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

# Ensure local venv site-packages is on sys.path if running with base python
_venv_site = Path(__file__).resolve().parent.parent.parent / "venv" / "Lib" / "site-packages"
if _venv_site.exists() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

import aiohttp

from src.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_API_URL,
    DEEPSEEK_MODEL,
    GEMINI_API_BASE_URL,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GROQ_API_KEY,
    GROQ_API_URL,
    GROQ_MODEL,
    LLM_MAX_RETRIES,
    LLM_TIMEOUT_SECONDS,
    MAX_PAYLOAD_CHARS,
)
from src.utils.logger import get_logger

logger = get_logger("llm_service")


def clean_json_markdown(text: str) -> str:
    """Extract raw JSON string from markdown code fences or conversational wrappers."""
    cleaned = text.strip()
    # Strip markdown code fences ```json ... ``` or ``` ... ```
    if "```" in cleaned:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
        if match:
            cleaned = match.group(1).strip()

    # Sometimes LLMs append text before the opening bracket { or after }
    start_idx = cleaned.find("{")
    end_idx = cleaned.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        cleaned = cleaned[start_idx : end_idx + 1]

    return cleaned


def bound_payload(text: str, max_chars: int = MAX_PAYLOAD_CHARS) -> str:
    """Safely limit input payload size to prevent HTTP 413 (Payload Too Large)."""
    if len(text) <= max_chars:
        return text
    logger.warning("Payload size %d exceeds max %d chars. Truncating input.", len(text), max_chars)
    return text[:max_chars] + "\n\n[Warning: Input truncated due to size limits]"


class LLMService:
    """Unified asynchronous LLM client with provider fallback chain."""

    def __init__(
        self,
        gemini_key: str = GEMINI_API_KEY,
        groq_key: str = GROQ_API_KEY,
        deepseek_key: str = DEEPSEEK_API_KEY,
    ):
        self.gemini_key = gemini_key.strip()
        self.groq_key = groq_key.strip()
        self.deepseek_key = deepseek_key.strip()

        # Chain order: Gemini (Primary) -> Groq (Fallback 1) -> DeepSeek (Fallback 2)
        self.providers = ["gemini", "groq", "deepseek"]

    def has_configured_provider(self) -> bool:
        """Return True if at least one provider has an API key configured."""
        return bool(self.gemini_key or self.groq_key or self.deepseek_key)

    async def _call_gemini(
        self,
        session: aiohttp.ClientSession,
        prompt: str,
        system_instruction: Optional[str] = None,
    ) -> Tuple[int, Optional[str]]:
        """Call Gemini REST API endpoint."""
        if not self.gemini_key:
            return 401, "Gemini API key is not configured"

        url = f"{GEMINI_API_BASE_URL}/{GEMINI_MODEL}:generateContent?key={self.gemini_key}"
        headers = {"Content-Type": "application/json"}

        body: Dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.1,
            },
        }
        if system_instruction:
            body["system_instruction"] = {
                "parts": [{"text": system_instruction}]
            }

        async with session.post(
            url,
            json=body,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=LLM_TIMEOUT_SECONDS),
        ) as resp:
            status = resp.status
            if status == 200:
                data = await resp.json()
                try:
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                    return 200, text
                except (KeyError, IndexError) as err:
                    return 500, f"Malformed Gemini response: {err}"
            else:
                err_text = await resp.text()
                return status, err_text

    async def _call_groq(
        self,
        session: aiohttp.ClientSession,
        prompt: str,
        system_instruction: Optional[str] = None,
    ) -> Tuple[int, Optional[str]]:
        """Call Groq chat completion REST endpoint."""
        if not self.groq_key:
            return 401, "Groq API key is not configured"

        headers = {
            "Authorization": f"Bearer {self.groq_key}",
            "Content-Type": "application/json",
        }

        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        body = {
            "model": GROQ_MODEL,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }

        async with session.post(
            GROQ_API_URL,
            json=body,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=LLM_TIMEOUT_SECONDS),
        ) as resp:
            status = resp.status
            if status == 200:
                data = await resp.json()
                try:
                    text = data["choices"][0]["message"]["content"]
                    return 200, text
                except (KeyError, IndexError) as err:
                    return 500, f"Malformed Groq response: {err}"
            else:
                err_text = await resp.text()
                return status, err_text

    async def _call_deepseek(
        self,
        session: aiohttp.ClientSession,
        prompt: str,
        system_instruction: Optional[str] = None,
    ) -> Tuple[int, Optional[str]]:
        """Call DeepSeek chat completion REST endpoint."""
        if not self.deepseek_key:
            return 401, "DeepSeek API key is not configured"

        headers = {
            "Authorization": f"Bearer {self.deepseek_key}",
            "Content-Type": "application/json",
        }

        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        body = {
            "model": DEEPSEEK_MODEL,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }

        async with session.post(
            DEEPSEEK_API_URL,
            json=body,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=LLM_TIMEOUT_SECONDS),
        ) as resp:
            status = resp.status
            if status == 200:
                data = await resp.json()
                try:
                    text = data["choices"][0]["message"]["content"]
                    return 200, text
                except (KeyError, IndexError) as err:
                    return 500, f"Malformed DeepSeek response: {err}"
            else:
                err_text = await resp.text()
                return status, err_text

    async def generate_json(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        session: Optional[aiohttp.ClientSession] = None,
        max_retries: int = LLM_MAX_RETRIES,
    ) -> Tuple[Dict[str, Any], str, int]:
        """Execute JSON generation across the provider fallback chain.

        Returns:
            (parsed_json, winning_provider_name, fallback_attempts_count)

        Raises:
            RuntimeError: if all providers fail or are unconfigured.
        """
        bounded_prompt = bound_payload(prompt)

        # Ensure active session
        close_session = False
        if session is None:
            session = aiohttp.ClientSession()
            close_session = True

        fallback_attempts = 0

        try:
            for provider_idx, provider in enumerate(self.providers):
                logger.info("Attempting extraction with provider: %s (attempt %d)", provider.upper(), fallback_attempts)

                # Skip provider if API key is missing
                if provider == "gemini" and not self.gemini_key:
                    logger.debug("Gemini skipped: No API key configured.")
                    fallback_attempts += 1
                    continue
                elif provider == "groq" and not self.groq_key:
                    logger.debug("Groq skipped: No API key configured.")
                    fallback_attempts += 1
                    continue
                elif provider == "deepseek" and not self.deepseek_key:
                    logger.debug("DeepSeek skipped: No API key configured.")
                    fallback_attempts += 1
                    continue

                # Provider execution loop with exponential backoff for HTTP 429
                for attempt in range(max_retries + 1):
                    try:
                        if provider == "gemini":
                            status, raw_response = await self._call_gemini(session, bounded_prompt, system_instruction)
                        elif provider == "groq":
                            status, raw_response = await self._call_groq(session, bounded_prompt, system_instruction)
                        elif provider == "deepseek":
                            status, raw_response = await self._call_deepseek(session, bounded_prompt, system_instruction)
                        else:
                            status, raw_response = 500, "Unknown provider"

                        # Handle 200 OK
                        if status == 200 and raw_response:
                            clean_json = clean_json_markdown(raw_response)
                            try:
                                parsed = json.loads(clean_json)
                                if isinstance(parsed, dict):
                                    logger.info("Extraction succeeded with %s after %d fallback(s).", provider.upper(), fallback_attempts)
                                    return parsed, provider, fallback_attempts
                                else:
                                    logger.warning("Provider %s returned non-dict JSON. Retrying fallback.", provider)
                                    break
                            except json.JSONDecodeError as json_err:
                                logger.warning("Provider %s returned invalid JSON: %s. Output was: %s", provider, json_err, raw_response[:100])
                                break  # Move to next provider

                        # Handle 429 Rate Limit with exponential backoff
                        elif status == 429:
                            if attempt < max_retries:
                                wait_seconds = (2 ** attempt) * 2.0
                                logger.warning("Provider %s HTTP 429 (Rate Limit). Retrying in %.1fs (attempt %d/%d)...", provider, wait_seconds, attempt + 1, max_retries)
                                await asyncio.sleep(wait_seconds)
                                continue
                            else:
                                logger.warning("Provider %s exceeded maximum 429 retries. Falling back to next provider.", provider)
                                break

                        # Handle 413 Payload Too Large
                        elif status == 413:
                            logger.warning("Provider %s HTTP 413 (Payload Too Large). Further truncating input.", provider)
                            bounded_prompt = bound_payload(bounded_prompt, max_chars=4000)
                            if attempt < 1:
                                continue
                            break

                        # Other HTTP errors (4xx, 5xx)
                        else:
                            logger.warning("Provider %s failed with HTTP %d: %s", provider, status, (raw_response or "")[:150])
                            break

                    except asyncio.TimeoutError:
                        logger.warning("Provider %s timed out on attempt %d/%d.", provider, attempt + 1, max_retries + 1)
                        if attempt == max_retries:
                            break
                    except Exception as exc:
                        logger.warning("Provider %s encountered request error: %s", provider, exc)
                        break

                fallback_attempts += 1

            # If loop completed without returning, all providers failed
            raise RuntimeError(
                f"All configured LLM providers failed or no valid API keys were set. (Fallback attempts: {fallback_attempts})"
            )
        finally:
            if close_session:
                await session.close()
