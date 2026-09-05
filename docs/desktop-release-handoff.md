# 데스크톱 릴리스 자동화 인수인계

이 문서는 `v2.0.0`의 첫 데스크톱 릴리스를 준비하면서 완료한 구현, 현재 CI 실패 상태, 다음 작업 순서를 기록한다. 릴리스 운영 정책과 수동 검토 절차의 기준 문서는 [`release.md`](release.md)다.

## 현재 목표와 범위

첫 릴리스는 다음 두 배포물의 검증된 GitHub Release **draft** 생성까지다.

- Windows x64 Inno Setup 설치 프로그램
- Linux Flatpak bundle

다음은 범위 밖이다.

- macOS 패키징
- Flathub 제출
- tag 또는 release의 자동 생성·공개
- Windows 코드 서명
- 웹 배포와 데스크톱 배포의 결합

Windows 설치 프로그램은 현재 서명하지 않는다. GitHub Release는 workflow가 draft만 만들 수 있고, repository owner가 검토 후 GitHub UI에서만 publish한다.

## 구현 완료 상태

다음 커밋이 `main`에 반영되어 있다.

```text
924c6d697 feat: add third-party license compliance
880eb0a87 feat: add desktop release automation
608215040 fix: stabilize checksum output
2db502ad8 test: cover desktop release automation
242f7b0ec docs: document desktop release workflow
7d02190bf chore: prepare v2.0.0
46a9b12f9 fix: resolve release workspace paths
```

이번 인수인계 문서와 LF 줄바꿈 보정은 위 커밋 뒤의 별도 수정으로 반영한다.

### 추가된 자동화

- `.github/workflows/desktop-release.yml`
  - `workflow_dispatch` 전용이다.
  - tag 형식, annotated tag 여부, `src/mdlogger/_version.py` 버전, tag commit과 checkout `HEAD` 일치를 검증한다.
  - `prepare` → `windows`와 `flatpak` → `assemble-release` → 선택적 `publish-draft` 순서다.
  - 빌드는 검증된 tag commit으로 만든 동일 source archive를 사용한다.
  - 기본 권한은 `contents: read`이고, draft 생성 job만 `contents: write`를 가진다.
  - `create_draft=false`이면 asset artifact만 만들고 GitHub Release는 만들지 않는다.
- `scripts/release/`
  - release version 검증, source archive 생성, manifest 생성, Windows/Flatpak 검증 스크립트를 제공한다.
- `tests/test_release_automation.py`
  - release automation의 Python 동작을 검증한다.
- `src/mdlogger/checksum.py`
  - release checksum 산출에 사용한다.
- `scripts/release/third_party_source_delivery.json`
  - third-party corresponding source는 workflow가 내려받거나 자동 첨부하지 않으며, `pending_manual_attachment`로 기록한다.

### GitHub Environment 설정

소유자가 GitHub 저장소 설정에서 다음 Environment를 직접 준비해야 한다.

| Environment | 목적 | 필요한 설정 |
| --- | --- | --- |
| `desktop-release-build` | Windows·Flatpak 빌드에 publishable Supabase 설정 주입 | Variables에 `MDLOGGER_SUPABASE_URL`, `MDLOGGER_SUPABASE_ANON_KEY`를 설정한다. service-role key나 secret은 금지한다. |
| `desktop-release` | 검증된 asset으로 GitHub Release draft 생성 | repository owner 승인 규칙을 둔다. 변수나 secret은 필요 없다. |

## 검증 이력

데스크톱 release automation 구현 시 다음 검증은 성공했다.

```text
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest tests/test_release_automation.py tests/test_checksum.py tests/test_desktop_licenses.py
uv run pytest
uv run python scripts/generate_desktop_licenses.py --check
```

결과는 전체 `538 passed, 2 skipped`, release/checksum/license 관련 `47 passed`였다. workflow YAML은 로컬 `js-yaml`로 파싱했고 Bash 문법도 확인했다. Linux 개발 환경에는 `pwsh`가 없어 PowerShell 문법 실행 검증은 하지 못했다.

## 현재 CI 상태와 알려진 실패

사용자 보고에 따르면 `5236ba833 chore: stop tracking local-only design docs` 이후 GitHub Actions workflow run 33건이 한 번도 성공하지 않았다. 따라서 현재 CI 실패는 새 데스크톱 release automation만의 문제로 단정하면 안 된다.

### Windows `windows-package`: source 문서 hash drift

Windows runner에서 다음 명령이 실패했다.

```text
uv run python scripts/generate_desktop_licenses.py --check
```

오류는 다음과 같다.

```text
Tracked legal-file hash drift for desktop source documents:
licenses/sources/desktop-license-provenance.md
```

원인은 policy hash가 LF 바이트를 기준으로 하는데 Windows checkout이 해당 Markdown 문서를 CRLF로 전환할 수 있었던 것으로 판단된다. 이를 막기 위해 `.gitattributes`에 다음을 추가한다.

```gitattributes
# The desktop policy hashes these source documents as LF bytes on every platform.
licenses/sources/desktop-license-provenance.md text eol=lf
licenses/sources/desktop-source-offer.md text eol=lf
```

로컬에서 다음은 성공했다.

```text
git check-attr eol -- licenses/sources/desktop-license-provenance.md licenses/sources/desktop-source-offer.md
uv run python scripts/generate_desktop_licenses.py --check
uv run pytest tests/test_desktop_licenses.py
```

새 CI run에서 Windows hash drift가 사라지는지 먼저 확인한다. policy 산출물이나 라이선스 문서를 재생성해서 이 문제를 숨기지 않는다.

### Linux `validate`: PySide6 WebEngine import 불일치

실패 화면에는 다음 import error가 있었다.

```text
from PySide6.QtWebEngineCore import QWebEngineChromiumVersion, QWebEngineVersion
ImportError: cannot import name ...
```

그러나 `46a9b12f9`의 `scripts/generate_desktop_licenses.py`는 이미 다음의 소문자 API를 사용한다.

```python
from PySide6.QtWebEngineCore import qWebEngineChromiumVersion, qWebEngineVersion
```

따라서 코드를 되돌리거나 중복 수정하지 않는다. 새 run에서도 같은 오류가 반복되면 다음 순서로 조사한다.

1. runner log의 checkout SHA를 확인한다.
2. runner가 실제로 읽은 `scripts/generate_desktop_licenses.py` 내용을 확인한다.
3. 해당 source가 `main`과 다른 이유를 파악한 뒤에만 수정한다.

### Web CI: `npm audit`의 `fast-uri` high severity

웹 CI는 `fast-uri@3.1.5` advisory 때문에 실패한다. 알려진 의존성 경로는 다음과 같다.

```text
vite-plugin-pwa
→ workbox-build
→ ajv
→ fast-uri@3.1.5
```

이는 desktop release workflow가 npm을 실행해서 생긴 문제가 아니며, PWA 개발·빌드 의존성 문제다. `npm audit`를 약화하거나 제거하지 않는다. 별도 수정 작업에서 공식 advisory와 고정 버전을 확인한 뒤 최소 `package.json` override와 lockfile 갱신을 검토한다. 그때는 `npm ci`, `npm audit`, 웹 license 생성·검증, build, lint, test를 실행한다.

## tag 운영 상태

`src/mdlogger/_version.py`의 버전은 `2.0.0`이다. `v2.0.0` tag는 CI가 안정적으로 성공하기 전까지 만들거나 유지하지 않는다. 기존 로컬·원격 `v2.0.0` tag가 있으면 삭제한다.

CI가 성공한 뒤에만 final release-state commit에 annotated tag를 만든다.

```bash
git tag -a v2.0.0 -m "v2.0.0"
git push origin v2.0.0
```

그 뒤 GitHub Actions의 **Desktop release draft**를 다음 입력으로 수동 실행한다.

```text
tag: v2.0.0
create_draft: false
```

artifact-only run에서 Windows installer와 Flatpak bundle을 확인하기 전에는 `create_draft=true`를 사용하지 않는다. GitHub Release draft 생성 또는 publish는 이 문서의 후속 작업 범위이며, 자동 publish는 금지한다.

## 다음 세션 작업 계획

1. 이번 `.gitattributes` LF 보정 커밋의 새 CI run을 확인한다.
   - Windows `windows-package`에서 desktop license hash drift가 해소됐는지 확인한다.
   - Linux PySide6 import 오류가 재현되면 runner checkout과 실제 source를 비교한다.
2. `npm audit` 실패는 별도 원인으로 분리해 공식 advisory 기준의 최소 의존성 수정을 계획·검증한다.
3. CI가 green이 되기 전에는 어떤 release tag도 만들지 않는다.
4. CI가 안정화되면 GitHub Environments의 변수·승인 규칙을 확인한다.
5. 그 후에만 final release-state commit에 annotated `v2.0.0` tag를 만들고 `create_draft=false`로 desktop artifact-only workflow를 실행한다.
6. Windows installer와 Flatpak bundle, checksum, source archive, verification record를 검토한다.
7. 모든 검토가 끝난 경우에만 owner 승인 Environment를 거쳐 GitHub Release **draft**를 만든다. draft 공개 전에는 owner가 third-party corresponding source를 직접 재확인·첨부한다.

## 다음 세션용 쿼리

다음 내용을 새 세션의 첫 메시지로 사용한다.

```text
MDLogger의 데스크톱 릴리스 자동화 작업을 이어서 진행해 줘. 먼저 `docs/desktop-release-handoff.md`, `docs/release.md`, `AGENTS.md`를 읽고 Serena 프로젝트를 활성화한 뒤 관련 memory를 확인해. 현재 목표는 v2.0.0의 Windows x64 installer와 Linux Flatpak artifact-only release workflow를 안정화하는 것이다. CI가 성공할 때까지 release tag는 절대 만들거나 유지하지 마.

먼저 방금 푸시된 `.gitattributes` LF 보정 커밋의 GitHub Actions 결과를 확인해. Windows desktop license hash drift가 해결됐는지 확인하고, Linux PySide6 WebEngine import error가 반복되면 runner checkout SHA와 runner가 읽은 실제 source를 비교한 뒤에만 수정해. `npm audit`의 fast-uri 실패는 별도 웹 의존성 문제이므로 audit를 약화하지 말고, desktop 문제와 분리해서 상태를 보고해.

변경이 필요하면 최소 범위로 수정하고 프로젝트 규칙의 검증 명령을 실행해. CI가 모두 안정적으로 성공한 뒤에만 final release-state commit에 annotated v2.0.0 tag를 만들고 Desktop release draft workflow를 `tag=v2.0.0`, `create_draft=false`로 실행해. GitHub Release draft 생성·공개, production secret 사용, Flathub 제출은 명시적 승인 없이는 하지 마.
```
