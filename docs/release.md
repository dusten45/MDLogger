# MDLogger 릴리스 빌드

이 문서는 MDLogger의 Flatpak 배포판과 Windows exe 배포판을 만드는 절차를 기록한다.
모든 명령은 프로젝트 루트에서 실행한다.

기본 개발·Windows 빌드는 Python 3.15.1, Flatpak은 Freedesktop 26.08의 Python 3.14를 사용한다. 웹 도구는 루트 `.nvmrc`의 Node 26.12.1을 사용하며, `nvm use`로 선택한다.

## GitHub Actions 데스크톱 릴리스 초안

데스크톱 릴리스는 `.github/workflows/desktop-release.yml`의 수동 workflow만 사용한다. 지원 대상은 Windows x64 Inno Setup 설치 프로그램과 Linux Flatpak bundle이며, 웹 배포와 Flathub 제출은 이 workflow에 포함하지 않는다. workflow는 GitHub Release를 **draft**로만 만들며, 공개 publish 또는 기존 release·asset 덮어쓰기를 자동으로 수행하지 않는다.

### 최초 설정: GitHub Environment

다음 Environment는 GitHub 저장소의 **Settings → Environments**에서 소유자가 직접 만든다. workflow 파일이나 repository secret에 service-role key, 코드 서명 인증서, 개인 토큰, 비밀번호를 추가하지 않는다.

| Environment             | 용도                                                                | 필요한 설정                                                                                                                                                                                 |
| ----------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `desktop-release-build` | Windows·Flatpak 빌드에서 앱에 포함할 publishable Supabase 설정 제공 | Variables에 `MDLOGGER_SUPABASE_URL`, `MDLOGGER_SUPABASE_ANON_KEY`를 설정한다. 둘 다 앱에 포함 가능한 publishable 값이어야 하며 service-role/secret key는 금지한다. 승인 규칙은 두지 않는다. |
| `desktop-release`       | 검증된 asset으로 GitHub Release draft를 만드는 마지막 job           | repository owner를 승인자로 설정한다. Variables와 Secrets는 필요 없다. 이 job만 `contents: write` 권한을 가진다.                                                                            |

첫 릴리스 범위에서는 Windows installer에 코드 서명을 하지 않는다. 인증서를 구매하거나 GitHub에 보관하지 않는다. 따라서 사용자는 Windows SmartScreen 경고를 볼 수 있으며, 이 상태를 release 검토 시 확인한다. 코드 서명 도입은 인증서 공급자·보관 방법·SmartScreen 운영 정책이 정해진 별도 작업으로 진행한다.

### 실행 전 tag 계약

workflow는 이미 존재하는 **annotated** `v<major>.<minor>.<patch>` tag만 받는다. 예를 들어 `v1.2.3`은 `src/mdlogger/_version.py`의 `__version__ = "1.2.3"`과 정확히 일치해야 한다. lightweight tag, prerelease suffix가 붙은 tag, 현재 checkout과 다른 tag commit, 수정되거나 untracked 파일이 있는 checkout은 초기에 거부된다.

기존 tag가 이 계약에 맞지 않으면 tag를 이동하거나 다시 쓰지 않는다. release 자동화가 포함된 새 commit에서 version을 올리고, 그 commit에 새 annotated tag를 만든다. 예시는 다음과 같다.

```bash
git tag -a v1.2.3 -m "v1.2.3"
git push origin v1.2.3
```

### 수동 workflow 실행

1. GitHub Actions에서 **Desktop release draft**를 선택하고 **Run workflow**를 누른다.
2. `tag`에 검증할 existing annotated tag를 입력한다.
3. 처음에는 `create_draft=false`로 실행해 Windows installer·Flatpak bundle·source archive artifact만 검토할 수 있다. 이 경우 GitHub Release는 만들지 않는다.
4. 같은 tag의 artifact와 검증 기록이 확인되면 `create_draft=true`로 새 실행을 시작한다. 기존 release가 있으면 workflow는 실패하며 덮어쓰지 않는다.

`prepare` job은 tag commit에서 source archive를 만들고 checksum을 기록한다. Windows와 Flatpak job은 각자 작업 디렉터리가 아니라 이 동일한 archive를 checksum 검증 후 풀어 빌드한다. Windows는 PyInstaller onedir, Inno Setup compile, 무인 설치 및 설치 payload 검사를 수행한다. Flatpak은 final image license payload 검사, bundle 생성, 새 GitHub runner의 user Flatpak 설치 검사를 수행한다. build job에는 Release 쓰기 권한이 없다.

### Draft 검토와 공개

자동 생성되는 release body에는 `변경 사항` 섹션만 들어 있다. `변경 사항` 섹션에는 **직전 릴리스 대비 사용자에게 보이는 변경 사항만** 작성한다. 그 밖의 기술 정보, 플랫폼별 checksum, source 상태, 검증 결과와 체크리스트는 release manifest와 이 문서에만 유지한다. 소유자는 AI 에이전트가 준비한 tag 비교 요약을 참고할 수 있지만, 공개할 문구와 publish 결정은 소유자가 최종 승인한다.

workflow가 GitHub Release draft에 업로드하는 사용자 배포용 asset은 다음 4개다.

```text
MDLoggerSetup-<version>.exe
MDLoggerSetup-<version>.exe.sha256
MDLogger-<version>.flatpak
MDLogger-<version>.flatpak.sha256
```

MDLogger 자체의 소스 아카이브는 GitHub Release가 자동으로 첨부하는 `Source code (zip)` 및 `Source code (tar.gz)`로 제공되며, CI 내부 검증용 `MDLogger-<version>-source.tar.gz`와 `MDLogger-<version>-release-manifest.json`은 GitHub Actions workflow artifact(`release-assets-<run_id>`)에 보관된다. 수정하지 않은 제3자 라이브러리(Qt, PySide6, cryptography, OpenSSL, NumPy)의 원본 소스는 **GPL-3.0 제6조 d항**에 따라 각 공식 업스트림 서버(`download.qt.io`, `github.com`, `files.pythonhosted.org`)를 통해 제공되며, 저장소 내 `licenses/sources/desktop-source-offer.md`를 통해 정확한 다운로드 URL과 SHA-256 해시를 안내한다.

공개 전에는 다음을 확인한다.

- installer, Flatpak bundle, source archive의 `.sha256`이 manifest와 일치하는지
- Windows와 Linux 환경에서 설치·실행·법률 문서 열기가 가능한지
- Windows installer가 unsigned임과 SmartScreen 안내가 현재 정책에 맞는지
- `변경 사항` 섹션이 사용자용 변경 사항만 포함하는지

모든 항목을 확인한 뒤에만 GitHub Release 화면에서 draft를 publish한다. draft 생성이나 asset upload가 실패하면 workflow는 자동으로 재시도하거나 asset을 교체하지 않는다. 소유자가 draft를 유지 또는 삭제하고 원인을 고친 뒤, **새 commit과 새 annotated tag**로 다시 시작한다.

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

# Linux에서는 Flatpak과 같은 Python 3.14 wheel을 별도 환경에서 검증한다.
UV_PROJECT_ENVIRONMENT=/tmp/mdlogger-license-env uv run --python 3.14.9 --frozen python scripts/generate_desktop_licenses.py
UV_PROJECT_ENVIRONMENT=/tmp/mdlogger-license-env uv run --python 3.14.9 --frozen python scripts/generate_desktop_licenses.py --check

git status --porcelain --untracked-files=all -- \
  THIRD_PARTY_NOTICES.md THIRD_PARTY_NOTICES.txt \
  flatpak/requirements-runtime.txt licenses/desktop licenses/inventory licenses/sources \
  web/licenses/inventory.json web/public/third-party-notices.txt web/public/licenses
```

새 package, 새 license expression, 누락된 LICENSE/NOTICE/COPYING 파일이 발견되면 자동 승인하지 않는다. `scripts/desktop_license_policy.json` 또는 `web/scripts/generate-third-party-notices.mjs`의 검토 정책을 갱신하기 전에 실제 production 포함 근거와 upstream 원문을 확인한다.

Qt/PySide6, cryptography/OpenSSL와 NumPy 자체의 source archive는 `licenses/sources/desktop-source-offer.md`에 기록된 URL, 크기와 SHA-256을 릴리스마다 다시 확인한다. 현재 Qt/PySide6 선택 경로는 GPL-3.0-only이며, 공식 archive에 detached signature가 없는 상태를 signature 검증 완료로 표현하지 않는다. 바이너리와 같은 릴리스 다운로드 위치에 검증한 source archive와 MDLogger source revision·패키징 파일을 함께 제공한다. NumPy wheel의 OpenBLAS/GCC runtime은 정확한 toolchain revision이 공개되지 않은 알려진 한계다. 보존된 고지와 라이선스 원문을 포함하되, upstream URL을 해당 바이너리의 exact corresponding-source snapshot으로 표현하지 않는다. 일치하는 revision과 source hash가 나중에 확인되면 릴리스 기록과 source archive에 추가한다.

Qt 또는 PySide6 버전이 바뀌면 실제 Essentials wheel과 같은 버전의 Qt/PySide source archive에서 법률 원문과 attribution을 다시 확인한다. Linux의 wheel 원본 hash와 Flatpak Builder 후처리 이후의 final-image hash는 각각 검증한다. 사용하지 않는 QtWebEngine, QtPdf, QtMultimedia와 Chromium/FFmpeg는 설치하지 않으며, inventory와 배포 검사에서도 이 제외 조건을 확인한다.

pyqtgraph의 `PAL-relaxed.hex`와 `PAL-relaxed_bright.hex`는 라이선스와 출처를 확인할 수 없어 Windows와 Flatpak 배포물에서 제외한다. 두 파일이 다시 나타나면 릴리스를 중단한다.

### Qt 배포 범위

앱이 사용하는 QtCore, QtGui, QtWidgets, QtSvg와 테스트용 QtTest는 `PySide6-Essentials`가 제공한다. umbrella `PySide6`와 Addons 대신 Essentials만 고정하여 사용하지 않는 모듈의 보안·배포 부담을 줄인다. Python import 이름은 계속 `PySide6`이며, PyInstaller에는 Essentials-only 설치에서도 필요한 `PySide6.support.deprecated` hidden import를 명시한다.

## Flatpak 배포판 생성 및 삭제

### 사전 준비

호스트에 `flatpak`과 `flatpak-builder`를 설치하고, 프로젝트가 요구하는 SDK를 설치한다.

```bash
flatpak install --user flathub org.freedesktop.Sdk//26.08
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
   test ! -e /app/venv/lib/python3.14/site-packages/PySide6/Qt/lib/libQt6WebEngineCore.so.6 && \
   test ! -e /app/venv/lib/python3.14/site-packages/PySide6/Qt/lib/libQt6Multimedia.so.6 && \
   test -f /app/share/doc/mdlogger/sources/desktop-source-offer.md && \
   test -f /app/share/licenses/mdlogger/desktop/qt-6.12.0/QT-THIRD-PARTY-ATTRIBUTIONS.json && \
   test -d /app/share/licenses/mdlogger/desktop/qt-6.12.0/third-party-source-files && \
   test ! -e /app/venv/lib/python3.14/site-packages/pip && \
   test ! -e /app/venv/bin/pip && \
   test ! -e /app/venv/lib/python3.14/site-packages/pyqtgraph/colors/maps/PAL-relaxed.hex && \
   test ! -e /app/venv/lib/python3.14/site-packages/pyqtgraph/colors/maps/PAL-relaxed_bright.hex'
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
  "dist\MDLogger\licenses\desktop\qt-6.12.0\LICENSES\GPL-3.0-only.txt"
)
$required | ForEach-Object { if (-not (Test-Path $_)) { throw "누락: $_" } }
$palettes = Get-ChildItem dist\MDLogger -Recurse -File |
  Where-Object { $_.Name -in @("PAL-relaxed.hex", "PAL-relaxed_bright.hex") }
if ($palettes) { throw "라이선스 미확인 palette가 포함되었습니다." }
```

`build\MDLogger\Analysis-00.toc`, `build\MDLogger\COLLECT-00.toc`와 `dist\MDLogger`의 Qt DLL·plugin 목록도 확인한다. Windows 배포 폴더에는 Linux 전용 런타임·고지(`qtwebengine`, `qtmultimedia`, `cryptography` 등)와 내부 CI 인벤토리(`licenses/inventory/`)를 포함하지 않는다.

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
