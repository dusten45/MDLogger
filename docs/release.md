# MDLogger 릴리스 빌드

이 문서는 MDLogger의 Flatpak 배포판과 Windows exe 배포판을 만드는 절차를 기록한다.
모든 명령은 프로젝트 루트에서 실행한다.

## 제3자 라이선스 산출물 갱신

dependency 또는 lockfile이 변경되면 배포 빌드 전에 데스크톱과 웹 고지를 모두 재생성한다.

```bash
cd web
npm ci
npm run generate:licenses
npm run check:licenses
npm run check:license-artifacts
npm run build
npm run check:license-bundle
npm run strip:source-maps
npm run check:secrets
cd ..

uv run python scripts/generate_desktop_licenses.py
uv run python scripts/generate_desktop_licenses.py --check

git status --porcelain --untracked-files=all -- \
  THIRD_PARTY_NOTICES.md THIRD_PARTY_NOTICES.txt \
  flatpak/requirements-runtime.txt licenses/desktop licenses/inventory licenses/sources \
  web/licenses/inventory.json web/public/third-party-notices.txt web/public/licenses
```

새 package, 새 license expression, 누락된 LICENSE/NOTICE/COPYING 파일이 발견되면 자동 승인하지 않는다. `scripts/desktop_license_policy.json` 또는 `web/scripts/generate-third-party-notices.mjs`의 검토 정책을 갱신하기 전에 실제 production 포함 근거와 upstream 원문을 확인한다.

Qt/PySide6, FFmpeg, cryptography/OpenSSL와 NumPy 자체의 source archive는 `licenses/sources/desktop-source-offer.md`에 기록된 URL, 크기와 SHA-256을 릴리스마다 다시 확인한다. 현재 Qt/PySide6 선택 경로는 GPL-3.0-only이며, 공식 archive에 detached signature가 없는 상태를 signature 검증 완료로 표현하지 않는다. 바이너리와 같은 릴리스 다운로드 위치에 검증한 source archive와 MDLogger source revision·패키징 파일을 함께 제공한다. NumPy wheel의 OpenBLAS/GCC runtime은 정확한 toolchain revision이 공개되지 않은 알려진 한계다. 보존된 고지와 라이선스 원문을 포함하되, upstream URL을 해당 바이너리의 exact corresponding-source snapshot으로 표현하지 않는다. 일치하는 revision과 source hash가 나중에 확인되면 릴리스 기록과 source archive에 추가한다.

Qt 또는 PySide6 버전이 바뀌면 새 Qt source archive에서 Chromium credits를 다시 생성한다. 이 파일은 wheel 제작자의 exact-build SBOM이 아니라, GN dependency graph를 확보할 수 없을 때 사용하는 보수적인 Linux source-tree superset이다.

```bash
mkdir -p /tmp/mdlogger-qt-license-audit
tar -xf qt-everywhere-src-6.11.1.tar.xz \
  -C /tmp/mdlogger-qt-license-audit \
  qt-everywhere-src-6.11.1/qtwebengine
cd /tmp/mdlogger-qt-license-audit/qt-everywhere-src-6.11.1/qtwebengine/src/3rdparty/chromium
python tools/licenses/licenses.py --format txt --target-os linux credits \
  "$OLDPWD/licenses/desktop/qt-6.11.1/qtwebengine/chromium-source-credits.html"
cd "$OLDPWD"
uv run python scripts/generate_desktop_licenses.py --check
```

pyqtgraph의 `PAL-relaxed.hex`와 `PAL-relaxed_bright.hex`는 라이선스와 출처를 확인할 수 없어 Windows와 Flatpak 배포물에서 제외한다. 두 파일이 다시 나타나면 릴리스를 중단한다.

### 선택적 Flatpak 경량화

현재는 검증이 끝난 full `PySide6` 구성을 유지한다. Windows PyInstaller는 사용하지 않는 Addons를 대부분 제외하므로 주요 Windows 배포 영향은 작지만, Linux Flatpak은 `PySide6-Addons` wheel 전체를 설치해 다운로드와 디스크 사용량이 커진다. 사용하지 않는 모듈은 실행 시 불러오지 않으므로 시작 시간과 메모리 영향은 제한적이다. 나중에 Linux 배포 크기를 줄이려면 현재 직접 사용하는 QtCore, QtGui, QtWidgets, QtSvg를 모두 제공하는 `PySide6-Essentials`로 전환할 수 있으며, 이때 lockfile, inventory, 고지와 실제 패키지 회귀 검사를 함께 갱신한다.

## Flatpak 배포판 생성 및 삭제

### 사전 준비

호스트에 `flatpak`과 `flatpak-builder`를 설치하고, 프로젝트가 요구하는 SDK를 설치한다.

```bash
flatpak install flathub org.freedesktop.Sdk//25.08
```

온라인 기능을 포함한 배포본은 빌드 전에 프로젝트 루트의 `.env`에서 Supabase publishable(anon) 설정을 생성한다. `.env` 파일이 없거나 필수 값이 비어 있으면 생성은 중단된다. service-role 또는 secret 키는 절대 사용하지 않는다.

```text
MDLOGGER_SUPABASE_URL=<hosted-project-url>
MDLOGGER_SUPABASE_ANON_KEY=<publishable-anon-key>
```

```bash
uv run python scripts/generate_build_config.py
```

### 빌드 및 번들 생성

`.venv`, 기존 빌드 산출물 등을 제외한 소스 스냅숏을 만들고 Flatpak을 빌드·설치한다.

```bash
STAGE="$(mktemp -d)"
git ls-files -c | tar -cf - -T - | tar -xf - -C "$STAGE"
cp src/mdlogger/remote/_bundled_config.py "$STAGE/src/mdlogger/remote/"

flatpak-builder --user --install --force-clean \
  --state-dir="$STAGE/state" \
  --repo="$STAGE/repo" \
  "$STAGE/build" \
  "$STAGE/flatpak/io.github.dusten45.MDLogger.yaml"

# Flatpak Builder 후처리(debug split/strip) 뒤의 최종 이미지 hash도 확인한다.
uv run python "$STAGE/scripts/verify_flatpak_license_payload.py" \
  --app-root "$STAGE/build/files" \
  --payload-phase final_image
```

GitHub Releases 등에 올릴 단일 `.flatpak` 파일을 생성한다.

```bash
mkdir -p dist/linux
flatpak build-bundle "$STAGE/repo" \
  dist/linux/MDLogger.flatpak \
  io.github.dusten45.MDLogger
```

설치 전 또는 임시 설치 후 다음 파일이 포함되고 제외 대상 palette가 없는지 검사한다.

```bash
flatpak run --command=sh io.github.dusten45.MDLogger -c \
  'test -f /app/share/licenses/mdlogger/LICENSE && \
   test -f /app/share/doc/mdlogger/THIRD_PARTY_NOTICES.txt && \
   test -f /app/share/licenses/mdlogger/inventory/desktop-linux.json && \
   test -f /app/share/licenses/mdlogger/inventory/qt-modules-linux-flatpak.json && \
   test -f /app/share/licenses/mdlogger/inventory/qt-third-party-runtime-linux-flatpak.json && \
   test ! -e /app/share/licenses/mdlogger/inventory/desktop-windows.json && \
   test -f /app/share/licenses/mdlogger/desktop/qt-6.11.1/qtwebengine/chromium-source-credits.html && \
   test -f /app/share/licenses/mdlogger/desktop/qt-6.11.1/qtmultimedia/ffmpeg/LICENSE.LGPL-2.1-or-later.txt && \
   test -f /app/share/doc/mdlogger/sources/desktop-source-offer.md && \
   test -f /app/share/licenses/mdlogger/desktop/qt-6.11.1/QT-THIRD-PARTY-ATTRIBUTIONS.json && \
   test -d /app/share/licenses/mdlogger/desktop/qt-6.11.1/third-party-source-files && \
   test ! -e /app/venv/lib/python3.13/site-packages/pip && \
   test ! -e /app/venv/bin/pip && \
   test ! -e /app/venv/lib/python3.13/site-packages/pyqtgraph/colors/maps/PAL-relaxed.hex && \
   test ! -e /app/venv/lib/python3.13/site-packages/pyqtgraph/colors/maps/PAL-relaxed_bright.hex'
```

생성한 파일의 설치·실행 방법은 다음과 같다.

```bash
flatpak install --user ./dist/linux/MDLogger.flatpak
flatpak run io.github.dusten45.MDLogger
```

### Flatpak 앱 삭제

앱만 제거하고 데이터는 남긴다.

```bash
flatpak uninstall io.github.dusten45.MDLogger
```

앱과 Flatpak 샌드박스 데이터까지 함께 제거한다.

```bash
flatpak uninstall --delete-data io.github.dusten45.MDLogger
```

더 이상 사용하지 않는 Flatpak 런타임도 정리하려면 다음을 실행한다.

```bash
flatpak uninstall --unused
```

## Windows exe 배포판 빌드

Windows에서 PowerShell을 열고 프로젝트 루트에서 실행한다. 배포는 두 단계로 이루어진다. 먼저 PyInstaller로 onedir 산출물(`MDLogger.exe` + `_internal/`)을 만들고, 이어서 Inno Setup으로 설치 프로그램(`MDLoggerSetup-<버전>.exe`)을 생성한다. 최종 배포물은 설치 프로그램 하나다.

### 설정 생성 및 PyInstaller 빌드

온라인 기능을 포함하려면 프로젝트 루트의 `.env`에 `MDLOGGER_SUPABASE_URL`과 `MDLOGGER_SUPABASE_ANON_KEY`를 설정한 뒤 publishable(anon) 설정을 생성한다.

```powershell
uv run python scripts/generate_build_config.py
uv run python scripts/generate_desktop_licenses.py --check

uv run pyinstaller --noconfirm --clean MDLogger.spec
```

빌드 결과는 다음 위치에 생성된다.

```text
dist\MDLogger\MDLogger.exe
dist\MDLogger\_internal\
```

### 배포 전 검증

산출물 전체를 검사하고 체크섬을 생성한다.

```powershell
uv run python -m mdlogger.secret_scan dist\MDLogger
uv run python -m mdlogger.checksum dist\MDLogger
```

시크릿 스캔 결과가 0건인지 확인한다. 체크섬 manifest는 `dist\MDLogger.sha256`에 생성된다. 이어서 법률 문서와 제외 대상 palette를 검사한다.

```powershell
$required = @(
  "dist\MDLogger\LICENSE",
  "dist\MDLogger\THIRD_PARTY_NOTICES.txt",
  "dist\MDLogger\licenses\inventory\desktop-windows.json",
  "dist\MDLogger\licenses\sources\desktop-source-offer.md"
)
$required | ForEach-Object { if (-not (Test-Path $_)) { throw "누락: $_" } }
$palettes = Get-ChildItem dist\MDLogger -Recurse -File |
  Where-Object { $_.Name -in @("PAL-relaxed.hex", "PAL-relaxed_bright.hex") }
if ($palettes) { throw "라이선스 미확인 palette가 포함되었습니다." }
```

`build\MDLogger\Analysis-00.toc`, `build\MDLogger\COLLECT-00.toc`와 `dist\MDLogger`의 Qt DLL·plugin 목록도 확인한다. `desktop-windows.json`은 resolver closure일 뿐 exact PyInstaller payload inventory가 아니므로, Linux Flatpak runtime inventory나 Chromium source credits를 Windows payload 증거로 표시하지 않는다.

### 설치 프로그램 생성 (Inno Setup)

`scripts\installer_windows.iss`로 설치 프로그램을 만든다. Inno Setup 6을 설치한 뒤 `ISCC.exe`로 빌드한다.

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" scripts\installer_windows.iss
```

설치 프로그램은 `dist\installer\MDLoggerSetup-<버전>.exe`에 생성된다. 버전은 `src\mdlogger\_version.py`의 `__version__`과 일치해야 한다. 스크립트의 `MyAppVersion` 기본값을 직접 고치거나, 빌드 시 `/DMyAppVersion`으로 주입한다.

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DMyAppVersion=1.0.0 scripts\installer_windows.iss
```

설치 프로그램은 onedir 폴더 전체(`_internal/` 포함)를 Program Files에 설치하고 시작 메뉴·바탕화면 바로가기와 제거 프로그램을 만든다. 설치 후 `{app}\LICENSE`, `{app}\THIRD_PARTY_NOTICES.txt`, `{app}\licenses\`가 존재하는지 확인한다. 사용자 데이터(SQLite)는 OS 표준 데이터 디렉터리에 있으므로 제거 시에도 남는다. Windows 바이너리 산출물은 `dist\installer\MDLoggerSetup-<버전>.exe` 하나이며, 같은 릴리스 다운로드 위치에 대응 source archive도 별도 첨부한다.

## 웹 배포 전 제3자 라이선스 확인

`web/`에서 실제 script를 사용해 생성 파일, production closure와 정적 배포물을 검사한다.

```bash
cd web
npm ci
npm run generate:licenses
npm run check:licenses
npm run check:license-artifacts
npm run lint
npm test
npm run build
npm run check:license-bundle
npm run strip:source-maps
npm run check:secrets

test -f dist/third-party-notices.txt
test -d dist/licenses
```

배포 후 `/third-party-notices.txt`가 열리고 로그인 footer와 설정 화면의 `오픈소스 라이선스` 링크가 해당 URL을 가리키는지 확인한다. 일반 production build에는 검사 전용 source map을 공개하지 않는다. 웹 정적 배포에도 Windows·Flatpak과 동일하게 해당 배포를 만든 정확한 MDLogger commit, source archive SHA-256, 고지 생성물과 패키징 파일을 같은 릴리스 위치에 제공한다.
