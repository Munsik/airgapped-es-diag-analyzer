"""Diagnostics bundle loader.

A support-diagnostics output has one of these forms:
  - diagnostic-xxxx.zip                     (still compressed)
  - .../api-diagnostics-YYYYMMDD-HHMMSS/    (extracted directory)
  - local / remote mode: the above plus a logs/ directory (elasticsearch.log, gc.log, etc.)

A zip is read directly in memory, not extracted to temp files (air-gapped and read-only environments).
"""

import json
import os
import zipfile
from .i18n import T



def _is_error_body(obj):
    """An Elasticsearch error response: {"error": ..., "status": <int>} and nothing else."""
    return (isinstance(obj, dict) and "error" in obj and isinstance(obj.get("status"), int)
            and set(obj) <= {"error", "status"})

class Bundle(object):
    def __init__(self, path):
        self.path = path
        self._zip = None
        self._names = []        # relative paths inside the bundle
        self._cache = {}
        self._root = ""
        if os.path.isdir(path):
            self._load_dir(path)
        elif zipfile.is_zipfile(path):
            self._load_zip(path)
        else:
            raise ValueError(T("loader.Bundle.__init__.01") % path)
        self._index = {}
        for n in self._names:
            self._index.setdefault(os.path.basename(n).lower(), []).append(n)

    #     # ---------------- loading ----------------
    def _load_dir(self, path):
        self._mode = "dir"
        self._base = path
        for dirpath, _dirnames, filenames in os.walk(path):
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, path).replace("\\", "/")
                self._names.append(rel)

    def _load_zip(self, path):
        self._mode = "zip"
        self._zip = zipfile.ZipFile(path, "r")
        for info in self._zip.infolist():
            if info.is_dir():
                continue
            self._names.append(info.filename.replace("\\", "/"))

    #     # ---------------- raw access ----------------
    def names(self):
        return list(self._names)

    def _read_raw(self, rel):
        if self._mode == "zip":
            with self._zip.open(rel) as fh:
                return fh.read()
        with open(os.path.join(self._base, rel), "rb") as fh:
            return fh.read()

    def resolve(self, name):
        """Finds the real path for 'nodes_stats.json' or 'commercial/ilm_explain.json'."""
        name = name.replace("\\", "/")
        base = os.path.basename(name).lower()
        cands = self._index.get(base, [])
        if not cands:
            return None
        if "/" in name:
            suffix = name.lower()
            for c in cands:
                if c.lower().endswith(suffix):
                    return c
        # prefer paths closest to the top level (directly under the root)
        cands = sorted(cands, key=lambda c: (c.count("/"), len(c)))
        return cands[0]

    def exists(self, name):
        return self.resolve(name) is not None

    def text(self, name, errors="replace"):
        rel = self.resolve(name)
        if rel is None:
            return None
        if rel in self._cache:
            return self._cache[rel]
        try:
            data = self._read_raw(rel).decode("utf-8", errors)
        except Exception:
            return None
        self._cache[rel] = data
        return data

    def json(self, name, default=None, cache=True):
        """Parses JSON. The raw text is not cached (saves memory on large bundles).

        With cache=False the result is not cached either: for large files (cluster_state, mapping) that are summarized and dropped.
        """
        key = "json:" + name
        if key in self._cache:
            return self._cache[key]
        rel = self.resolve(name)
        if rel is None:
            return default
        try:
            raw = self._read_raw(rel)
        except Exception:
            return default
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        if not raw.strip():
            return default
        try:
            obj = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            rows = []
            for ln in raw.decode("utf-8", "replace").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rows.append(json.loads(ln))
                except ValueError:
                    return default
            obj = rows if rows else default
        del raw
        if _is_error_body(obj):
            # the diagnostics tool saves a failed API call's error response under the same file name: treat it as missing
            obj = default
        if cache:
            self._cache[key] = obj
        return obj

    def _text_nocache(self, name):
        rel = self.resolve(name)
        if rel is None:
            return None
        try:
            raw = self._read_raw(rel)
        except Exception:
            return None
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        return raw.decode("utf-8", "replace")

    def iter_object(self, name):
        """Parses a large file whose top level is a JSON object one (key, value) at a time and yields them.

        The whole file is not parsed at once, so peak memory is about the raw text plus one item (mapping.json etc.).
        Falls back to a full parse if the format is not as expected.
        """
        text = self._text_nocache(name)
        if not text:
            return
        dec = json.JSONDecoder()
        ws = " \t\r\n"
        i = 0
        n = len(text)
        while i < n and text[i] in ws:
            i += 1
        if i >= n or text[i] != "{":
            obj = self.json(name, cache=False)
            for kv in (obj.items() if isinstance(obj, dict) else []):
                yield kv
            return
        i += 1
        try:
            while True:
                while i < n and text[i] in ws + ",":
                    i += 1
                if i >= n or text[i] == "}":
                    return
                key, i = dec.raw_decode(text, i)
                while i < n and text[i] in ws:
                    i += 1
                i += 1                                  # ':'
                while i < n and text[i] in ws:
                    i += 1
                val, i = dec.raw_decode(text, i)
                yield key, val
        except ValueError:
            return

    def extract_array(self, name, anchor, key):
        """Cuts out and parses only the first "key": [...] array after anchor in a large file (for small pieces of cluster_state).

        Returns None if not found. Meant to avoid a full parse; the key position is limited by anchor.
        """
        text = self._text_nocache(name)
        if not text:
            return None
        a = text.find('"%s"' % anchor)
        if a < 0:
            return None
        k = text.find('"%s"' % key, a)
        if k < 0:
            return None
        b = text.find("[", k)
        if b < 0:
            return None
        try:
            val, _end = json.JSONDecoder().raw_decode(text, b)
            return val
        except ValueError:
            return None

    def find_all(self, predicate):
        """List of paths satisfying predicate(relpath)->bool."""
        return [n for n in self._names if predicate(n)]

    def close(self):
        if self._zip is not None:
            try:
                self._zip.close()
            except Exception:
                pass

    #     # ---------------- logs ----------------
    def log_files(self):
        """Paths of server log files collected in local/remote mode."""
        out = []
        for n in self._names:
            low = n.lower()
            if "docker-logs" in low and low.endswith(".txt"):
                out.append(n)       # docker targets: support-diagnostics writes the container logs to docker/docker-logs*.txt
            elif "/logs/" in low or low.startswith("logs/"):
                if low.endswith((".log", ".json", ".json.gz")) or ".log." in low:
                    out.append(n)
        return out

    def read_log(self, rel, max_bytes=8 * 1024 * 1024):
        """For a big log, reads only the tail (most recent part)."""
        try:
            data = self._read_raw(rel)
        except Exception:
            return ""
        if rel.lower().endswith(".gz"):
            # rolled-over log (.log.gz, .json.gz). Decompress in chunks and keep only the last max_bytes, so the result is the
            # most recent part. Decompression stops after 512MB (or 64 x max_bytes if larger) to bound the work on a
            # decompression bomb; ES rolls its logs at 128MB, so a real rolled log is read to the end.
            try:
                import gzip, io
                tail, seen = b"", 0
                with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
                    while seen < max(max_bytes * 64, 512 * 1024 * 1024):
                        chunk = gz.read(1024 * 1024)
                        if not chunk:
                            break
                        seen += len(chunk)
                        tail = (tail + chunk)[-max_bytes:]
                data = tail
            except Exception:
                return ""
        if len(data) > max_bytes:
            data = data[-max_bytes:]
        return data.decode("utf-8", "replace")
