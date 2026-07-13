"""Single place where the app talks to an LLM.

Provider is Google Gemini (free tier). Everything else in the app is
provider-agnostic — swap this file to change models/providers.

Both callers (lesson-plan generation and syllabus ingestion) need the same
thing: a system instruction + a user prompt + a Pydantic schema the model must
fill. `structured()` returns a validated instance of that schema.

Credentials: set GEMINI_API_KEY (or GOOGLE_API_KEY). Get a free key at
https://aistudio.google.com/apikey
"""

from __future__ import annotations

import os
import re
import time

from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from pydantic import BaseModel

# Free-tier quotas on Gemini are per-model and small (some flash models cap new
# accounts at ~20 requests/day, or 0). gemini-flash-lite-latest is the most
# reliably-available free model at time of writing. For higher quality lesson
# plans on a paid/higher tier, override with LESSONPLAN_MODEL (e.g. a full flash
# or pro model).
MODEL = os.getenv("LESSONPLAN_MODEL", "gemini-flash-lite-latest")

# How long we're willing to sleep out a single rate-limit (per-minute quota).
# A per-DAY quota exhaustion reports a much larger delay; we don't wait that out
# — the error propagates so the batch can skip the subject and resume later.
_MAX_RETRY_SLEEP = 70


class QuotaExceeded(RuntimeError):
    """Daily/again-later quota hit and not worth waiting out in-process."""


def _retry_delay_seconds(err: Exception) -> float | None:
    m = re.search(r"retry(?:Delay)?[\"']?\s*[:=]\s*[\"']?(\d+(?:\.\d+)?)s", str(err))
    return float(m.group(1)) if m else None

_client: genai.Client | None = None


def has_credentials() -> bool:
    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        # Client picks up GEMINI_API_KEY / GOOGLE_API_KEY from the environment.
        _client = genai.Client()
    return _client


def structured(system: str, user: str, schema: type[BaseModel],
               *, max_retries: int = 4) -> BaseModel | None:
    """Call Gemini and return a validated `schema` instance (or None).

    Retries on transient rate-limit / server errors with backoff — handy for
    batch ingestion on the free tier's per-minute limits.
    """
    client = _get_client()
    config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_schema=schema,
        temperature=0.4,
    )
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = client.models.generate_content(
                model=MODEL, contents=user, config=config
            )
            parsed = resp.parsed
            if isinstance(parsed, schema):
                return parsed
            # Fall back to parsing the raw JSON text if .parsed is unset.
            if resp.text:
                return schema.model_validate_json(resp.text)
            return None
        except genai_errors.APIError as e:
            last_err = e
            status = getattr(e, "code", None) or getattr(e, "status_code", None)
            if status not in (429, 500, 503) or attempt >= max_retries - 1:
                raise
            wait = _retry_delay_seconds(e) or (2 ** attempt * 4)  # honour server hint
            if status == 429 and wait > _MAX_RETRY_SLEEP:
                # Per-day quota: don't block for minutes — let the caller skip.
                raise QuotaExceeded(str(e)) from e
            time.sleep(min(wait, _MAX_RETRY_SLEEP))
            continue
    if last_err:
        raise last_err
    return None
