"""
AI 관련도 판단 (Claude API).

공고가 회사 비전과 관련 있는지 Claude 가 판단하고 한 줄 이유를 붙인다.
키가 없거나 호출이 실패하면 None 을 반환해, 호출부(crawler.run_crawl)가
기존 키워드 방식으로 무중단 폴백하도록 한다.

structured output(json_schema)으로 항상 유효한 JSON(relevant/score/reason)을 받는다.
"""

import json
import logging
import re

import config

logger = logging.getLogger(__name__)

_client = None  # 지연 생성(키 없으면 만들지 않음)


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
        "한국어 문장에 영어식 콜론을 쓰지 마라.\n"
        "반드시 JSON 한 개만 출력하라. 다른 설명이나 코드블록 표시(```)는 쓰지 마라.\n"
        '형식: {"relevant": true 또는 false, "score": 0~100 정수 관련도, '
        '"reason": "왜 관련 있는지/없는지 한국어 한 줄"}'
    )


def _parse_json(text):
    """모델 응답에서 첫 JSON 객체를 추출해 파싱. 실패 시 None."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)  # 코드블록·앞뒤 텍스트가 섞여도 추출
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def judge_relevance(title, body):
    """
    공고 1건의 관련도를 판단한다.
    반환: {"relevant": bool, "score": int, "reason": str,
           "usage": {"input": int, "output": int}}  또는 실패 시 None.

    structured output 미지원 구버전 SDK에서도 동작하도록 JSON 프롬프트 + 파싱 방식 사용.
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
        )
        text = "".join(
            b.text for b in resp.content if getattr(b, "type", "") == "text"
        )
        data = _parse_json(text)
        if data is None:
            logger.warning("AI 응답 JSON 파싱 실패(%s): %s", title[:30], text[:80])
            return None
        return {
            "relevant": bool(data.get("relevant")),
            "score": int(data.get("score") or 0),
            "reason": str(data.get("reason") or ""),
            "usage": {
                "input": resp.usage.input_tokens,
                "output": resp.usage.output_tokens,
            },
        }
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
