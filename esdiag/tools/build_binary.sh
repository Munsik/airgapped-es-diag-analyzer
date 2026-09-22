#!/usr/bin/env bash
# Python 이 없는 서버용 단독 실행 파일(esdiag) 빌드 — 선택 사항
#
# 빌드 머신에만 PyInstaller 가 필요합니다(인터넷 가능한 환경). 결과물은 Python 없이 실행됩니다.
#
# 중요: Linux 바이너리는 '빌드한 OS 의 glibc 버전 이상' 에서만 실행됩니다.
#       대상 서버와 같거나 더 오래된 OS(예: 대상이 RHEL 8 이면 RHEL 8) 에서 빌드하십시오.
#       Windows 용은 Windows 에서 빌드해야 합니다(크로스 빌드 불가).
#
#   bash tools/build_binary.sh          # dist/esdiag 생성
#   ./dist/esdiag 번들.zip --html report.html
set -euo pipefail
cd "$(dirname "$0")/.."
# 시스템 Python 을 건드리지 않도록 빌드 전용 가상환경 사용(PEP 668 환경 대응)
python3 -m venv build/venv
build/venv/bin/python -m pip install --quiet --upgrade pip pyinstaller
build/venv/bin/python -m PyInstaller --onefile --clean --name esdiag \
  --distpath dist --workpath build/pyinstaller --specpath build \
  --collect-submodules esdiag analyze.py
echo "생성: dist/esdiag"
echo "빌드 환경 glibc: $(ldd --version 2>/dev/null | head -1 || echo 확인 불가)"
