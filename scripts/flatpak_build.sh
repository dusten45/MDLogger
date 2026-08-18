#!/usr/bin/env bash
# MDLogger Flatpak 빌드·설치 스크립트
#
# 동작:
#   1) flatpak-builder 와 FreeDesktop SDK(25.08)가 있는지 확인하고, 없으면
#      사용자 당(--user) 설치를 안내·시도한다.
#   2) 생성된 Supabase 설정 모듈(_bundled_config.py)이 없으면 생성 스크립트로
#      만든다(환경변수 미지정 시 온라인 기능 제외). 생성 모듈은 .gitignore 라서
#      아래 워킹 트리 스냅숏에 빠지므로 명시적으로 복사한다.
#   3) 워킹 트리(추적 + 비추적, .gitignore 제외)로 정리된 소스 스냅숏을 임시
#      디렉터리에 만든 뒤 그 위에서 flatpak-builder 로 빌드·설치한다. 저장소의
#      .venv 나 dist/·build/ 가 빌드 소스에 섞이지 않는다.
#   4) 빌드 산출물을 Flatpak 런타임에 사용자 설치(--user)한다.
#
# 사용: ./scripts/flatpak_build.sh
#
# 환경변수:
#   MDLOGGER_SUPABASE_URL / MDLOGGER_SUPABASE_ANON_KEY
#       생성 설정 모듈에 넣을 publishable Supabase 값. 없거나 이미 생성된 모듈이
#       있으면 그대로 두고, 비어 있으면(온라인 기능 꺼짐) 경고 후 계속한다.
#   FLATPAK_BUNDLE  설정 시 실행 파일(<appid>.flatpak)도 생성
#   CLEANUP_BUILD   "1" 이면 빌드 스냅숏 디렉터리가 종료 후 삭제됨(기본 유지)
set -euo pipefail

APP_ID="io.github.dusten45.MDLogger"
RUNTIME_REF="org.freedesktop.Sdk//25.08"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="flatpak/${APP_ID}.yaml"
BUNDLED_CONFIG="src/mdlogger/remote/_bundled_config.py"

# --- 1) 도구 확인 -----------------------------------------------------------
if ! command -v flatpak-builder >/dev/null 2>&1; then
  echo "[오류] flatpak-builder 가 설치되어 있지 않습니다." >&2
  echo "  Fedora:  sudo dnf install flatpak-builder" >&2
  echo "  Ubuntu:  sudo apt install flatpak-builder" >&2
  echo "  기타:    설치 후 다시 실행하세요." >&2
  exit 1
fi

# 사용자에게 flathub 원격이 없으면 추가 (root 없이 가능)
if ! flatpak remotes --user | awk '{print $1}' | grep -qx flathub; then
  echo "[안내] 사용자 flathub 원격을 추가합니다."
  flatpak remote-add --if-not-exists --user flathub https://flathub.org/repo/flathub.flatpakrepo
fi

if ! flatpak info "${RUNTIME_REF}" >/dev/null 2>&1 \
  && ! flatpak info --system "${RUNTIME_REF}" >/dev/null 2>&1; then
  echo "[안내] FreeDesktop SDK 25.08 이 없어 설치를 시도합니다."
  flatpak install --user flathub "${RUNTIME_REF}"
fi

# --- 2) 정리된 소스 스냅숏 만들기 ------------------------------------------
STAGE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/mdlogger-flatpak.XXXXXX")"
if [[ "${CLEANUP_BUILD:-}" == "1" ]]; then
  trap 'rm -rf "$STAGE_ROOT"' EXIT
fi

echo "[1/3] 소스 스냅숏 준비 (워킹 트리)"

# 필수 Supabase 설정 모듈 생성 (없을 때만). 환경변수가 없으면 온라인 기능을
# 끈 채로 오프라인 빌드를 이어간다(경고만, 실패 아님).
if [[ ! -f "$REPO_ROOT/$BUNDLED_CONFIG" ]]; then
  if [[ -z "${MDLOGGER_SUPABASE_URL:-}" || -z "${MDLOGGER_SUPABASE_ANON_KEY:-}" ]]; then
    echo "[경고] MDLOGGER_SUPABASE_URL/ANON_KEY 이 없어 설정 모듈을 생략합니다."
    echo "       온라인(로그인·동기화·decks.json 갱신) 기능 없이 오프라인 빌드됩니다."
  else
    echo "[안내] 설정 모듈이 없어 생성합니다."
    uv run python "$REPO_ROOT/scripts/generate_build_config.py"
  fi
fi

# 커밋 여부와 무관하게 워킹 트리(추적 + 비추적)를 모으되 .gitignore 무시 항목은
# 제외한다. .venv·build·dist 등이 빌드 소스에 섞이지 않는다.
(
  cd "$REPO_ROOT" && git ls-files -c -o --exclude-standard | tar -cf - -T -
) | tar -xf - -C "$STAGE_ROOT"

# 생성 설정 모듈은 .gitignore 이므로 git ls-files 에서 빠졌다. 명시적으로 복사.
if [[ -f "$REPO_ROOT/$BUNDLED_CONFIG" ]]; then
  mkdir -p "$STAGE_ROOT/$(dirname "$BUNDLED_CONFIG")"
  cp "$REPO_ROOT/$BUNDLED_CONFIG" "$STAGE_ROOT/$BUNDLED_CONFIG"
fi

# --- 3) flatpak-builder 빌드·설치 -------------------------------------------
echo "[2/3] flatpak-builder 로 빌드·설치"
# state-dir 는 --force-clean 이 지우는 빌드 디렉터리 밖에 둔다. 안에 두면
# flatpak-builder 가 "지금 디렉터리/state-dir 상위 삭제 거부"로 실패한다.
# repo 도 빌드 디렉터리 밖에 두어 번들 대비 영속 OSTree 저장소로 남긴다.
flatpak-builder \
  --user \
  --install \
  --force-clean \
  --state-dir="$STAGE_ROOT/state" \
  --repo="$STAGE_ROOT/repo" \
  "$STAGE_ROOT/build" \
  "$STAGE_ROOT/$MANIFEST"

echo "[3/3] 설치 완료"
echo
echo "실행:  flatpak run ${APP_ID}"
echo "제거:  flatpak uninstall --user ${APP_ID}"

if [[ -n "${FLATPAK_BUNDLE:-}" ]]; then
  echo "번들 생성:"
  # --repo 로 내보낸 OSTree 저장소에서 .flatpak 단일 실행 파일로 뽑는다.
  flatpak build-bundle \
    "$STAGE_ROOT/repo" \
    "${FLATPAK_BUNDLE}" \
    "${APP_ID}"
fi
