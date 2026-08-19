# MDLogger 릴리스 빌드

이 문서는 MDLogger의 Flatpak 배포판과 Windows exe 배포판을 만드는 절차를 기록한다.
모든 명령은 프로젝트 루트에서 실행한다.

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
git ls-files -c -o --exclude-standard | tar -cf - -T - | tar -xf - -C "$STAGE"
cp src/mdlogger/remote/_bundled_config.py "$STAGE/src/mdlogger/remote/"

flatpak-builder --user --install --force-clean \
  --state-dir="$STAGE/state" \
  --repo="$STAGE/repo" \
  "$STAGE/build" \
  "$STAGE/flatpak/io.github.dusten45.MDLogger.yaml"
```

GitHub Releases 등에 올릴 단일 `.flatpak` 파일을 생성한다.

```bash
mkdir -p dist/linux
flatpak build-bundle "$STAGE/repo" \
  dist/linux/MDLogger.flatpak \
  io.github.dusten45.MDLogger
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

시크릿 스캔 결과가 0건인지 확인한다. 체크섬 manifest는 `dist\MDLogger.sha256`에 생성된다.

### 설치 프로그램 생성 (Inno Setup)

`scripts\installer_windows.iss`로 설치 프로그램을 만든다. Inno Setup 6을 설치한 뒤 `ISCC.exe`로 빌드한다.

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" scripts\installer_windows.iss
```

설치 프로그램은 `dist\installer\MDLoggerSetup-<버전>.exe`에 생성된다. 버전은 `src\mdlogger\_version.py`의 `__version__`과 일치해야 한다. 스크립트의 `MyAppVersion` 기본값을 직접 고치거나, 빌드 시 `/DMyAppVersion`으로 주입한다.

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DMyAppVersion=0.2.1 scripts\installer_windows.iss
```

설치 프로그램은 onedir 폴더 전체(`_internal/` 포함)를 Program Files에 설치하고 시작 메뉴·바탕화면 바로가기와 제거 프로그램을 만든다. 사용자 데이터(SQLite)는 OS 표준 데이터 디렉터리에 있으므로 제거 시에도 남는다. 배포는 `dist\installer\MDLoggerSetup-<버전>.exe` 파일 하나만 올리면 된다.
