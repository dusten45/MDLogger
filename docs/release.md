# MDLogger 빌드·릴리스

현재 빌드와 배포 절차만 관리한다. 기능 계획, 세션 인수인계, 과거 테스트 수와 오류 재현 기록은 공개 문서에 누적하지 않는다. 명령의 기준 디렉터리는 별도 표시가 없으면 저장소 루트다.

## 빌드 기준

| 대상 | 도구와 배포 형식 |
|---|---|
| Windows x64 | Python 3.15.1, PySide6-Essentials 6.12, PyInstaller onedir, Inno Setup 6 |
| Linux x86_64 | Freedesktop 26.08, SDK의 Python 3.14, Flatpak bundle |
| 웹/PWA | Node 26.12.1, Vite, Cloudflare Workers Static Assets |

버전의 기준은 [`_version.py`](../src/mdlogger/_version.py), [`.python-version`](../.python-version), [`pyproject.toml`](../pyproject.toml), [`.nvmrc`](../.nvmrc)와 각 lockfile이다. Ruff의 `py313`은 소스 문법 검사 기준이며 현재 Python 런타임 버전이 아니다. macOS 네이티브 패키지와 Windows 32비트·ARM64 전용 빌드는 제공하지 않는다.

## 개발과 검사

```bash
uv sync --locked --group dev
uv run mdlogger
```

앱은 OS 표준 사용자 데이터 폴더를 사용한다. 개발용 자료는 `MDLOGGER_DATA_DIR`로 분리한다. 원격 설정은 환경변수, 번들 설정, 현재 작업 디렉터리의 `.env` 순으로 읽으므로 환경변수만 지워서 오프라인 격리를 보장할 수는 없다.

Python 변경의 기본 검사는 다음과 같다. GUI 표시 장치가 없는 Linux에서는 `QT_QPA_PLATFORM=offscreen`을 사용한다.

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest --ignore=tests/integration
```

`tests/integration`은 실제 서버에 인증·경기·게스트 관측 요청을 보낼 수 있다. 운영 `.env`나 배포 설정을 사용하는 환경에서 전체 pytest를 무심코 실행하지 않는다. 실서버 통합 검사는 별도의 테스트 프로젝트와 폐기 가능한 계정·자료로 수행한다. 웹 검사와 서버 검사는 각각 [웹 README](../web/README.md), [Supabase README](../supabase/README.md)를 따른다.

## 릴리스 자동화

| workflow | 용도 | 공개 배포 자산 |
|---|---|---|
| [Windows release](../.github/workflows/windows-release.yml) | 서명된 Windows 앱 내 업데이트 | 설치 파일, 설치 파일 SHA-256, `update.json`, `update.json.sig` |
| [Desktop release draft](../.github/workflows/desktop-release.yml) | Windows와 Linux 동시 빌드 | 설치 파일과 SHA-256, Flatpak bundle과 SHA-256 |

두 workflow는 수동 실행하며 GitHub Release **draft만 생성**한다. 기존 Release·자산을 덮어쓰거나 자동 publish하지 않는다. 동시 빌드 workflow는 업데이트 metadata를 서명하지 않으므로 Windows 앱 내 업데이트 배포에 사용하지 않는다. Windows 전용 릴리스는 Linux와 웹을 배포하지 않는다.

### 설정과 태그

- `desktop-release-build` Environment에는 배포 가능한 `MDLOGGER_SUPABASE_URL`, `MDLOGGER_SUPABASE_ANON_KEY` Variables만 둔다. service-role key는 클라이언트에 포함하지 않는다.
- `desktop-release` Environment는 소유자 승인 대상으로 설정하고 `MDLOGGER_UPDATE_SIGNING_KEY` Secret을 보관한다. 비밀키는 로그·파일·artifact·명령행 인수에 출력하지 않는다.
- 입력은 기존 annotated `v<major>.<minor>.<patch>` 태그이며 `_version.py`와 정확히 일치해야 한다. 깨끗한 태그 소스에서 빌드한다.
- 기존 태그를 삭제·이동·재작성하여 검증 실패를 해결하지 않는다. 제품 수정은 새 커밋과 새 버전의 태그로 배포한다.
- Release 제목은 태그 이름과 정확히 같게 한다. `MDLogger ` 접두사를 붙이지 않는다. 제목 수정으로 태그·버전·자산·릴리스 노트를 바꾸지 않는다.

### 실행과 공개

1. 해당 소스의 CI 결과와 필요한 수동 검증을 확인한다.
2. 대상 workflow에 태그와 `create_draft`를 지정한다. `false`는 자산 검토용이며 Windows 서명·검증 단계를 생략하는 옵션이 아니다.
3. workflow는 태그 커밋의 소스 아카이브를 만들고 같은 아카이브의 체크섬을 확인하여 플랫폼별로 빌드한다. 잠금 의존성, 라이선스, 비밀값, 플랫폼 payload와 설치 검사를 수행한다.
4. Windows 서명 job은 동일 소스·자산의 provenance를 확인한 뒤 업데이트 metadata를 서명하고 독립 실행기로 정상·변조·서명 누락을 검사한다.
5. draft의 제목, 버전, 배포 파일, 체크섬, 서명, 검증 기록을 대조한 후 소유자가 공개한다. 공개 본문은 사용자에게 보이는 변경 사항만 담는다.

Windows 업데이트 배포에는 다음 네 파일이 같은 Release에 필요하다.

```text
MDLoggerSetup-<version>.exe
MDLoggerSetup-<version>.exe.sha256
MDLogger-<version>-update.json
MDLogger-<version>-update.json.sig
```

업데이트 manifest는 고정 공개 키로 UTF-8 원문 바이트의 RSA 3072비트/SHA-256/PKCS#1 v1.5 서명을 검증한다. 버전 상승, 플랫폼, 저장소 URL, 유효기간, 설치 파일 크기·SHA-256도 검사한다. 기본 유효기간은 90일이며 최대 366일이다. 체크섬만으로 서명을 대신하거나 네트워크에서 받은 공개 키를 자동 신뢰하지 않는다. 키 교체는 새 키를 신뢰하는 앱을 기존 키로 먼저 배포하는 별도 작업이다.

## 업데이트와 검증

Windows 설치판은 시작 후 공개된 정식 릴리스를 비차단 방식으로 확인한다. 다운로드·설치는 사용자 선택 후 진행하며, 초안·사전 릴리스는 설치하지 않는다. 관리자 범위의 Program Files 설치를 유지하므로 UAC 동의가 필요할 수 있다. 업데이트 서명은 Authenticode 코드 서명과 다르며 SmartScreen 경고가 사라진다는 뜻이 아니다.

v2.1.0 이전에는 앱 내 업데이트 기능이 없다. v2.1.0에서 v2.1.1로 전환할 때도 앱을 닫고 새 설치 파일을 직접 실행하는 수동 설치를 권장한다. 새 소스의 수정은 이미 설치된 구버전 실행기를 바꾸지 않는다. Linux는 수동 bundle 업데이트이며 자동 업데이트용 MDLogger Flatpak remote가 구성되어 있지 않다.

업데이트 캐시는 `%LOCALAPPDATA%\MDLogger\updates`에 별도로 저장한다. 실행기는 앱 종료를 기다린 뒤 installer만 승격하고 원래 사용자 권한으로 앱을 재실행한다. 자동 PC 재부팅이나 강제 앱 종료를 정상 경로로 사용하지 않는다.

**2026-10-26 소유자가 Windows 10·11에서 업데이트 정상 동작을 확인했다.** 이는 사용자 실기기 확인이며 CI 자동 검사의 결과와 구분한다. 업데이트 전후 버전, 설치 방식과 상세 인계 로그는 이 기록에 첨부되어 있지 않으므로 아래 조건 전체의 통과로 확대하지 않는다.

CI의 설치·재설치·데이터 sentinel·기동 검사와 `--verify-payload` 서명 검사 외에 확인할 조건은 다음과 같다.

- 앱에서 승인한 뒤 부모 PID 종료, 실행기의 `--job` 설치, 새 PID·버전·난수 시작 영수증까지 확인한다.
- UAC 승인·취소·다른 관리자 자격 증명을 사용한 경우에도 원래 사용자로 재실행되는지 확인한다.
- 기본 데이터 폴더와 `MDLOGGER_DATA_DIR`에서 계정·기록·미전송 자료 보존을 확인한다.
- 다중 창, 창 파괴, 동기화 정지 지연, 설치 실패, 시간 초과, 취소 후 재시도를 확인한다.
- 재부팅 필요 종료 코드에서도 자동 PC 재부팅과 강제 프로세스 종료가 없는지 확인한다.

검증은 별도 Windows 테스트 계정과 폐기 가능한 자료로 수행한다. Linux Qt 테스트나 가짜 서비스 결과를 OS 키링·실서버·Windows 전체 인계 성공으로 기록하지 않는다.

## 소스와 라이선스

MDLogger 소스는 해당 태그의 GitHub `Source code (zip/tar.gz)`로 제공한다. 빌드에 사용한 별도 소스 아카이브, checksum, provenance는 Actions artifact에 보관한다. 저장소·배포물의 법률 원문과 고지는 삭제하지 않는다.

제3자 라이브러리는 [소스 안내](../licenses/sources/desktop-source-offer.md)의 공식 업스트림 URL·확인된 해시로 안내한다. 현재 workflow는 제3자 소스 아카이브를 별도 공개 자산으로 첨부하지 않는다. URL 안내나 자동 검사의 성공만으로 모든 라이선스 의무가 충족되었다고 단정하지 않는다. 정확한 NumPy OpenBLAS/GCC 소스 revision, Qt exact-build SBOM과 소스의 지속적인 가용성 등 확인 범위·한계는 해당 안내와 [출처 기록](../licenses/sources/desktop-license-provenance.md)에 유지한다.

의존성이나 lockfile을 변경하면 다음을 확인한다.

- `scripts/desktop_license_policy.json`과 `scripts/generate_desktop_licenses.py`로 고지·inventory를 갱신하고 `--check`로 대조한다. Linux 증거는 Flatpak과 같은 Python 3.14 wheel 환경에서 확인한다.
- 웹 고지는 `web/README.md`의 생성·추적·실제 번들 검사를 수행한다. 검사에 사용한 source map은 배포 전에 제거한다.
- 새 라이선스, 누락 원문, hash 차이를 검사 완화로 숨기지 않는다. 라이선스 원문은 생성 요약문으로 대체하지 않는다.
- PySide6-Essentials만 사용하며 WebEngine·Pdf·Multimedia와 Chromium/FFmpeg를 포함하지 않는다. 출처 미확인 `PAL-relaxed.hex`, `PAL-relaxed_bright.hex`도 제외한다.
- Windows 고지는 설치된 법률 원문과 공개 소스 안내로 연결되어야 한다. Windows에서 제외하는 내부 inventory·source 문서를 로컬 설치 경로로 안내하지 않는다.

## 로컬 패키징

공개 릴리스는 위 workflow를 우선한다. 아래 명령은 로컬 패키징용이며 성공만으로 공개 준비가 완료되는 것은 아니다. 온라인 기능을 포함하려면 환경변수 또는 로컬 `.env`에 publishable Supabase 설정을 넣고 생성한다. `.env`와 생성된 `_bundled_config.py`는 커밋하지 않는다.

### Windows

PowerShell에서 실행한다. Inno Setup 6과 Windows 기본 .NET Framework compiler가 필요하다.

```powershell
uv sync --locked --group dev
uv run python scripts/generate_build_config.py
uv run python scripts/generate_desktop_licenses.py --check
pwsh -NoProfile -File scripts/update/build_helper.ps1
uv run pyinstaller --noconfirm --clean MDLogger.spec
pwsh -NoProfile -File scripts/ensure_inno_setup.ps1
$version = uv run python -c "from mdlogger._version import __version__; print(__version__)"
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "/DMyAppVersion=$version" scripts/installer_windows.iss
```

`dist/MDLogger/`가 onedir이고 설치 파일은 `dist/installer/MDLoggerSetup-<version>.exe`다. [Windows 검증 스크립트](../scripts/release/verify_windows_release.ps1)로 payload·설치·재설치·기동을 확인한다. 로컬 installer 생성만으로 서명된 업데이트 metadata가 생기지는 않는다. 앱 파일과 사용자 데이터는 별도 위치이며 제거 프로그램은 사용자 경기 DB를 삭제하지 않는다.

### Linux Flatpak

`flatpak`과 `flatpak-builder`가 필요하다. 아래 스크립트는 Flathub SDK 확인·설치와 앱의 사용자 설치를 수행한다.

```bash
uv run python scripts/generate_build_config.py
mkdir -p dist/linux
version="$(uv run python -c 'from mdlogger._version import __version__; print(__version__)')"
FLATPAK_BUNDLE="$PWD/dist/linux/MDLogger-$version.flatpak" bash scripts/flatpak_build.sh
flatpak run io.github.dusten45.MDLogger
```

배포 전에는 [Flatpak 검증 스크립트](../scripts/release/verify_flatpak_release.sh)와 `scripts/verify_flatpak_license_payload.py`로 설치 상태 및 strip/debug-split 이후 final-image payload를 확인한다. 검증 스크립트는 앱 설치·제거를 수행하므로 CI 또는 별도 테스트 계정에서 실행한다. 사용자는 `flatpak install --user`에 다운로드한 bundle 경로를 전달하여 설치한다.

## 서버·웹 호환성

현재 웹의 멱등 생성과 전체 기록 조회에는 `0030_idempotent_game_creates.sql`, `0031_web_read_models.sql`이 필요하다. schema 1 / payload 2 계약과 기존 로컬 naive ISO `played_at` 의미를 유지한다.

`0029_release_policy_v100.sql`은 최소 지원 버전을 변경하는 별도 정책이다. 적용 번호가 비었다는 이유로 실행하거나 실행하지 않은 migration을 적용된 것으로 표시하지 않는다. hosted 변경 전 `supabase migration list --linked`와 `supabase db push --linked --dry-run`으로 실제 대상과 정책 영향을 확인한다. 전체 migration 적용 명령을 무조건 운영 프로젝트에 실행하지 않는다.

웹은 별도로 빌드·배포한다. production은 `main`만 허용하고 배포 전 audit·라이선스·lint·테스트·번들·source map 제거·비밀값 검사를 수행한다. 자세한 명령과 PWA의 온라인 사용 경계는 [웹 README](../web/README.md)를 따른다.
