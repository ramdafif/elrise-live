import math
import re
from datetime import date, datetime, timedelta, timezone

JAKARTA = timezone(timedelta(hours=7), "Asia/Jakarta")


class ValidationError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def now():
    return datetime.now(JAKARTA).replace(tzinfo=None)


def text(data, key, label, maximum=120, required=True):
    value = str(data.get(key, "")).strip()
    if (required and not value) or len(value) > maximum or "\x00" in value:
        raise ValidationError(f"{label} wajib diisi dan maksimal {maximum} karakter.")
    return value


def email(data, key="email"):
    value = text(data, key, "Email", 190).lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ValidationError("Format email tidak valid.")
    return value


def password(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 128:
        raise ValidationError("Password harus berisi 12-128 karakter.")
    return value


def integer(data, key, minimum, maximum, default=None):
    try:
        value = int(data.get(key, default))
    except (ValueError, TypeError, OverflowError):
        raise ValidationError(f"{key} harus berupa angka bulat.") from None
    if not minimum <= value <= maximum:
        raise ValidationError(f"{key} harus antara {minimum} dan {maximum}.")
    return value


def number(data, key, minimum, maximum):
    try:
        raw = data.get(key)
        if isinstance(raw, bool):
            raise ValueError
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        raise ValidationError(f"{key} harus berupa angka valid.") from None
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValidationError(f"{key} harus antara {minimum} dan {maximum}.")
    return value


def day(data, key):
    try:
        return date.fromisoformat(str(data.get(key, "")))
    except ValueError:
        raise ValidationError(f"Tanggal {key} tidak valid.") from None


def time_value(data, key):
    try:
        return datetime.strptime(str(data.get(key, "")), "%H:%M").time()
    except ValueError:
        raise ValidationError(f"Jam {key} harus HH:MM.") from None


def sql_time(value):
    if isinstance(value, timedelta):
        return (datetime.min + value).time()
    return value


def pagination():
    from flask import request

    page = integer(request.args, "page", 1, 100000, 1)
    return page, 20, (page - 1) * 20


def date_range(args, maximum=93):
    today = now().date()
    start = day(args, "start") if args.get("start") else today.replace(day=1)
    end = day(args, "end") if args.get("end") else today
    if end < start or (end - start).days >= maximum or end > today:
        raise ValidationError(f"Rentang laporan maksimal {maximum} hari, sampai hari ini.")
    return start, end
