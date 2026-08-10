# 마스터듀얼 전적 로거

듀얼 한 판마다 승/패를 빠르게 기록하는 데스크톱 앱(PySide6). Windows · macOS · Linux 모두 지원.

## 요구 사항

- [uv](https://docs.astral.sh/uv/) (Python 3.13)

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
