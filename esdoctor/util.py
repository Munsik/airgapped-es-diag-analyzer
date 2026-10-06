"""Unit parsing and formatting helpers. No external dependencies."""

import re

_BYTE_UNITS = {
    "b": 1,
    "k": 1024,            # ES ByteSizeValue also accepts the single-letter units
    "m": 1024 ** 2,
    "g": 1024 ** 3,
    "t": 1024 ** 4,
    "p": 1024 ** 5,
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
    """'1.5tb', '512mb', '1024', 1024 -> bytes (int). Returns default on failure."""
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
    """bytes -> human-readable string."""
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
    """milliseconds -> human-readable string."""
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
    """Percentage. Returns None if whole is 0 or None."""
    try:
        if not whole:
            return None
        return (float(part) / float(whole)) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def dig(obj, *path, **kw):
    """Safe access into nested dict/list. dig(d, 'a', 'b', 0, default=None)"""
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
    """Numeric field accessor. Returns default (0 unless given) if missing, null or non-numeric. Numeric strings ("123", "1.5") are converted.

    Depending on version and collection mode a number may arrive as a string or be absent; this keeps the calculation going.
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
    """(key, value) list of a dict. Empty list if not a dict."""
    return list(x.items()) if isinstance(x, dict) else []


def strs(x):
    """List with only the string elements (for pattern and name lists)."""
    return [i for i in x if isinstance(i, str)] if isinstance(x, list) else []


def dicts(x):
    """List with only the dict elements (elements of another type are dropped)."""
    return [i for i in x if isinstance(i, dict)] if isinstance(x, list) else []


# Network and shared filesystem types (nodes_stats fs.data[].type), used by PERF-009 and FRZ-002
NET_FS = ("nfs", "cifs", "smb", "fuse", "glusterfs", "ceph", "lustre", "gpfs", "beegfs", "9p")
NET_FS_LOCAL = ("fuseblk", "fuse.fuse-overlayfs")     # FUSE types that are local, not network


def is_network_fs(fstype):
    t = str(fstype or "").lower()
    return bool(t) and t not in NET_FS_LOCAL and any(x in t for x in NET_FS)


IP_REJECTION_KEYS = ("coordinating_rejections", "primary_rejections", "replica_rejections")


def ip_rejections(node_stats):
    """Indexing pressure rejections of a node: coordinating + primary + replica (IndexingPressure). primary_document_rejections
    counts the documents of the same rejections, and large_operation_rejections is counted before the check that may still allow
    the operation (a real large-operation rejection also counts as a primary rejection), so neither is added. -1 (an older node in
    a mixed cluster) counts as 0."""
    tot = dig(node_stats, "indexing_pressure", "memory", "total") or {}
    return sum(max(0.0, num(tot, k)) for k in IP_REJECTION_KEYS)


def parse_cat_table(text):
    """Converts support-diagnostics cat_*.txt (whitespace-aligned table) into a list of dicts.

    Treats the first line as the header and splits each row on whitespace. When a row has more parts than columns and every
    extra part starts in the last column, the surplus belongs to that column; otherwise (spaces in an earlier column, or empty
    cells) the row is cut at the header column start offsets.
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
        elif len(parts) > len(cols) and len(cols) > 1 and \
                len([m for m in re.finditer(r"\S+", ln) if m.start() < cols[-1][1]]) == len(cols) - 1:
            # only the last column holds spaces (a relocating shard: "node -> ip id target"): the surplus joins it. Numeric
            # columns are right-aligned, so cutting at header offsets would split them.
            rows.append(dict(zip([c[0] for c in cols], parts[:len(cols) - 1] + [" ".join(parts[len(cols) - 1:])])))
        else:
            # value contains spaces: slice by header offsets
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


def dwidth(text):
    """Display width in a terminal: East Asian wide and full-width characters take two columns."""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in str(text))


def dljust(text, width):
    """ljust by display width."""
    text = str(text)
    return text + " " * max(0, width - dwidth(text))
