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

Windows에서 PowerShell을 열고 프로젝트 루트에서 실행한다. 현재 배포 형식은 단일 exe가 아니라 `MDLogger.exe`와 `_internal` 폴더를 함께 만드는 onedir 형식이다.

### 설정 생성 및 빌드

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

### 배포 전 검증 및 ZIP 생성

산출물 전체를 검사하고 체크섬을 생성한다.

```powershell
uv run python -m mdlogger.secret_scan dist\MDLogger
uv run python -m mdlogger.checksum dist\MDLogger
```

시크릿 스캔 결과가 0건인지 확인한 뒤, 폴더 전체를 ZIP으로 묶는다.

```powershell
Compress-Archive -Path dist\MDLogger -DestinationPath dist\MDLogger-win64.zip -Force
```

`MDLogger.exe`만 따로 배포하면 `_internal` 파일이 없어 실행되지 않는다. 반드시 `MDLogger-win64.zip`처럼 `MDLogger` 폴더 전체를 배포한다.
