"""Local memory policy. Original diary text is never rewritten by this module."""

from __future__ import annotations

import math
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from .state import _DIARY_MAX_ENTRIES, _now_utc, _parse_iso_ts

MEMORY_TYPES = frozenset({"preference", "temporary", "event", "boundary"})
MEMORY_ACTIONS = frozenset({
    "pin", "unpin", "pause", "resume", "confirm", "correct", "archive", "unarchive", "classify", "expire", "undo",
})
DAY = 86400


class MemoryPolicyError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def metadata(item: dict) -> dict:
    value = item.get("memory")
    return value if isinstance(value, dict) else {}


def _policy_snapshot(item: dict) -> dict:
    meta = deepcopy(metadata(item))
    meta.pop("undo", None)
    meta.pop("history", None)
    return meta


def count(value: Any, default: int = 1) -> int:
    return min(10000, max(1, value)) if type(value) is int else default


def memory_text(item: dict) -> str:
    return str(metadata(item).get("correction") or item.get("quote") or "")


def _time(now: datetime | None) -> datetime:
    return (now or _now_utc()).astimezone(timezone.utc)


def memory_state(item: dict, now: datetime | None = None) -> str:
    status = str(item.get("status") or "active")
    if status != "active":
        return status
    meta = metadata(item)
    if meta.get("schema", 1) != 1:
        return "pending"
    if meta.get("paused") is True:
        return "paused"
    if meta.get("pending") is True:
        return "pending"
    current = _time(now)
    expires = _parse_iso_ts(meta.get("valid_until"))
    if expires and current >= expires:
        return "expired"
    if not meta or meta.get("pinned") is True or meta.get("type") == "boundary":
        return "active"
    if meta.get("type") == "temporary" and not expires:
        return "pending"
    confirmed = _parse_iso_ts(meta.get("last_confirmed_at"))
    # Legacy records have no aging baseline. Reading them must not start a clock.
    if not confirmed:
        return "active"
    days = max(0, (current - confirmed).total_seconds() / DAY)
    horizon = (180 if meta.get("type") == "preference" else 90) * min(4, count(meta.get("confirmations")))
    return "dormant" if days >= horizon else "active"


def lifecycle_view(item: dict, now: datetime | None = None) -> dict:
    view = dict(item)
    if item.get("source") == "auto":
        view["memory_state"] = memory_state(item, now)
        view["memory"] = deepcopy(metadata(item))
    return view


def diary_partition(diary: list[dict], scope: str = "") -> list[dict]:
    """Capacity archives history without deleting it or changing fact validity."""
    if scope == "all":
        return list(diary)
    candidates = [(index, item) for index, item in enumerate(diary) if not metadata(item).get("archived")]
    candidates.sort(key=lambda pair: (str(metadata(pair[1]).get("return_to_recent") or ""), pair[0]), reverse=True)
    recent = {id(item) for _, item in candidates[:_DIARY_MAX_ENTRIES]}
    return [item for item in diary if (id(item) not in recent) == (scope == "archive")]


def relevance(query: str, item: dict) -> float:
    needle = query.strip().casefold()
    if not needle:
        return 0.0
    body = f"{memory_text(item)} {item.get('quote') or ''} {item.get('note') or ''}".casefold()
    if needle in body:
        return 1.0
    words = re.findall(r"[a-z0-9]+|[\u3400-\u9fff]{2,}", needle)
    tokens = set()
    for word in words:
        if re.search(r"[\u3400-\u9fff]", word):
            tokens.update(word[index:index + 2] for index in range(len(word) - 1))
        else:
            tokens.add(word)
    return sum(token in body for token in tokens) / max(1, len(tokens))


def memory_priority(item: dict, now: datetime | None = None) -> float:
    meta = metadata(item)
    if not meta:
        return 0.0
    confirmed = _parse_iso_ts(meta.get("last_confirmed_at"))
    days = max(0, (_time(now) - confirmed).total_seconds() / DAY) if confirmed else 0.0
    return (
        (4 if meta.get("pinned") else 0)
        + (2 if meta.get("type") == "boundary" else 0)
        + min(2, math.log2(count(meta.get("confirmations"))))
        + 1 / (1 + days / 90)
    )


def recall_memories(
    diary: list[dict], kind: str = "", query: str = "", limit: int = 10, *, now: datetime | None = None,
) -> list[dict]:
    try:
        cap = max(1, min(30, int(limit)))
    except (ValueError, TypeError, OverflowError):
        cap = 10
    hits = []
    for position, item in enumerate(diary):
        state = memory_state(item, now)
        if item.get("source") != "auto" or state not in ({"active", "dormant"} if query.strip() else {"active"}):
            continue
        if kind and item.get("kind") != kind:
            continue
        match = relevance(query, item)
        # Query lookup is deliberately conservative; fuzzy matching is for
        # selecting extraction candidates, not returning unrelated user facts.
        body = f"{memory_text(item)} {item.get('quote') or ''} {item.get('note') or ''}".casefold()
        if query.strip() and query.strip().casefold() not in body:
            continue
        hits.append((match, memory_priority(item, now), position, item))
    hits.sort(key=lambda hit: hit[:3], reverse=True)
    return [item for *_, item in hits[:cap]]


def extraction_candidates(diary: list[dict], user_text: str, limit: int = 10) -> list[dict]:
    eligible = [(index, item) for index, item in enumerate(diary)
                if item.get("source") == "auto" and memory_state(item) in {"active", "dormant", "expired"}]
    ranked = sorted(eligible, key=lambda pair: (relevance(user_text, pair[1]), pair[0]), reverse=True)
    selected = {index for index, _ in ranked[:max(1, limit - 3)]}
    selected.update(index for index, _ in eligible[-3:])
    # Keep the prompt's numbered list in chronological order, newest first.
    return [deepcopy(item) for index, item in reversed(eligible) if index in selected][:limit]


def new_metadata(parsed: dict, stamp: str, *, user_text: str = "", local_now: datetime | None = None) -> dict:
    kind = parsed.get("kind")
    requested = parsed.get("memory_type")
    memory_type = requested if requested in MEMORY_TYPES else (
        "boundary" if kind in {"dislike", "overstep"} else "preference" if kind == "like" else "event"
    )
    # A model cannot quietly make a recorded boundary or hurtful event expire.
    if kind == "overstep" or kind == "dislike" and requested != "temporary":
        memory_type = "boundary"
    meta = {
        "schema": 1, "type": memory_type, "confirmations": 1,
        "last_confirmed_at": stamp, "updated_at": stamp,
        "evidence": [{"ts": stamp, "quote": str(parsed.get("quote") or "")[:60]}],
    }
    condition = str(parsed.get("condition") or "").strip()[:120]
    if condition and condition in user_text:
        meta["condition"] = condition
    if memory_type == "temporary":
        current = local_now or _parse_iso_ts(stamp) or datetime.now(timezone.utc)
        day = str(parsed.get("valid_until") or "")[:10]
        # Only accept an expiry grounded in an explicit source date or a
        # same-day expression. Otherwise require user confirmation.
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) and day in user_text:
            try:
                end = datetime.fromisoformat(day).replace(tzinfo=current.tzinfo) + timedelta(days=1)
                meta["valid_until"] = end.isoformat(timespec="seconds")
                meta["valid_through"] = day
            except (ValueError, OverflowError):
                meta["pending"] = True
        elif re.search(r"今天|今晚|今日|\btoday\b|\btonight\b", user_text, re.IGNORECASE):
            end = current.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            meta["valid_until"] = end.isoformat(timespec="seconds")
            meta["valid_through"] = current.date().isoformat()
        else:
            meta["pending"] = True
    return meta


def reinforce(item: dict, parsed: dict, stamp: str) -> bool:
    meta = deepcopy(metadata(item))
    now = _parse_iso_ts(stamp)
    previous = _parse_iso_ts(meta.get("last_confirmed_at") or item.get("ts"))
    if not now or previous and (now - previous).total_seconds() < DAY:
        return False
    if not meta:
        meta = new_metadata({**parsed, "kind": item.get("kind")}, stamp)
        meta["evidence"] = [{"ts": str(item.get("ts") or ""), "quote": str(item.get("quote") or "")[:60]}]
    meta.pop("undo", None)
    meta["confirmations"] = min(10000, count(meta.get("confirmations")) + 1)
    meta["last_confirmed_at"] = stamp
    meta["updated_at"] = stamp
    evidence = list(meta.get("evidence") or [])
    evidence.append({"ts": stamp, "quote": str(parsed.get("quote") or "")[:60]})
    meta["evidence"] = evidence[-8:]
    item["memory"] = meta
    return True


def apply_capture(diary: list[dict], existing: list[dict], parsed: dict, record: dict) -> str:
    """Mutate only a still-matching target. Returns new/reinforced/duplicate."""
    relation = parsed.get("relation")
    if any(item.get("source") == "auto" and item.get("quote") == parsed.get("quote")
           and metadata(item).get("paused") for item in diary):
        return "duplicate"
    target = parsed.get("target", 0)
    expected = existing[target - 1] if type(target) is int and 1 <= target <= len(existing) else None
    if relation == "duplicate" and expected is None:
        expected = next((item for item in existing if item.get("quote") == parsed.get("quote")), None)
    current = next((item for item in diary if expected and item == expected), None)
    if relation == "duplicate" and current and memory_state(current) in {"paused", "pending", "superseded"}:
        return "duplicate"
    if relation == "duplicate":
        if current and metadata(current).get("condition", "") != metadata(record).get("condition", ""):
            diary.append(record)
            return "new"
        if current and metadata(current).get("correction"):
            return "duplicate"
        if current and memory_state(current) not in {"paused", "pending", "superseded"}:
            changed = reinforce(current, parsed, record["ts"])
            renew = metadata(current).get("type") == "temporary" and bool(metadata(record).get("valid_until"))
            if renew:
                current["memory"] = deepcopy(metadata(current))
                current["memory"].pop("undo", None)
                current["memory"]["updated_at"] = record["ts"]
                for key in ("valid_until", "valid_through", "pending"):
                    current["memory"].pop(key, None)
                    if key in metadata(record):
                        current["memory"][key] = record["memory"][key]
            return "reinforced" if changed or renew else "duplicate"
        # Preserve old-model duplicate replies without guessing a target.
        return "duplicate"
    if relation in {"supersede", "conflict"} and current:
        old_condition = str(metadata(current).get("condition") or "")
        new_condition = str(metadata(record).get("condition") or "")
        if old_condition == new_condition and not metadata(record).get("pending"):
            if metadata(current).get("correction"):
                record["memory"]["pending"] = True
                record["memory"]["conflicts_with"] = str(current.get("ts") or "")
            elif relation == "supersede":
                if metadata(record).get("type") != "temporary" or metadata(current).get("type") == "temporary":
                    current["status"] = "superseded"
                    current["memory"] = {**metadata(current), "updated_at": record["ts"]}
                    current["memory"].pop("undo", None)
                    record["supersedes"] = current.get("ts")
            else:
                record["memory"]["pending"] = True
                record["memory"]["conflicts_with"] = str(current.get("ts") or "")
                current["memory"] = {**metadata(current), "pending": True,
                                     "conflicts_with": record["ts"], "updated_at": record["ts"]}
                current["memory"].pop("undo", None)
    diary.append(record)
    return "new"


def _related_memories(diary: list[dict], item: dict) -> list[dict]:
    edges: dict[str, set[str]] = {}
    for entry in diary:
        stamp = str(entry.get("ts") or "")
        for link in (entry.get("supersedes"), metadata(entry).get("conflicts_with")):
            if stamp and link:
                edges.setdefault(stamp, set()).add(str(link))
                edges.setdefault(str(link), set()).add(stamp)
    connected = {str(item.get("ts") or "")}
    pending = list(connected)
    while pending:
        stamp = pending.pop()
        for linked in edges.get(stamp, set()) - connected:
            connected.add(linked)
            pending.append(linked)
    related = [other for other in diary if other is not item and str(other.get("ts") or "") in connected]
    stamps = [str(other.get("ts") or "") for other in related]
    if len(set(stamps)) != len(stamps) or any(metadata(other).get("schema", 1) != 1 for other in related):
        raise MemoryPolicyError("memory_action_invalid")
    if len(related) > 10000:
        raise MemoryPolicyError("memory_capacity_reached")
    return related


def manage_memory(diary: list[dict], item: dict, action: str, *, text: str = "", now: datetime | None = None) -> None:
    if action not in MEMORY_ACTIONS:
        raise MemoryPolicyError("memory_action_invalid")
    if item.get("source") != "auto" and action not in {"archive", "unarchive", "undo"}:
        raise MemoryPolicyError("memory_action_invalid")
    if not isinstance(text, str):
        raise MemoryPolicyError("memory_text_invalid")
    stamp = _time(now).isoformat()
    previous = _policy_snapshot(item)
    snapshot = {"memory": previous, "had_memory": "memory" in item,
                "status": str(item.get("status") or ""), "had_status": "status" in item}
    meta = deepcopy(metadata(item))
    if meta.get("schema", 1) != 1:
        raise MemoryPolicyError("memory_action_invalid")
    # Organizing a legacy record must not retroactively start its aging clock.
    meta.setdefault("schema", 1)
    meta.setdefault("type", new_metadata(item, str(item.get("ts") or stamp))["type"])
    meta.setdefault("confirmations", 1)
    if action == "undo":
        undo = list(meta.get("undo") or [])
        if not undo:
            raise MemoryPolicyError("memory_action_invalid")
        saved = undo[-1]
        for related in saved.get("related", []):
            matches = [other for other in diary if other.get("ts") == related["ts"]]
            if len(matches) != 1 or metadata(matches[0]).get("updated_at") != related["changed_at"]:
                raise MemoryPolicyError("memory_action_invalid")
        for related in saved.get("related", []):
            other = next(other for other in diary if other.get("ts") == related["ts"])
            if related["had_memory"]:
                audit = {key: value for key, value in metadata(other).items() if key in {"history", "undo"}}
                other["memory"] = {**deepcopy(related["memory"]), **audit, "updated_at": stamp}
            else:
                other["memory"] = {"updated_at": stamp}
        if saved["had_status"]:
            item["status"] = saved["status"]
        else:
            item.pop("status", None)
        restored = deepcopy(saved["memory"])
        restored["undo"] = undo[:-1]
        restored["history"] = [*(meta.get("history") or []), {"ts": stamp, "action": "undo"}][-20:]
        if not saved["had_memory"] and not restored["undo"]:
            # Retain only the audit trail, without creating an aging baseline.
            restored = {"history": restored["history"]}
        item["memory"] = {**restored, "updated_at": stamp}
        return
    if action in {"pin", "unpin"}:
        meta["pinned"] = action == "pin"
    elif action in {"pause", "resume"}:
        meta["paused"] = action == "pause"
    elif action in {"archive", "unarchive"}:
        meta["archived"] = action == "archive"
        if action == "unarchive":
            meta["return_to_recent"] = stamp
    elif action == "classify":
        if text not in MEMORY_TYPES:
            raise MemoryPolicyError("memory_action_invalid")
        meta["type"] = text
        meta["pending"] = bool(meta.get("pending") and meta.get("conflicts_with")) or (
            text == "temporary" and not meta.get("valid_until")
        )
        if text != "temporary":
            meta.pop("valid_until", None)
            meta.pop("valid_through", None)
    elif action == "expire":
        try:
            local_now = now or _now_utc()
            end = datetime.fromisoformat(text).replace(tzinfo=local_now.tzinfo) + timedelta(days=1)
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) or end <= local_now:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            raise MemoryPolicyError("memory_date_invalid") from None
        meta.update({"type": "temporary", "valid_until": end.isoformat(timespec="seconds"),
                     "valid_through": text, "pending": bool(meta.get("pending") and meta.get("conflicts_with"))})
    else:
        if action == "correct":
            correction = text.strip()
            if not correction or len(correction) > 500:
                raise MemoryPolicyError("memory_text_invalid")
            meta["correction"] = correction
        # Explicit confirmation is the only way to revive expired/updated facts.
        # Mark their replacements pending rather than presenting both as current.
        for other in _related_memories(diary, item):
            snapshot.setdefault("related", []).append({
                "ts": str(other.get("ts") or ""), "memory": _policy_snapshot(other),
                "had_memory": "memory" in other, "changed_at": stamp,
            })
            other["memory"] = {**metadata(other), "pending": True, "updated_at": stamp}
            other["memory"].pop("undo", None)
        item["status"] = "active"
        meta.update({"pending": False, "paused": False, "last_confirmed_at": stamp,
                     "confirmations": min(10000, count(meta.get("confirmations")) + 1)})
        meta.pop("valid_until", None)
        meta.pop("valid_through", None)
        if meta.get("type") == "temporary":
            meta["type"] = "event"
        meta["pinned"] = True
        meta.pop("suggestion", None)
    meta["updated_at"] = stamp
    history = list(meta.get("history") or [])
    history.append({"ts": stamp, "action": action})
    meta["history"] = history[-20:]
    meta["undo"] = [*(meta.get("undo") or []), snapshot][-10:]
    item["memory"] = meta
