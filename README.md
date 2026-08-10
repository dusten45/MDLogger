# MD WCQ 전적 로거

마스터듀얼 **WCQ(World Championship Qualifier)** 전적을 듀얼 한 판마다 빠르게 기록하는 Windows 데스크톱 앱(PySide6).

## 요구 사항

- Windows 10
- [uv](https://docs.astral.sh/uv/)

## 설치 / 실행

```bash
uv sync          # 최초 1회
uv run mdlogger  # 실행
```

## 개발 / 테스트

```bash
uv run ruff check . && uv run ruff format --check .   # 린트/포맷
uv run ty check                                        # 타입 검사
uv run pytest                                          # 테스트
```

## 기술 스택

Python 3.13 · PySide6 · SQLite · pyqtgraph · openpyxl(XLSX)
