"""PyInstaller 빌드용 진입 스크립트.

PyInstaller 는 모듈(`-m`)이 아니라 스크립트 파일을 진입점으로 받으므로
패키지 절대 임포트로 main() 을 호출한다.
"""

from mdlogger.app import main

if __name__ == "__main__":
    main()
