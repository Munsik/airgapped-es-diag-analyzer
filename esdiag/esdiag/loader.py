"""진단 번들 로더.

support-diagnostics 산출물은 다음 형태 중 하나다.
  - diagnostic-xxxx.zip                     (압축 그대로)
  - .../api-diagnostics-YYYYMMDD-HHMMSS/    (압축 해제 디렉터리)
  - local / remote 모드는 위 파일 + logs/ 디렉터리(elasticsearch.log, gc.log 등) 포함

zip은 임시 파일로 풀지 않고 메모리에서 직접 읽는다(폐쇄망/읽기전용 환경 고려).
"""

import json
import os
import zipfile


class Bundle(object):
    def __init__(self, path):
        self.path = path
        self._zip = None
        self._names = []        # 번들 내 상대 경로 목록
        self._cache = {}
        self._root = ""
        if os.path.isdir(path):
            self._load_dir(path)
        elif zipfile.is_zipfile(path):
            self._load_zip(path)
        else:
            raise ValueError("지원하지 않는 입력입니다(zip 또는 디렉터리): %s" % path)
        self._index = {}
        for n in self._names:
            self._index.setdefault(os.path.basename(n).lower(), []).append(n)

    # ---------------- 적재 ----------------
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

    # ---------------- 원시 접근 ----------------
    def names(self):
        return list(self._names)

    def _read_raw(self, rel):
        if self._mode == "zip":
            with self._zip.open(rel) as fh:
                return fh.read()
        with open(os.path.join(self._base, rel), "rb") as fh:
            return fh.read()

    def resolve(self, name):
        """'nodes_stats.json' 또는 'commercial/ilm_explain.json' 형태로 실제 경로 탐색."""
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
        # 최상위(루트 바로 아래)에 가까운 것을 우선
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
        """JSON 파싱. 원문 문자열은 캐시하지 않는다(대형 번들 메모리 절약).

        cache=False 면 결과도 캐시하지 않는다 — 요약만 뽑고 버릴 대형 파일(cluster_state, mapping)용.
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
        """최상위가 JSON 객체인 대형 파일을 (키, 값) 단위로 하나씩 파싱해 돌려준다.

        전체를 한 번에 파싱하지 않으므로 최대 메모리는 원문 + 항목 하나 수준이다(mapping.json 등).
        형식이 예상과 다르면 전체 파싱으로 폴백한다.
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
        """대형 파일에서 anchor 이후 처음 나오는 "key": [...] 배열만 잘라 파싱한다(cluster_state 의 작은 조각용).

        찾지 못하면 None. 전체 파싱을 피하기 위한 것으로, 키 위치는 anchor 로 한정한다.
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
        """predicate(relpath)->bool 을 만족하는 경로 목록."""
        return [n for n in self._names if predicate(n)]

    def close(self):
        if self._zip is not None:
            try:
                self._zip.close()
            except Exception:
                pass

    # ---------------- 로그 ----------------
    def log_files(self):
        """local/remote 모드에서 수집된 서버 로그 파일 경로."""
        out = []
        for n in self._names:
            low = n.lower()
            if "/logs/" in low or low.startswith("logs/"):
                if low.endswith(".log") or low.endswith(".json") or ".log." in low:
                    out.append(n)
        return out

    def read_log(self, rel, max_bytes=8 * 1024 * 1024):
        """큰 로그는 뒤쪽(최근) 일부만 읽는다."""
        try:
            data = self._read_raw(rel)
        except Exception:
            return ""
        if len(data) > max_bytes:
            data = data[-max_bytes:]
        return data.decode("utf-8", "replace")
