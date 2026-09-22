"""Phase 6 — a local LLM front end that is not allowed to do arithmetic.

README section 13 draws the line: Python computes, the model talks. So the model
appears twice, on either side of the analytics engine, and never in the middle.

    question -> [parse] -> params -> recommend.py -> dict -> [narrate] -> answer

Two things here are defensive rather than decorative. The parser's output is
re-normalised in Python because the model returns things like "evening" where a
number was asked for. And every dollar figure in the generated answer is checked
against the source data before the user sees it: a model narrating earnings will
eventually invent one, and on a money-adjacent tool that has to be structurally
impossible rather than merely unlikely.
"""

import json
import re
import urllib.error
import urllib.request

from . import config as cfg
from . import recommend as R

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.1:8b"
TIMEOUT_SECONDS = 120

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# The model answers with words where a clock time was requested, so the mapping
# lives here rather than in the prompt where it would only be a suggestion.
TIME_WORDS = {
    "morning": 7.0, "breakfast": 7.0, "early": 7.0,
    "late morning": 10.0, "midday": 12.0, "noon": 12.0,
    "lunch": 12.0, "lunchtime": 12.0,
    "afternoon": 14.0, "arvo": 14.0,
    "evening": 17.0, "dinner": 18.0, "tonight": 17.0, "peak": 17.0,
    "night": 20.0, "late": 20.0,
}

INTENTS = {"plan_session", "rank_windows", "stay_advice", "out_of_scope"}

# The in/out-of-scope boundary is decided in Python, not by the model. It must
# refuse location and marketplace questions, and must NOT refuse ordinary timing
# questions -- llama3.1 classified "Is Friday lunch worth it?" as out of scope,
# which is the more damaging direction to get wrong.
OUT_OF_SCOPE_PATTERNS = re.compile(
    r"\b(where|which (area|suburb|part|spot|zone|place)|area|suburb|hotspot|"
    r"surge|demand|other drivers?|how many drivers|traffic|weather)\b", re.I
)

PARSE_PROMPT = """You convert a rideshare driver's question into JSON. Reply with JSON only.

Keys:
  intent: one of "plan_session", "rank_windows", "stay_advice", "out_of_scope"
  day: a weekday name, or "today", or null
  start_hour: 24-hour number like 17, or a word like "evening", or null
  hours: how many hours they have free, a number, or null

Use "plan_session" when they name a time or a block of hours.
Use "rank_windows" when they ask which day or time is best.
Use "stay_advice" when they ask how long to stay out.
Use "out_of_scope" when they ask WHERE to drive, about other drivers, surge,
demand, or anything outside their own past earnings by day and time.

Question: {question}"""

NARRATE_PROMPT = """You are a driving assistant. Answer the driver's question using ONLY the data below.

Hard rules:
- Every number you write must appear in the data. Never calculate, round or invent one.
- Quote dollar amounts exactly as given, digit for digit, including cents.
- Dollar figures are TOTALS for the whole session unless the field name says
  "per_hour". Never describe a total as an hourly rate.
- Mention the range, not just the single figure — these are estimates, not promises.
- 2-4 sentences, plain and direct. No preamble, no bullet points, no markdown.
- If the verdict is "not_enough_evidence", say plainly that there is no history
  for that time and give no dollar figure at all.

Question: {question}

Data:
{data}

Answer:"""

OUT_OF_SCOPE_ANSWER = (
    "I can't answer that one. This system only knows your own past earnings by day "
    "and time — it has no view of current demand, surge, other drivers, or which area "
    "to pick. Location specifically isn't answerable here: 27 of your 33 recorded "
    "sessions were in the same cell and 99% of your driving falls within 3 km of one "
    "point, so there's no second area to compare against. Ask me about timing instead."
)


class OllamaUnavailable(RuntimeError):
    """Raised when the local model cannot be reached, so callers can degrade."""


def _call(prompt: str, as_json: bool = False, model: str = MODEL) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0},
    }
    if as_json:
        payload["format"] = "json"

    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read()).get("response", "").strip()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OllamaUnavailable(f"Ollama not reachable at {OLLAMA_URL}: {exc}") from exc


def available() -> bool:
    try:
        _call("Reply with {}", as_json=True)
        return True
    except OllamaUnavailable:
        return False


def parse_question(question: str) -> dict:
    raw = _call(PARSE_PROMPT.format(question=question), as_json=True)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"intent": "out_of_scope", "_parse_error": raw[:200]}


def _coerce_hour(value) -> float | None:
    """Turn whatever the model produced into a clock hour, or give up."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) % 24
    text = str(value).strip().lower()

    match = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", text)
    if match:
        hour = int(match.group(1)) % 24
        minutes = int(match.group(2) or 0) / 60
        suffix = match.group(3)
        if suffix == "pm" and hour < 12:
            hour += 12
        elif suffix == "am" and hour == 12:
            hour = 0
        return hour + minutes

    for word, hour in TIME_WORDS.items():
        if word in text:
            return hour
    return None


def parse_without_model(question: str) -> dict:
    """Keyword parse used when Ollama is unreachable.

    The model is the interface, not the brain, so losing it should cost fluency
    and nothing else. Day names and time words are trivial to spot in Python,
    and every number still comes from the same engine either way.
    """
    text = question.lower()
    day = next((d for d in DAYS if d.lower() in text), None)
    if day is None and re.search(r"\b(today|tonight|now)\b", text):
        day = cfg.today_day_name()

    start = next((hour for word, hour in TIME_WORDS.items() if word in text), None)
    if start is None:
        clock = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text)
        start = _coerce_hour(clock.group(0)) if clock else None

    hours_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b", text)
    hours = float(hours_match.group(1)) if hours_match else None

    if re.search(r"\bhow long\b|\bstay\b", text):
        intent = "stay_advice"
    elif start is not None:
        intent = "plan_session"
    elif day or re.search(r"\bbest\b|\bwhen\b", text):
        intent = "rank_windows"
    else:
        intent = "out_of_scope"

    return {"intent": intent, "day": day, "start_hour": start, "hours": hours}


def normalise(parsed: dict, question: str = "") -> dict:
    """Repair the model's output into parameters the engine can actually take."""
    intent = parsed.get("intent")
    if intent not in INTENTS:
        intent = "out_of_scope"

    if question:
        if OUT_OF_SCOPE_PATTERNS.search(question):
            intent = "out_of_scope"
        elif intent == "out_of_scope":
            # The model refused a question with no out-of-scope subject in it,
            # so it is answerable: fall back on what it managed to extract.
            intent = "rank_windows" if parsed.get("day") else "stay_advice"
            if parsed.get("start_hour") is not None:
                intent = "plan_session"

    day = parsed.get("day")
    if isinstance(day, str):
        day = day.strip().title()
        if day in ("Today", "Tonight", "Now"):
            day = cfg.today_day_name()
        elif day not in DAYS:
            day = None

    hours = parsed.get("hours")
    try:
        hours = float(hours) if hours is not None else None
    except (TypeError, ValueError):
        hours = None
    if hours is not None:
        hours = max(0.5, min(hours, 12.0))

    start_hour = _coerce_hour(parsed.get("start_hour"))

    # "Monday morning" names a window, not a start time. Without snapping, a
    # default block starting at 07:00 spills into late morning and the answer
    # quotes a window the driver never asked about.
    if start_hour is not None and hours is None:
        window = R.window_for_hour(start_hour)
        for name, begin, _ in cfg.TIME_WINDOWS:
            if name == window:
                start_hour = float(begin)
                hours = R.window_span(name)
                break

    return {"intent": intent, "day": day, "start_hour": start_hour, "hours": hours}


def route(params: dict) -> dict:
    """Run the analytics engine. This is the only place numbers are produced."""
    intent = params["intent"]

    if intent == "plan_session":
        if params["day"] is None or params["start_hour"] is None:
            return {"needs_clarification": True,
                    "missing": [k for k in ("day", "start_hour") if params[k] is None]}
        return R.plan_session(params["day"], params["start_hour"], params["hours"] or 3.0)

    if intent == "rank_windows":
        return R.rank_windows(params["day"], top_n=5)

    if intent == "stay_advice":
        return R.stay_advice()

    return {"out_of_scope": True}


# Internals the driver has no use for, and which only give the model more
# numbers to misquote.
_HIDE = {"window_span_hours", "percentile_vs_all_windows", "coverage",
         "band_note", "evidence_sessions", "rankable", "status", "pro_rated"}

# Field names are the only units the model ever sees, so they carry them. With
# the original names it read a total range as an hourly rate.
_RENAME = {
    "expected_earnings": "expected_total_dollars",
    "band_80": "likely_total_range_dollars",
    "expected_per_available_hour": "dollars_per_available_hour",
    "hours_covered": "hours_in_this_window",
    "observations": "times_worked_before",
}


def trim(result):
    """Strip engine internals and make the remaining units self-describing."""
    if isinstance(result, dict):
        return {_RENAME.get(k, k): trim(v) for k, v in result.items() if k not in _HIDE}
    if isinstance(result, list):
        return [trim(v) for v in result]
    return result


_MONEY = re.compile(r"\$\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*dollars", re.I)


def _numbers_in(obj) -> set[float]:
    found = set()
    if isinstance(obj, dict):
        for value in obj.values():
            found |= _numbers_in(value)
    elif isinstance(obj, list):
        for value in obj:
            found |= _numbers_in(value)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        found.add(round(float(obj), 2))
    return found


def check_faithfulness(text: str, source: dict) -> tuple[bool, list[str]]:
    """Verify every dollar figure in the answer came from the data.

    Only money is policed. Counts and times get restated loosely in ordinary
    prose ("about 3 hours"), and flagging those would bury the one class of
    error that actually costs the driver something.
    """
    allowed = _numbers_in(source)
    offenders = []
    for match in _MONEY.finditer(text):
        value = float(match.group(1) or match.group(2))
        # Exact, or the same figure rounded to whole dollars. A loose window
        # here would wave through digit-level corruption -- the model has
        # already produced "$20.56" where the data said "$20.60", which is
        # wrong in exactly the way that matters and looks plausible.
        if not any(abs(value - ok) < 0.005 or value == round(ok) for ok in allowed):
            offenders.append(f"${value:g}")
    return (not offenders), offenders


def narrate(question: str, result: dict) -> str:
    data = json.dumps(trim(result), indent=2, default=str)
    return _call(NARRATE_PROMPT.format(question=question, data=data))


def answer(question: str, fallback_formatter=None) -> dict:
    """Full pipeline, with every failure path landing on real numbers."""
    degraded = None
    try:
        parsed = parse_question(question)
    except OllamaUnavailable as exc:
        parsed, degraded = parse_without_model(question), str(exc)

    params = normalise(parsed, question)
    result = route(params)

    if degraded:
        # Answer anyway, in plain figures. The engine never needed the model.
        if result.get("out_of_scope"):
            text = OUT_OF_SCOPE_ANSWER
        elif result.get("needs_clarification"):
            text = "I need a day and a time before I can answer that."
        else:
            text = fallback_formatter(result) if fallback_formatter else ""
        return {"question": question, "params": params, "result": result,
                "answer": text, "ok": False, "reason": degraded,
                "source": "no_model"}

    if result.get("out_of_scope"):
        return {"question": question, "params": params, "result": result,
                "answer": OUT_OF_SCOPE_ANSWER, "ok": True, "source": "canned"}

    if result.get("needs_clarification"):
        missing = " and ".join(result["missing"]).replace("start_hour", "what time")
        return {"question": question, "params": params, "result": result,
                "answer": f"I need to know {missing} before I can answer that.",
                "ok": True, "source": "canned"}

    try:
        text = narrate(question, result)
    except OllamaUnavailable as exc:
        text = fallback_formatter(result) if fallback_formatter else ""
        return {"question": question, "params": params, "result": result,
                "answer": text, "ok": False, "reason": str(exc), "source": "fallback"}

    faithful, offenders = check_faithfulness(text, result)
    if not faithful:
        # Fail closed. A wrong dollar figure is worse than a plain one.
        return {
            "question": question, "params": params, "result": result,
            "answer": fallback_formatter(result) if fallback_formatter else text,
            "ok": True, "source": "fallback_unfaithful",
            "rejected_answer": text, "invented_figures": offenders,
        }

    return {"question": question, "params": params, "result": result,
            "answer": text, "ok": True, "source": "llm"}
