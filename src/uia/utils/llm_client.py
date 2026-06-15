"""Client for interfacing with Groq's chat completion API.

Provides LLMClient to call Groq completions for extracting structured JSON
data from unstructured raw web pages using defined schemas.
"""
import json
import logging
import os
from typing import Any, Dict, Optional
from dotenv import load_dotenv

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class LlmResponseError(Exception):
    """Raised when the Groq LLM API returns a non-200 retriable status code."""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"Groq API returned status {status_code}: {message}")


class LLMClient:
    """A resilient wrapper for Groq LLM API calls.

    Resilience Strategies:
    1. Retry Mechanisms: Retries on network issues or rate limiting (429) /
       server errors (5xx) with exponential backoff using tenacity.
    2. Context Safety: Truncates inputs to fit safely in model context windows.
    3. Output Correction: Cleans and parses LLM outputs (e.g. stripping markdown fences)
       to ensure valid JSON dictionary parsing.
    4. Graceful Degradation: Returns empty dictionary on parsing/retrying failures
       instead of halting execution.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ):
        """Initializes the LLMClient.

        Args:
            api_key: Optional Groq API key (defaults to GROQ_API_KEY environment variable).
            model: Optional Groq model ID (defaults to GROQ_MODEL environment variable).
            client: Optional httpx.AsyncClient to use for requests.
        """
        load_dotenv()
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")
        self.model = model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.client = client or httpx.AsyncClient(timeout=30.0)

    def _log_retry(self, retry_state):
        """Logs retry attempts with exception details."""
        exc = retry_state.outcome.exception()
        attempt = retry_state.attempt_number
        logger.warning(f"Groq API call retry attempt #{attempt} due to: {repr(exc)}")

    async def _post_with_retry(self, payload: Dict[str, Any]) -> httpx.Response:
        """Sends the payload to Groq's completions endpoint using a retry policy."""
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        def should_retry(exception: Exception) -> bool:
            if isinstance(exception, httpx.TransportError):
                return True
            if isinstance(exception, LlmResponseError):
                # Retry on rate limiting (429) or server errors (5xx)
                return exception.status_code == 429 or (500 <= exception.status_code < 600)
            return False

        retrier = AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=5),
            retry=retry_if_exception(should_retry),
            before_sleep=self._log_retry,
            reraise=True,
        )

        async for attempt in retrier:
            with attempt:
                response = await self.client.post(url, headers=headers, json=payload)
                if response.status_code != 200:
                    raise LlmResponseError(response.status_code, response.text)
                return response

        raise RuntimeError("Retries failed to raise or return a response.")

    def _parse_json_content(self, content: str) -> Dict[str, Any]:
        """Parses the LLM string response into a dictionary.

        Attempts to load the raw string as JSON. If it fails, attempts to strip
        markdown formatting code blocks (```json ... ```) and parses again.
        Returns an empty dict if all attempts fail.
        """
        clean_content = content.strip()
        try:
            return json.loads(clean_content)
        except json.JSONDecodeError:
            # Fallback: attempt to strip code blocks
            if clean_content.startswith("```"):
                lines = clean_content.splitlines()
                # Remove starting code block line
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]
                # Remove ending code block line
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                inner_content = "\n".join(lines).strip()
                try:
                    return json.loads(inner_content)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed parsing code block contents: {e}")
                    return {}
            logger.warning("Failed parsing raw LLM response as JSON.")
            return {}

    async def extract_structured(
        self,
        page_text: str,
        target_schema_description: str,
        field_name: str,
        source_url: str,
    ) -> Dict[str, Any]:
        """Sends page content to Groq completions to extract structured fields.

        Args:
            page_text: Raw page html or text contents.
            target_schema_description: Metadata/schema string representation of target structure.
            field_name: Name of target data field (e.g. 'tuition_fees').
            source_url: The source URL where raw text was compiled.

        Returns:
            A parsed dictionary mapping the target schema structures, or empty dict if extraction fails.
        """
        # Truncate text to avoid model context overflows, high latency, and rate-limiting issues
        max_chars = 12000
        if len(page_text) > max_chars:
            page_text = page_text[:max_chars] + "\n...[TRUNCATED]..."

        system_prompt = (
            "You are a precise data-extraction engine for university intelligence.\n"
            "Your task is to extract structured details from the provided text and return them in a strict JSON format.\n"
            "Guidelines:\n"
            "1. Only extract values that are explicitly present in the provided text. Never extrapolate or assume.\n"
            f"2. Return strict JSON matching the following schema description:\n{target_schema_description}\n"
            "3. If a field is not present in the text, return an empty object or list, or omit it, depending on the schema.\n"
            "4. NEVER fabricate or invent dates, numbers, or names if they are not in the source text.\n"
            "5. Ensure the final response is valid JSON and nothing else."
        )

        user_prompt = (
            f"Target Field: {field_name}\n"
            f"Source URL: {source_url}\n"
            f"Source Text:\n{page_text}"
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }

        try:
            response = await self._post_with_retry(payload)
            response_json = response.json()
            content = response_json["choices"][0]["message"]["content"]
            return self._parse_json_content(content)
        except Exception as e:
            logger.error(f"Structured extraction terminal failure for field '{field_name}': {e}")
            return {}

    async def close(self):
        """Closes the underlying httpx.AsyncClient."""
        await self.client.aclose()


# ==============================================================================
# StubLLMClient — used when GROQ_API_KEY is not set in the environment.
#
# To switch to real Groq extraction:
#   1. Copy .env.example to .env
#   2. Set GROQ_API_KEY=<your_key> inside .env
#   3. Re-run `uia run` (without --stub) — main.py will auto-detect the key
#      and instantiate the real LLMClient instead of this stub.
# ==============================================================================


class StubLLMClient:
    """A no-op drop-in replacement for LLMClient used when no API key is available.

    Returns an empty dict for every extraction call. The orchestrator treats an
    empty-dict response as "nothing found" and falls back to typed defaults from
    _get_default_for_type(), so all 10 top-level UniversityRecord fields are still
    present in the output (just unpopulated). The validator then flags each empty
    field as severity="medium" / confidence=0.3, which is correct behaviour and
    not a bug — it signals that the extraction stage was skipped, not that the
    agent failed structurally.
    """

    async def extract_structured(
        self,
        page_text: str,
        target_schema_description: str,
        field_name: str,
        source_url: str,
    ) -> Dict[str, Any]:
        """Immediately returns an empty dict — no API call is made."""
        logger.info(
            f"[StubLLMClient] Skipping LLM extraction for field '{field_name}' "
            "(GROQ_API_KEY not set — using stub mode)."
        )
        return {}

    async def close(self) -> None:
        """No-op cleanup (stub holds no connections)."""
        pass
