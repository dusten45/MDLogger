"""패키지 단일 버전 소스(하드닝 N-1).

pyproject.toml은 hatchling dynamic version으로 이 파일의 ``__version__``을
읽는다. 이 값은 실제 릴리스 태그(git tag v0.1.6)와 일치해야 하며, 게스트 ingest·
장치 등록·아카이브 manifest로 서버에 전송된다. 여기에서만 수정한다.
"""

__version__ = "0.2.0"
