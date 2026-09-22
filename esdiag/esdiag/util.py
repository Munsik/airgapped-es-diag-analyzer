"""단위 파싱/포매팅 유틸리티. 외부 의존성 없음."""

import re

_BYTE_UNITS = {
    "b": 1,
    "kb": 1024,
    "mb": 1024 ** 2,
    "gb": 1024 ** 3,
    "tb": 1024 ** 4,
    "pb": 1024 ** 5,
}

_TIME_UNITS = {
    "nanos": 1e-6,
    "ns": 1e-6,
    "micros": 1e-3,
    "us": 1e-3,
    "ms": 1.0,
    "s": 1000.0,
    "m": 60 * 1000.0,
    "h": 3600 * 1000.0,
    "d": 86400 * 1000.0,
}


def parse_bytes(value, default=None):
    """'1.5tb', '512mb', '1024', 1024 -> bytes(int). 실패 시 default."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip().lower().replace(",", "")
    if not s:
        return default
    m = re.match(r"^(-?[\d.]+)\s*([a-z]*)$", s)
    if not m:
        return default
    num, unit = m.group(1), m.group(2)
    try:
        num = float(num)
    except ValueError:
        return default
    if unit in ("", "bytes"):
        return int(num)
    if unit in _BYTE_UNITS:
        return int(num * _BYTE_UNITS[unit])
    return default


def parse_time_ms(value, default=None):
    """'30s', '1.5h', '250ms' -> milliseconds(float)."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().lower()
    m = re.match(r"^(-?[\d.]+)\s*([a-z]*)$", s)
    if not m:
        return default
    num, unit = m.group(1), m.group(2)
    try:
        num = float(num)
    except ValueError:
        return default
    if unit == "":
        return num
    if unit in _TIME_UNITS:
        return num * _TIME_UNITS[unit]
    return default


def fmt_bytes(num):
    """bytes -> 사람이 읽는 문자열."""
    if num is None:
        return "-"
    try:
        num = float(num)
    except (TypeError, ValueError):
        return "-"
    neg = num < 0
    num = abs(num)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if num < 1024 or unit == "PB":
            out = "%.1f%s" % (num, unit) if unit != "B" else "%dB" % num
            return ("-" + out) if neg else out
        num /= 1024.0
    return "-"


def fmt_ms(ms):
    """milliseconds -> 사람이 읽는 문자열."""
    if ms is None:
        return "-"
    try:
        ms = float(ms)
    except (TypeError, ValueError):
        return "-"
    if ms < 1000:
        return "%.0fms" % ms
    sec = ms / 1000.0
    if sec < 60:
        return "%.1fs" % sec
    minute = sec / 60.0
    if minute < 60:
        return "%.1fm" % minute
    hour = minute / 60.0
    if hour < 48:
        return "%.1fh" % hour
    return "%.1fd" % (hour / 24.0)


def fmt_num(n):
    if n is None:
        return "-"
    try:
        return "{:,}".format(int(n))
    except (TypeError, ValueError):
        return str(n)


def pct(part, whole):
    """백분율. whole이 0/None이면 None."""
    try:
        if not whole:
            return None
        return (float(part) / float(whole)) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def dig(obj, *path, **kw):
    """중첩 dict/list 안전 접근. dig(d, 'a', 'b', 0, default=None)"""
    default = kw.get("default")
    cur = obj
    for key in path:
        if cur is None:
            return default
        try:
            if isinstance(key, int) and isinstance(cur, (list, tuple)):
                cur = cur[key]
            elif isinstance(cur, dict):
                cur = cur.get(key)
            else:
                return default
        except (KeyError, IndexError, TypeError):
            return default
    return default if cur is None else cur


def num(obj, *path, **kw):
    """숫자 필드 접근자. 없거나 null·비숫자면 default(기본 0). 숫자 문자열("123", "1.5")은 숫자로 변환.

    버전·수집 조건에 따라 숫자가 문자열로 오거나 빠지는 경우에도 계산이 멈추지 않게 한다.
    """
    default = kw.get("default", 0)
    v = dig(obj, *path) if path else obj
    if isinstance(v, bool) or v is None:
        return default
    if isinstance(v, (int, float)):
        return v
    try:
        f = float(str(v).strip())
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return default


def items(x):
    """dict 의 (key, value) 목록. dict 가 아니면 빈 목록."""
    return list(x.items()) if isinstance(x, dict) else []


def strs(x):
    """문자열 원소만 남긴 리스트(패턴·이름 목록용)."""
    return [i for i in x if isinstance(i, str)] if isinstance(x, list) else []


def dicts(x):
    """dict 원소만 남긴 리스트(형식이 다른 원소는 버림)."""
    return [i for i in x if isinstance(i, dict)] if isinstance(x, list) else []


def parse_cat_table(text):
    """support-diagnostics의 cat_*.txt(공백 정렬 테이블)를 dict 리스트로 변환.

    첫 줄을 헤더로 보고, 헤더 컬럼의 시작 오프셋 기준으로 고정폭 분해를 시도한다.
    컬럼 수가 맞지 않으면 단순 split으로 폴백한다.
    """
    if not text:
        return []
    lines = [ln.rstrip("\n") for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return []
    header = lines[0]
    cols = []
    for m in re.finditer(r"\S+", header):
        cols.append((m.group(0), m.start()))
    rows = []
    for ln in lines[1:]:
        parts = ln.split()
        if len(parts) == len(cols):
            rows.append(dict(zip([c[0] for c in cols], parts)))
        else:
            # 값에 공백이 포함된 경우: 헤더 오프셋 기준 슬라이스
            rec = {}
            for i, (name, start) in enumerate(cols):
                end = cols[i + 1][1] if i + 1 < len(cols) else len(ln)
                rec[name] = ln[start:end].strip() if start < len(ln) else ""
            rows.append(rec)
    return rows


def truncate(s, n=160):
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def top_n(items, key, n=10, reverse=True):
    try:
        return sorted(items, key=key, reverse=reverse)[:n]
    except TypeError:
        return list(items)[:n]
