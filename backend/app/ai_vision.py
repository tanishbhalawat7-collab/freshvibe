"""Optional AI product recognition with a vision model.

AI output is *evidence*, never verified truth: the pipeline caps its confidence
and cross-checks every AI-read date against the OCR text. When no provider is
configured the step reports "not configured" -- it is never simulated."""
from __future__ import annotations

import base64
import json
import re

import cv2
import httpx
import numpy as np

from .config import config
from .lookup import CATEGORIES

PROMPT = f"""You are reading a photo of a retail product package (food, medicine or household item).
Report ONLY what is visible. Never guess a date that you cannot read.

Return a single JSON object, no prose, with exactly these keys:
{{
  "product_name": string|null,        // product name as printed, e.g. "Amul Taaza Toned Milk"
  "brand": string|null,
  "category": one of {json.dumps(CATEGORIES)} or null,
  "visible_text": string,             // the important printed text you can read, lines separated by \\n
  "dates": [                          // every date printed on the pack
    {{"label": string|null,           // the label printed next to it, e.g. "EXP", "MFD", "BEST BEFORE"
      "kind": "expiry"|"mfg"|"packed"|"other",
      "as_printed": string,           // exactly as printed, e.g. "05/2027"
      "normalized": string|null,      // "YYYY-MM-DD", or "YYYY-MM" if only month+year are printed
      "confidence": number}}          // 0..1 how sure you are of the reading
  ],
  "batch_no": string|null,
  "confidence": {{"product_name": number, "brand": number, "category": number}},
  "image_problems": string|null       // e.g. "date is blurred", "glare over text"
}}
Dates on Indian/European packs are day-first (DD/MM/YYYY)."""


class AIUnavailable(RuntimeError):
    pass


def provider() -> str | None:
    p = config.AI_PROVIDER
    if p == "anthropic" and config.ANTHROPIC_API_KEY:
        return "anthropic"
    if p == "openai" and config.OPENAI_API_KEY:
        return "openai"
    return None


def status() -> dict:
    p = provider()
    if p:
        return {"configured": True, "provider": p,
                "model": config.ANTHROPIC_MODEL if p == "anthropic" else config.OPENAI_MODEL}
    reason = ("AI_PROVIDER is not set" if not config.AI_PROVIDER else
              f"AI_PROVIDER={config.AI_PROVIDER} but its API key is missing")
    return {"configured": False, "provider": None, "reason": reason}


def _jpeg_b64(bgr: np.ndarray) -> str:
    h, w = bgr.shape[:2]
    scale = min(1.0, 1568 / max(h, w))
    if scale < 1:
        bgr = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return base64.b64encode(buf.tobytes()).decode()


def _parse_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise AIUnavailable("AI response did not contain JSON.")
    data = json.loads(m.group(0))
    if not isinstance(data, dict):
        raise AIUnavailable("AI response JSON is not an object.")
    return data


def _clean(d: dict) -> dict:
    def num(x, default=0.0):
        try:
            return max(0.0, min(1.0, float(x)))
        except (TypeError, ValueError):
            return default

    conf = d.get("confidence") or {}
    cat = d.get("category")
    dates = []
    for item in d.get("dates") or []:
        if not isinstance(item, dict):
            continue
        norm = item.get("normalized")
        if norm and not re.fullmatch(r"20\d{2}-\d{2}(-\d{2})?", str(norm)):
            norm = None
        dates.append({"label": item.get("label"), "kind": item.get("kind") if item.get("kind") in
                      ("expiry", "mfg", "packed", "other") else "other",
                      "as_printed": str(item.get("as_printed") or ""), "normalized": norm,
                      "confidence": num(item.get("confidence"))})
    return {
        "product_name": (d.get("product_name") or None),
        "brand": (d.get("brand") or None),
        "category": cat if cat in CATEGORIES else None,
        "visible_text": str(d.get("visible_text") or ""),
        "dates": dates,
        "batch_no": d.get("batch_no") or None,
        "confidence": {k: num(conf.get(k)) for k in ("product_name", "brand", "category")},
        "image_problems": d.get("image_problems") or None,
    }


async def analyze(bgr: np.ndarray) -> dict:
    p = provider()
    if not p:
        raise AIUnavailable(status()["reason"])
    img = _jpeg_b64(bgr)
    timeout = httpx.Timeout(config.AI_TIMEOUT_S, connect=10)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if p == "anthropic":
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                             "content-type": "application/json"},
                    json={"model": config.ANTHROPIC_MODEL, "max_tokens": 1200,
                          "messages": [{"role": "user", "content": [
                              {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img}},
                              {"type": "text", "text": PROMPT}]}]})
                if r.status_code != 200:
                    raise AIUnavailable(f"Anthropic API HTTP {r.status_code}: {r.text[:200]}")
                text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
            else:
                r = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                    json={"model": config.OPENAI_MODEL, "response_format": {"type": "json_object"},
                          "messages": [{"role": "user", "content": [
                              {"type": "text", "text": PROMPT},
                              {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}}]}]})
                if r.status_code != 200:
                    raise AIUnavailable(f"OpenAI API HTTP {r.status_code}: {r.text[:200]}")
                text = r.json()["choices"][0]["message"]["content"]
    except httpx.HTTPError as exc:
        raise AIUnavailable(f"AI request failed: {exc.__class__.__name__}") from exc
    try:
        return {"provider": p, **_clean(_parse_json(text))}
    except (ValueError, json.JSONDecodeError) as exc:
        raise AIUnavailable(f"Could not parse AI response: {exc}") from exc
