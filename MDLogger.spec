# -*- mode: python ; coding: utf-8 -*-
"""MDLogger 배포 빌드 설정 (PyInstaller).

run.py 진입점 + 패키지 데이터를 번들한다. 데이터 파일은 ``collect_data_files``로
패키지에서 자동 수집한다(하드닝 N-4, 단계 4 아이콘):
- ``mdlogger/data/decks.json`` — 첫 실행 덱 카탈로그 시드
- ``mdlogger/ui/icons/*.svg``   — 테마 SVG 아이콘(undo/minus/plus)
- ``mdlogger/remote/_bundled_config.py`` — 빌드 시 생성된 publishable 설정 모듈.
  `config.py`가 동적 `importlib.import_module("mdlogger.remote._bundled_config")`로
  임포트하므로 정적 분석으로는 추적되지 않는다. `hiddenimports`에 명시해 번들한다.

배포용 ``--onefile --windowed`` 단일 실행 파일을 만든다. 모듈이 없으면(개발 저장소)
`hiddenimports` 항목은 무시되고 `config.py`는 ImportError를 흡수해 오프라인으로 동작한다.
"""

from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("mdlogger")

# 동적 import 문자열(`importlib.import_module`)이라 정적 분석 대상이 아니므로
# publishable 설정 모듈을 명시적으로 포함한다. 없으면 PyInstaller가 무시한다.
hiddenimports = ["mdlogger.remote._bundled_config"]

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MDLogger",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
