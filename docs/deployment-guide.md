# MDLogger 배포 가이드 (Releases 탭)

MDLogger(Master Duel 듀얼 로거)를 각 OS용 실행 파일로 만들어서
**GitHub Releases 탭**에 올리는 방법을 담은 문서입니다.

이 문서는 운영 runbook(`docs/operations/runbook.md`)과 달리 **사람이 순서대로
읽고 수행**할 수 있게 쓴 안내서예요. 배포가 처음이라면 이 문서만 아래에서 위로
차례로 따라 하면 됩니다.

---

## 이 문서를 먼저 읽어야 하는 이유

이 프로젝트는 **단일 실행 파일**(onefile)로 배포하는 데스크톱 앱입니다.
Python 코드를 실행 파일로 변환하는 도구가 **PyInstaller**이고, 어떤 파일을
묶을지는 **`MDLogger.spec`** 파일이 결정합니다.

배포는 결국 3가지 일의 반복입니다.

1. **빌드** — PyInstaller로 OS별 실행 파일 만들기
2. **검증** — 시크릿(비밀 키)이 안 들어갔는지·파일이 온전한지 확인
3. **릴리스** — GitHub Releases 탭에 빌드 산출물을 올려 태그(v0.1.6 등)로 배포

---

## 목차

- [1. 배포 방식 한눈에 보기](#1-배포-방식-한눈에-보기)
- [2. PyInstaller 파라미터 이야기](#2-pyinstaller-파라미터-이야기)
- [3. MDLogger.spec 파일 해설](#3-mdloggerspec-파일-해설)
- [4. 공통 준비 단계 (모든 OS 공통)](#4-공통-준비-단계-모든-os-공통)
- [5. OS별 빌드 방법](#5-os별-빌드-방법)
- [6. GitHub Releases 탭에 올리기](#6-github-releases-탭에-올리기)
- [7. 릴리스 정책 (온라인 차단/킬 스위치)](#7-릴리스-정책-온라인-차단킬-스위치)
- [8. 자주 겪는 실수와 꿀팁](#8-자주-겪는-실수와-꿀팁)

---

## 1. 배포 방식 한눈에 보기

```
[소스 코드] --PyInstaller--> [OS별 실행 파일] --업로드--> [GitHub Releases]
   main                        dist/ 폴더               태그: v0.1.6
```

**가장 중요한 규칙 먼저 하나:**

> ⚠️ **PyInstaller는 한 OS에서 다른 OS용 파일을 만들 수 없습니다.**
> Windows용 exe는 Windows에서, macOS용은 macOS에서, Linux용은 Linux에서
> 각각 빌드해야 해요. "한 번 빌드해서 다 갖다 쓰자"는 불가능합니다.

그래서 배포할 OS가 없다면 그 OS 머신에서 빌드를 해야 합니다
(사람마다 "여기서 빌드, 저기서 빌드"라 번거로울 수 있지만, GitHub Actions로
자동화하면 한 번에 다 만들 수 있어요 — 6장 참고).

---

## 2. PyInstaller 파라미터 이야기

PyInstaller는 명령줄 파라미터가 **아주 많습니다.** 다 외울 필요는 없어요.
왜냐하면 이 프로젝트는 설정 대부분을 `MDLogger.spec` 파일에 옮겨놨기 때문입니다.

### 2-1) 실제로 매일 쓰는 명령

```bash
uv run pyinstaller --noconfirm --clean MDLogger.spec
```

여기 쓰는 파라미터는 딱 2개입니다.

| 파라미터 | 하는 일 |
| -------- | ------- |
| `--noconfirm` | `dist/`·`build/` 폴더가 이미 있어도 묻지 않고 덮어씀 (없으면 확인 창에서 멈춤) |
| `--clean` | 빌드 캐시(`build/`)를 지우고 처음부터 다시 빌드. 주입한 설정/데이터가 바뀌어도 확실히 반영됨 |
| `MDLogger.spec` | 공사 **설계도**. 이 파일을 넘겨주면 옵션을 하나하나 안 써도 됨 |

`--clean`은 "항상 붙이는 게 좋은가?" 의문이 들 수 있는데, **배포 직전에는 붙이는
것을 권장합니다.** 이전 빌드 캐시가 남아 있으면 `_bundled_config.py`(주입한
Supabase 설정)나 데이터 파일이 제대로 갱신되지 않을 수 있거든요.

### 2-2) CLI 파라미터는 spec 파일 안에서 "이미 다 설정"되어 있음

자주 언급되는 옵션들이 CLI에 있지만, 이 프로젝트는 전부 `MDLogger.spec`에
반영되어 있어서 명령줄에 쓸 필요가 없습니다.

| CLI 파라미터 | 의미 | 이 프로젝트에서 |
| ------------ | ---- | --------------- |
| `--onefile` | 실행 파일 하나로 묶기 | spec 구조로 이미 반영 |
| `--windowed` | 콘솔 창 없이 GUI로 | spec의 `console=False` |
| `--name NAME` | 산출물 이름 | spec의 `name="MDLogger"` |
| `--add-data` | 데이터 파일 추가 | spec의 `collect_data_files()`가 대신 처리 |
| `--hidden-import` | 숨겨진 모듈 추가 | spec의 `hiddenimports`로 대신 처리 |
| `--exclude-module` | 모듈 제외 | spec의 `excludes` (지금은 비어 있음) |
| `--icon` | 앱 아이콘 지정 | spec엔 아직 없음(추가 시 설정) |
| `--version-file` | Windows 버전 정보 | 아직 비어 있음(추가 시 설정) |
| `--log-level` | 빌드 로그 상세도 | 빌드가 실패할 때만 `--log-level DEBUG` 유용 |

> 💡 **실무 팁:** 옵션을 바꾸고 싶을 때 **CLI 파라미터를 늘리지 말고
> `MDLogger.spec`을 수정**하세요. 그래야 다음 빌드 때 똑같이 재현됩니다.
> 명령은 항상 동일하게 `--noconfirm --clean MDLogger.spec`면 충분해요.

---

## 3. MDLogger.spec 파일 해설

`MDLogger.spec`은 PyInstaller가 "무엇을 어떻게 묶을지" 친절하게 미리 적어둔
설계도입니다. 섹션별로 뜯어보면 이해가 쉬워요.

```python
# ① 데이터 파일 자동 수집
datas = collect_data_files("mdlogger")
```

- `mdlogger` 패키지 안의 **데이터 파일**(`decks.json`, UI 아이콘 `*.svg`)을
  자동으로 전부 모아서 실행 파일에 넣습니다.
- 일일이 하나하나 나열하지 않아도 되게 해주는 편리한 함수예요.

```python
# ② 숨겨진 모듈 명시
hiddenimports = ["mdlogger.remote._bundled_config"]
```

- `remote/config.py`가 `importlib.import_module(...)`으로 **동적으로** 임포트하는
  `_bundled_config.py`는 정적 분석으로는 발견되지 않습니다.
- PyInstaller가 놓치지 않도록 여기에 명시해 강제로 번들하게 합니다.
- 빌드 시 이 파일이 없으면(개발 저장소) 그냥 무시되고, 실행 시 오프라인으로 동작해요.

```python
# ③ 무엇을 실행 진입점으로 쓸지
a = Analysis(["run.py"], ...)
```

- `run.py`가 앱의 시작점(`from mdlogger.app import main`)입니다.

```python
# ④ 실행 파일 본체 (핵심!)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
          name="MDLogger",   # 산출물 이름: dist/MDLogger(.exe)
          console=False,     # 콘솔 창 안 뜨게 (GUI 앱)
          upx=True,          # UPX로 실행 파일 용량 압축
          ...)
```

- `console=False` + 단일 `EXE` 구조 = **onefile + windowed** 설정입니다.
- `EXE`가 `a.binaries`, `a.datas`까지 직접 포함하고 별도 `COLLECT`가 없으므로
  실행 파일 **하나**로 묶이는 형태입니다.

| spec 요소 | 역할 |
| --------- | ---- |
| `collect_data_files()` | 패키지 데이터(덱 목록, 테마 아이콘) 자동 번들 |
| `hiddenimports` | 동적 임포트라 놓치기 쉬운 설정 모듈 강제 포함 |
| `Analysis(["run.py"])` | 실행 진입점 지정 |
| `EXE(..., console=False)` | 단일 windowed 실행 파일 생성 |
| `name="MDLogger"` | 산출물 이름 결정 |
| `upx=True` | 압축(UPX가 없으면 무시됨) |

> 📌 **주의:** `.gitignore`에 `*.spec`은 무시하되 `!MDLogger.spec`만 예외로 추적
> 중입니다. 로컬 하드코딩 아이콘 경로가 있던 다른 spec(`마듀 듀얼로그 생성기.spec`)
> 은 커밋하지 않도록 하기 위한 조치예요. **`MDLogger.spec`은 재현 가능한 깨끗한
> 설계도라 저장소에 남아 있습니다.** 이 파일은 절대 지우지 마세요.

---

## 4. 공통 준비 단계 (모든 OS 공통)

배포용 실행 파일은 **로그인·게스트 ingest**를 활성화하려면 Supabase
**publishable(anon) 키**를 빌드 시점에 주입해야 합니다. 이건 어떤 OS에서 빌드하든
동일하게 수행합니다. (service-role/secret 키를 넣으면 스크립트가 **거부**합니다.)

### 4-1) Supabase 설정 주입

```bash
MDLOGGER_SUPABASE_URL=<hosted project url> \
MDLOGGER_SUPABASE_ANON_KEY=<hosted anon key> \
    uv run python scripts/generate_build_config.py
```

- 그러면 `src/mdlogger/remote/_bundled_config.py`가 생깁니다.
- 이 파일은 `.gitignore` 대상이라 **절대 커밋되지 않습니다.**
- 빈 값이면 실패하고, secret류 값이 들어가면 경로가 차단됩니다.

### 4-2) 빌드

```bash
uv run pyinstaller --noconfirm --clean MDLogger.spec
```

산출물이 `dist/` 아래에 생깁니다. (OS별 경로는 5장 참고)

### 4-3) 검증 — 시크릿 스캔 + 체크섬

```bash
uv run python -m mdlogger.secret_scan dist/<산출물>
uv run python -m mdlogger.checksum dist/<산출물>
```

- 시크릿 스캔: service-role key·secret JWT·URL 인증 정보가 **0건**이어야 합니다.
- 체크섬: 파일이 온전한지 확인하고 배포 기록에 남길 해시를 만듭니다.

---

## 5. OS별 빌드 방법

각 OS에서 "4장의 공통 준비 단계"를 **그대로 다시** 수행하면 됩니다
(설정 주입 → 빌드 → 검증). OS마다 산출물 경로와 주의점만 다릅니다.

### 🪟 Windows

| 항목 | 내용 |
| ---- | ---- |
| 산출물 | `dist\MDLogger.exe` |
| 실행 환경 | Windows에서 PowerShell 또는 cmd |

```powershell
# 1) 설정 주입
$env:MDLOGGER_SUPABASE_URL = "<hosted project url>"
$env:MDLOGGER_SUPABASE_ANON_KEY = "<hosted anon key>"
uv run python scripts/generate_build_config.py

# 2) 빌드
uv run pyinstaller --noconfirm --clean MDLogger.spec

# 3) 검증
uv run python -m mdlogger.secret_scan dist\MDLogger.exe
uv run python -m mdlogger.checksum dist\MDLogger.exe
```

**주의할 점**

- **SmartScreen 경고:** 코드 서명(codesign)을 안 한 exe는 다운로드 시 "알 수 없는
  게시자" 경고가 뜹니다. 릴리스 노트에 **"보안 경고가 뜨면 추가 정보 → 실행"**
  안내를 넣어주세요. 배포 품질을 높이려면 유료 코드 서명 인증서로 `signtool`을
  써서 서명하면 경고가 사라집니다.
- **간혹 백신 오탐:** onefile 실행 파일은 가끔 백신이 오탐할 수 있습니다.
  오탐이 잦으면 해당 백신에 파일을 분류 신고하세요.

### 🍎 macOS

| 항목 | 내용 |
| ---- | ---- |
| 산출물 | `dist/MDLogger` (onefile 실행 파일) |
| 실행 환경 | 반드시 macOS에서 빌드 |

```bash
# 1) 설정 주입
MDLOGGER_SUPABASE_URL=<hosted project url> \
MDLOGGER_SUPABASE_ANON_KEY=<hosted anon key> \
    uv run python scripts/generate_build_config.py

# 2) 빌드
uv run pyinstaller --noconfirm --clean MDLogger.spec

# 3) 검증
uv run python -m mdlogger.secret_scan dist/MDLogger
uv run python -m mdlogger.checksum dist/MDLogger
```

**주의할 점**

- 현재 spec은 .app 번들이 아니라 **onefile 실행 파일**을 만듭니다. 더 알맞은
  배포 형태(.app + .dmg/.zip)를 원하면 spec을 보완해야 합니다.
- **Gatekeeper 차단 (중요):** 서명·공증(notarization)이 없으면
  "손상된 앱입니다" / "확인할 수 없는 개발자" 경고가 뜹니다. 사용자에게
  **마우스 오른쪽 클릭 → 열기**로 실행하는 법을 안내하거나, Apple Developer
  계정(유료, 연 $99)으로 서명·공증하면 해결됩니다.
- 스펙에 서명 관련 필드(`codesign_identity`, `entitlements_file`)가 이미
  자리만 잡혀 있습니다(`None`). 서명을 하게 되면 이 값만 채우면 됩니다.
- **Apple Silicon vs Intel:** 아키텍처가 달라서 둘 다 배포하려면 각각의
  머신에서 빌드하거나 Universal2 설정이 필요합니다.

### 🐧 Linux

| 항목 | 내용 |
| ---- | ---- |
| 산출물 | `dist/MDLogger` |
| 실행 환경 | 배포 대상과 비슷한 배포판에서 빌드 권장 |

```bash
# 1) 설정 주입
MDLOGGER_SUPABASE_URL=<hosted project url> \
MDLOGGER_SUPABASE_ANON_KEY=<hosted anon key> \
    uv run python scripts/generate_build_config.py

# 2) 빌드
uv run pyinstaller --noconfirm --clean MDLogger.spec

# 3) 검증
uv run python -m mdlogger.secret_scan dist/MDLogger
uv run python -m mdlogger.checksum dist/MDLogger
```

**주의할 점**

- 빌드한 배포판과 **glibc 버전이 다르면** 다른 시스템에서 실행이 안 될 수
  있습니다. 배포 대상과 같은 배포판(예: Ubuntu LTS)에서 빌드하는 게 안전합니다.
- PySide6가 Qt 플랫폼 플러그인은 번들하지만, 타 시스템에서 `libGL`,
  `libxkbcommon`, `xcb` 같은 시스템 라이브러리가 부족하면 안 뜰 수 있습니다.
  이 경우 **AppImage**로 감싸는 배포 방식을 고려해 보세요.

---

## 6. GitHub Releases 탭에 올리기

빌드가 끝났으면 태그를 원격에 밀고 Releases 탭에서 릴리스를 만듭니다.
프로젝트 깃 원격은 `github.com/dusten45/MDCalculator`입니다.

### 6-1) 태그 푸시

버전은 `src/mdlogger/_version.py`(현재 `0.1.6`)의 값과 **반드시 일치**해야
합니다. 태그가 로컬에 이미 있다면 그대로 밉니다.

```bash
git push origin v0.1.6
```

아직 태그가 없으면 만들고 밉니다.

```bash
git tag v0.1.6
git push origin v0.1.6
```

### 6-2) 웹 UI로 릴리스 만들기 (가장 직관적)

1. 브라우저에서 `https://github.com/dusten45/MDCalculator/releases` 접속
2. 오른쪽 위 **"Draft a new release"** 클릭
3. **Choose a tag** → `v0.1.6` 선택 (또는 "Create new tag")
4. **Target** → `main`
5. **Title** → `v0.1.6`
6. **Body** → 이번 버전의 기능/수정 요약을 한글로 (아래 양식 참고)
7. **Attach binaries** → 5장에서 만든 산출물을 끌어다 놓기
   (자주 배포한다면 체크섬 파일도 함께 첨부)
8. **Publish release** 클릭

> 릴리스 노트 예시 (Body 작성란에 붙여 쓰세요)

```
## v0.1.6

Master Duel 듀얼 결과 기록을 더 편하게!

### 추가
- (예) 듀얼 기록 시 덱 자동 추천 기능

### 변경
- (예) UI 테마 개선

### 수정
- (예) 특정 상황에서 앱이 종료되던 문제 해결

---

### 설치 안내
- Windows: 위의 `MDLogger.exe` 다운로드 후 실행
  - SmartScreen 경고가 뜨면 **추가 정보 → 실행**을 눌러주세요.
- macOS: `MDLogger` 실행 파일 다운로드 후 마우스 오른쪽 클릭 → 열기
```

### 6-3) gh CLI로 만들기 (터미널 선호자)

```bash
gh release create v0.1.6 \
  ./dist/MDLogger.exe \
  --title "v0.1.6" \
  --notes "릴리스 노트 내용..."
```

여러 OS 산출물을 올리려면 파일을 계속 나열하면 됩니다.

### 6-4) (권장) GitHub Actions 자동화

지금은 각 OS에서 수동 빌드 후 첨부해야 합니다. 태그가 자주 늘면
**GitHub Actions**로 태그 푸시 시점에 Windows/macOS/Linux 매트릭스로 자동 빌드해
Releases에 자동 업로드하도록 만들 수 있습니다. 이 경우 Supabase URL/anon 키를
**GitHub Secrets**에 넣어야 합니다 (anon 키만 빌드에 사용하고 service-role 키는
절대 안 넣게 구성).

---

## 7. 릴리스 정책 (온라인 차단/킬 스위치)

- 서버 `public.release_policies`가 **최소 지원 버전**과 **릴리스 킬 스위치**를
  강제합니다.
- 클라이언트 버전은 단일 출처(`src/mdlogger/_version.py`)에서 오며,
  게스트 ingest·장치 등록·아카이브 manifest로 서버에 전달됩니다.
- 예: `latest_version = minimum_supported_version = 0.1.6`로 정책을 잡으면
  `0.1.6` 미만 클라이언트는 **온라인(로그인·업로드·pull)이 차단**되지만,
  로컬 기록·내보내기는 항상 허용됩니다.
- 업데이트가 생기면 이 행의 latest/minimum/update_url을 갱신하고 배포하세요.
  자세한 절차는 운영 runbook `docs/operations/runbook.md` §1.2 참고.

---

## 8. 자주 겪는 실수와 꿀팁

| 상황 | 해결 |
| ---- | ---- |
| "빌드는 되는데 번들 설정이 안 들어간 것 같아" | `--clean`으로 캐시를 지우고, `_bundled_config.py`가 생성됐는지 확인 |
| 설정 주입이 "빈 값"으로 실패 | `MDLOGGER_SUPABASE_URL` / `MDLOGGER_SUPABASE_ANON_KEY`가 비어 있지 않은지 확인 |
| 주입 시도가 "secret"으로 거부 | service-role/secret 키가 아니라 **publishable(anon) 키**를 넣었는지 확인 |
| 시크릿 스캔이 0건이 아님 | 빌드 전에 넣은 값이 anon 키인지 재확인. 절대 배포하지 말 것 |
| 다른 OS에서 만든 파일을 올렸다 | PyInstaller는 크로스 컴파일 불가. **해당 OS에서 다시 빌드** |
| 배포 직전에 항상 해야 할 것 | `uv run ruff check .` / `uv run ruff format --check .` / `uv run ty check` / `uv run pytest` 통과 확인 |
| 실행 파일이 클 때 | `upx=True`가 이미 적용. 그래도 크면 불필요 의존성 `excludes`로 줄이기 |

---

### 배포 체크리스트 (Developer)

- [ ] `_version.py` 값이 태그와 일치하는지 확인
- [ ] 코드·테스트 통과 (ruff, ty, pytest)
- [ ] 대상 OS에서 설정 주입 → 빌드
- [ ] 시크릿 스캔 0건
- [ ] 체크섬 생성
- [ ] 태그 푸시 `git push origin v0.1.6`
- [ ] Releases 탭에서 산출물 첨부 + 릴리스 노트 작성 후 Publish
