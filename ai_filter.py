"""
AI 관련도 판단 (Claude API).

공고가 회사 비전과 관련 있는지 Claude 가 판단하고 한 줄 이유를 붙인다.
키가 없거나 호출이 실패하면 None 을 반환해, 호출부(crawler.run_crawl)가
기존 키워드 방식으로 무중단 폴백하도록 한다.

structured output(json_schema)으로 항상 유효한 JSON(relevant/score/reason)을 받는다.
"""

import json
import logging

import config

logger = logging.getLogger(__name__)

_client = None  # 지연 생성(키 없으면 만들지 않음)

# 판단 결과 스키마 — score 0~100(관련도), relevant(불리언), reason(한국어 한 줄)
_SCHEMA = {
    "type": "object",
    "properties": {
        "relevant": {"type": "boolean"},
        "score": {"type": "integer"},
        "reason": {"type": "string"},
    },
    "required": ["relevant", "score", "reason"],
    "additionalProperties": False,
}


def is_available():
    """AI 판단을 쓸 수 있는 상태인지(켜짐 + 키 존재)."""
    return bool(config.AI_ENABLED and config.ANTHROPIC_API_KEY)


def _get_client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def _build_system():
    return (
        config.COMPANY_VISION
        + "\n\n"
        "아래 공고가 이 회사와 관련 있는지 판단하라. 키워드 글자가 똑같지 않아도 "
        "소음·진동·음향·소음제어·주거환경·센서·신호처리·스마트홈·공동주택 분야와 "
        "실질적으로 맞닿아 있으면 관련으로 본다. "
        "score 는 0~100 의 관련도, relevant 는 score 가 50 이상이면 true, "
        "reason 은 왜 관련 있는지(또는 없는지)를 설명하는 한국어 한 줄이다. "
        "한국어 문장에 영어식 콜론을 쓰지 마라."
    )


def judge_relevance(title, body):
    """
    공고 1건의 관련도를 판단한다.
    반환: {"relevant": bool, "score": int, "reason": str,
           "usage": {"input": int, "output": int}}  또는 실패 시 None.
    """
    if not is_available():
        return None

    body = (body or "")[: config.AI_MAX_BODY_CHARS]
    user_text = f"제목\n{title}\n\n본문·사업명\n{body}"

    try:
        resp = _get_client().messages.create(
            model=config.AI_MODEL,
            max_tokens=300,
            system=_build_system(),
            messages=[{"role": "user", "content": user_text}],
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        )
        text = next((b.text for b in resp.content if b.type == "text"), "")
        data = json.loads(text)
        data["usage"] = {
            "input": resp.usage.input_tokens,
            "output": resp.usage.output_tokens,
        }
        return data
    except Exception as e:
        # 안전 실패 — 호출부가 키워드 결과를 유지하도록 None 반환
        logger.warning("AI 판단 실패(%s): %s", title[:30], e)
        return None


def estimate_cost_krw(input_tokens, output_tokens):
    """토큰 사용량을 대략적인 원화 비용으로 환산(추정)."""
    usd = (
        input_tokens / 1_000_000 * config.AI_PRICE_INPUT_PER_1M
        + output_tokens / 1_000_000 * config.AI_PRICE_OUTPUT_PER_1M
    )
    return usd * config.USD_TO_KRW
