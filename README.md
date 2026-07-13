# MD WCQ 전적 로거

마스터듀얼 **WCQ(World Championship Qualifier)** 전적을 듀얼 한 판마다 빠르게 기록하는 Windows 데스크톱 앱입니다.
오버레이가 아니라 독립된 일반 창으로, 게임이 끝나면 alt-tab 으로 전환해 클릭 몇 번으로 기록합니다.

- WCQ는 단판 → **레코드 1개 = 듀얼 1판**
- 점수는 2nd STAGE 누적 점수만 다룹니다(단계 선택 없음)
- enum 입력(승/패, 선/후공, 종료 방식)은 전부 버튼·칩 → **오타 차단**. 손 타이핑은 점수·메모뿐.

## 요구 사항
- Windows 10
- [uv](https://docs.astral.sh/uv/) (Python 3.13 자동 사용 — `.python-version` 으로 고정)

## 설치 / 실행
```bash
uv sync          # 최초 1회: 가상환경 + 의존성 설치
uv run mdlogger   # 앱 실행  (또는: uv run python -m mdlogger)
```

## 사용 흐름
1. **화면1** — 상단에 오늘 전적(`N승 M패`), 큰 **승 / 패** 버튼.
2. 버튼을 누르면 **화면2(상세)** 로 전환. 상단 색 배너(승=초록/패=빨강)를 누르면 결과를 다시 고를 수 있습니다.
3. 선/후공 · **내 덱** · 상대 덱 · 소요 턴 · 종료 방식 · 점수 · 메모를 채우고 **확인** → SQLite 저장 후 화면1 복귀.
4. 화면1의 **↶ 마지막 기록 취소** 로 직전 기록을 되돌릴 수 있습니다(확인 후 삭제).
5. **통계 / 기록** 버튼으로 별도 창을 엽니다.
   - `통계` 탭: 요약 카드 · 점수 시계열(꺾은선, 승/패 색 점) · 상대 덱별 매치업(전체/선공/후공 필터) · CSV/XLSX 내보내기
   - `기록 관리` 탭: 전체 레코드 표에서 편집 / 삭제

### 입력 도움말
- **점수**: 직전 레코드 점수가 자동 프리필되고, 값을 바꾸면 옆에 델타(예: `+2,600`)가 표시됩니다. 저장은 절댓값.
- **내 덱 / 상대 덱**: 같은 후보 목록(`decks.json`)에서 고릅니다. 타이핑하면 부분일치로 필터링되고, 모호하면 저장이 막히니 후보에서 확정하세요. **내 덱은 직전 판의 값으로 자동 프리필**되어, 같은 덱으로 계속 돌리면 그대로 두면 됩니다.

## 덱 후보 편집 — `decks.json` (내 덱·상대 덱 공용)
프로젝트 루트의 `decks.json` 을 직접 편집하면 됩니다(문자열 배열). 내 덱·상대 덱 둘 다 이 목록에서 고릅니다. 앱은 매 입력마다 다시 읽으므로 재시작이 필요 없습니다.
- `"기타"` 는 없으면 자동으로 추가됩니다.
- 파일이 없으면 기본 시드(`"기타"` 하나)가 자동 생성됩니다. 실제 덱은 직접 채워 넣으세요.

```json
[
  "엑조디아",
  "블루아이즈",
  "기타"
]
```

## 데이터 위치
- DB: `data/games.db` (SQLite 단일 파일)
- 덱 후보: `decks.json` (프로젝트 루트)
- 환경변수 `MDLOGGER_DATA_DIR` 로 DB 디렉터리를 따로 지정할 수 있습니다.

### DB 스키마 (`games`)
| 컬럼 | 설명 |
|---|---|
| `id` | 행 고유 식별자(자동 증가). "몇 번째 판"은 `played_at` 정렬 순번으로 별도 계산 |
| `played_at` | ISO 타임스탬프(로컬). 시계열 x축이자 정렬 기준 |
| `result` | `win` / `lose` |
| `turn_order` | `first` / `second` |
| `my_deck` | 내 덱 |
| `opp_deck` | 상대 덱 |
| `turns` | 소요 턴 |
| `end_reason` | `regular` / `surrender` / `timeout` / `disconnect` |
| `score_after` | 2nd STAGE 누적 점수(절댓값) |
| `note` | 메모 |

## 배포 — exe 만들어 친구에게 공유
터미널 없이 더블클릭으로 실행되는 단독 실행 파일을 만들 수 있습니다(PyInstaller).

### 빌드
```bash
uv sync                       # pyinstaller 포함 (최초 1회)
uv run pyinstaller --noconfirm --clean --onefile --windowed --name MDLogger run.py
```
- 결과물: `dist/MDLogger.exe` (약 62MB, 단일 파일)
- 이후엔 생성된 스펙으로 재빌드 가능: `uv run pyinstaller MDLogger.spec`

### 실행 / 데이터
- `MDLogger.exe` 를 **빈 폴더에 넣고** 실행하세요. 첫 실행 시 같은 폴더에 `decks.json` 과 `data/games.db` 가 생깁니다.
- 어디서든 동작하는 **포터블** 앱입니다. 폴더째 옮기면 기록도 함께 갑니다.
- 본인이 정리한 덱 목록을 같이 주고 싶으면 `decks.json` 을 exe 옆에 함께 넣어 전달하세요.

### 친구에게 보내기
- 62MB라 이메일 첨부는 어렵습니다 → **Google Drive / OneDrive / 카톡 파일** 로 보내거나 `.zip` 으로 압축해 전달하세요.
- 친구 PC에서 처음 실행하면:
  - **"Windows의 PC를 보호했습니다"** 창 → 서명 안 된 앱이라 정상입니다. **추가 정보 → 실행** 을 누르면 됩니다.
  - 백신이 새 exe를 잠깐 오탐할 수 있습니다. 차단되면 예외 처리하거나 아래 onedir 방식을 쓰세요.
  - onefile은 첫 실행 때 압축 해제로 몇 초 걸립니다(이후엔 빠름).

### 대안: onedir (시작 빠름 / 오탐 적음)
```bash
uv run pyinstaller --noconfirm --clean --onedir --windowed --name MDLogger run.py
```
- 결과물: `dist/MDLogger/` 폴더(`MDLogger.exe` + `_internal/`). 폴더째 `.zip` 압축해 전달 → 친구는 풀어서 `MDLogger.exe` 실행.

## 개발 / 테스트
```bash
uv run pytest             # db / export 로직 단위 테스트
```

## 기술 스택
Python 3.13 · PySide6 · SQLite · pyqtgraph · openpyxl(XLSX) · 표준 csv 모듈(CSV)
