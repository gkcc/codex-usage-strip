"""Honest presentation of the read-only Codex rate-limit response."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Any

CHINA = timezone(timedelta(hours=8), "Asia/Shanghai")


def number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def epoch(value: Any) -> float | None:
    value = number(value)
    if value is None or value <= 0:
        return None
    try:
        datetime.fromtimestamp(value, CHINA)
    except (ValueError, OverflowError, OSError):
        return None
    return value


def stamp(value: float | None, full: bool = False) -> str:
    if value is None:
        return "时间未知"
    return datetime.fromtimestamp(value, CHINA).strftime(
        "%Y-%m-%d %H:%M:%S" if full else "%m/%d %H:%M"
    )


def countdown(value: float | None, now: float) -> str:
    if value is None:
        return "时间未知"
    seconds = max(0, math.ceil(value - now))
    if seconds == 0:
        return "到点待刷新"
    minutes = math.ceil(seconds / 60)
    days, remainder = divmod(minutes, 1440)
    hours, minutes = divmod(remainder, 60)
    if days:
        return f"{days}天{hours}小时"
    if hours:
        return f"{hours}小时{minutes}分"
    return f"{minutes}分钟"


@dataclass(frozen=True)
class Window:
    name: str
    short_name: str
    remaining: float | None
    resets_at: float | None
    duration_minutes: float | None

    @property
    def percent(self) -> str:
        if self.remaining is None:
            return "未知"
        return f"{self.remaining:g}%"


@dataclass(frozen=True)
class Quota:
    windows: tuple[Window, ...]
    bank_count: int | None
    bank_expiry: float | None
    bank_expiry_exact: bool
    detail_count: int
    plan: str | None
    fetched_at: float

    @classmethod
    def parse(cls, result: dict, now: float) -> "Quota":
        buckets = result.get("rateLimitsByLimitId")
        bucket = buckets.get("codex") if isinstance(buckets, dict) else None
        legacy = result.get("rateLimits")
        if not isinstance(bucket, dict) and isinstance(legacy, dict):
            if legacy.get("limitId") in (None, "codex"):
                bucket = legacy
        # An unrelated model bucket is not the user's general Codex allowance.
        bucket = bucket if isinstance(bucket, dict) else {}
        windows = []
        for key in ("primary", "secondary"):
            data = bucket.get(key)
            if not isinstance(data, dict):
                continue
            used = number(data.get("usedPercent"))
            remaining = None if used is None or used < 0 else max(0.0, 100 - used)
            duration = number(data.get("windowDurationMins"))
            if duration is not None and duration <= 0:
                duration = None
            if duration == 10080:
                name, short = "本周", "周"
            elif duration == 300:
                name, short = "5小时", "5h"
            elif duration == 1440:
                name, short = "每日", "日"
            elif duration is not None:
                name = short = f"{duration:g}分钟"
            else:
                name = short = "额度"
            windows.append(Window(name, short, remaining, epoch(data.get("resetsAt")), duration))
        bank = result.get("rateLimitResetCredits")
        count, expiry, exact, detail_count = None, None, False, 0
        if isinstance(bank, dict):
            raw_count = number(bank.get("availableCount"))
            if raw_count is not None and raw_count >= 0 and raw_count.is_integer():
                count = int(raw_count)
            details = bank.get("credits")
            if isinstance(details, list):
                available = [
                    row for row in details
                    if isinstance(row, dict) and row.get("status") == "available"
                ]
                detail_count = len(available)
                known = [epoch(row.get("expiresAt")) for row in available]
                dates = [value for value in known if value is not None]
                if dates:
                    expiry = min(dates)
                # A capped, unknown-date or duplicate list cannot establish the
                # earliest expiry of the whole bank. IDs stay in memory only.
                ids = [row.get("id") for row in available]
                unique_ids = all(isinstance(i, str) and i for i in ids) and len(set(ids)) == len(ids)
                exact = (
                    count is not None and count > 0 and len(available) == count
                    and len(dates) == count and unique_ids
                )
            if count == 0:
                expiry, exact = None, True
        plan = bucket.get("planType")
        return cls(tuple(windows), count, expiry, exact, detail_count,
                   plan if isinstance(plan, str) else None, now)

    def text(self, now: float, compact: int = 0, failed: bool = False) -> str:
        if compact == 3:
            # At the real desktop minimum width, split each label from its
            # timestamp. Keep the exact dates rather than ellipsizing them.
            rows = []
            for window in self.windows:
                rows += [f"{window.short_name}{window.percent}重置", stamp(window.resets_at)]
            if not rows:
                rows.append("额度未知")
            count = "?" if self.bank_count is None else str(self.bank_count)
            label = f"银行{count}次"
            if self.bank_count != 0:
                if self.bank_expiry is not None and not self.bank_expiry_exact:
                    label += "已知"
                rows += [label + "到期", stamp(self.bank_expiry)]
            else:
                rows.append(label)
            if failed or now - self.fetched_at > 180:
                rows[0] = "旧·" + rows[0]
            return "\n".join(rows)
        parts = []
        for window in self.windows:
            name = window.name if compact == 0 else window.short_name
            percent = window.percent
            label = "剩余 " if compact == 0 else ""
            part = f"{name}{label}{percent}  {stamp(window.resets_at)}重置"
            if compact == 0 and window.resets_at is not None:
                part += f"（{countdown(window.resets_at, now)}）"
            parts.append(part)
        if not parts:
            parts.append("额度待获取")
        bank = "银行 " if compact == 0 else "银行"
        bank += "次数未知" if self.bank_count is None else f"{self.bank_count}次"
        if self.bank_count != 0:
            if self.bank_expiry is None:
                bank += " · 到期时间未知"
            else:
                known = "最早" if self.bank_expiry_exact else "已知最早"
                if compact == 2:
                    known = "" if self.bank_expiry_exact else "已知"
                bank += f" · {known}{stamp(self.bank_expiry)}到期"
                if compact == 0:
                    bank += f"（{countdown(self.bank_expiry, now)}）"
        parts.append(bank)
        stale = failed or now - self.fetched_at > 180
        separator = "\n" if compact == 2 else "  |  "
        return ("旧数据 · " if stale else "") + separator.join(parts)

    def detail(self, now: float, failed: bool = False) -> str:
        lines = ["Codex 用量 · 北京时间（UTC+8）"]
        for window in self.windows:
            lines += [
                f"{window.name}剩余：{window.percent}",
                f"下次重置：{stamp(window.resets_at, full=True)}（{countdown(window.resets_at, now)}）",
            ]
        if not self.windows:
            lines.append("服务未返回通用额度窗口。")
        lines.append("重置银行：" + ("次数未知" if self.bank_count is None else f"{self.bank_count}次"))
        if self.bank_count == 0:
            lines.append("没有可用的储存重置。")
        elif self.bank_expiry is None:
            lines.append("最早到期：未知（服务未提供完整到期信息）")
        else:
            prefix = "最早到期" if self.bank_expiry_exact else "已知最早到期（明细不完整）"
            lines.append(f"{prefix}：{stamp(self.bank_expiry, full=True)}")
            lines.append(f"距离到期：{countdown(self.bank_expiry, now)}")
        lines.append(f"最后成功更新：{stamp(self.fetched_at, full=True)}")
        if failed or now - self.fetched_at > 180:
            lines.append("当前显示上次成功获取的数据；正在重试。")
        lines += ["每60秒读取官方用量；到点后会再次读取。", "拖动此条可移动 Codex；右键可刷新或退出。"]
        return "\n".join(lines)

    def due(self, now: float) -> bool:
        deadlines = [w.resets_at for w in self.windows] + [self.bank_expiry]
        return any(value is not None and self.fetched_at < value <= now for value in deadlines)

    def evidence(self) -> dict:
        return {
            "windows": [dict(name=w.name, remaining_percent=w.remaining,
                             resets_at=w.resets_at, duration_minutes=w.duration_minutes)
                        for w in self.windows],
            "bank_count": self.bank_count,
            "bank_earliest_expiry": self.bank_expiry,
            "bank_earliest_expiry_exact": self.bank_expiry_exact,
            "bank_detail_count": self.detail_count,
            "fetched_at": self.fetched_at,
            "timezone": "Asia/Shanghai",
        }
