# -*- mode: python ; coding: utf-8 -*-
"""MDLogger 배포 빌드 설정 (PyInstaller).

run.py 진입점 + 패키지 데이터를 번들한다. 데이터 파일은 ``collect_data_files``로
패키지에서 자동 수집한다(하드닝 N-4, 단계 4 아이콘):
- ``mdlogger/data/decks.json`` — 첫 실행 덱 카탈로그 시드
- ``mdlogger/ui/icons/*.svg``   — 테마 SVG 아이콘(undo/minus/plus)
- ``mdlogger/remote/_bundled_config.py`` — 빌드 시 생성된 publishable 설정 모듈.
  `config.py`가 동적 `importlib.import_module("mdlogger.remote._bundled_config")`로
  임포트하므로 정적 분석으로는 추적되지 않는다. `hiddenimports`에 명시해 번들한다.

배포용 **onedir(폴더형) + windowed** 빌드를 만든다. 진입점 실행 파일과 부속 파일
(바이너리·데이터)을 같은 폴더에 두므로, onefile처럼 실행마다 임시 폴더에 압축을
풀지 않아 **시작이 빠르다**. 모듈이 없으면(개발 저장소) `hiddenimports` 항목은
무시되고 `config.py`는 ImportError를 흡수해 오프라인으로 동작한다.
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

# onedir: 부트스트래퍼(간이 실행기)만 exe에 담고, 실제 바이너리·데이터는
# 아래 COLLECT가 같은 폴더에 모아둔다. exclude_binaries=True가 그 분리의 핵심.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
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
    icon=["icon/DuelistCup.ico"],  # Windows exe·태스크바·Inno 바로가기 아이콘
)

# onedir 산출물: dist/MDLogger/(MDLogger(.exe) + _internal/ 부속 파일)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="MDLogger",
)
