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

from pathlib import Path
from shutil import copy2, copytree, ignore_patterns, rmtree

from PyInstaller.utils.hooks import collect_data_files

# 애플리케이션 자체 데이터는 기존 방식으로 수집한다. 법률 문서는 COLLECT 완료 후
# onedir 최상위에 복사해 PyInstaller의 기본 ``_internal`` 구조를 바꾸지 않는다.
datas = collect_data_files("mdlogger")

# pyqtgraph hook은 colors/maps 전체를 수집한다. 다음 두 palette는 upstream에서
# 라이선스와 출처를 확인할 수 없어, 사용자 결정에 따라 모든 데스크톱 배포에서 제외한다.
excluded_pyqtgraph_data = {
    "pyqtgraph/colors/maps/PAL-relaxed.hex",
    "pyqtgraph/colors/maps/PAL-relaxed_bright.hex",
}

# Windows PySide6 wheel에 포함될 수 있는 Mesa/LLVM 소프트웨어 OpenGL 렌더러
# (opengl32sw.dll) 및 불필요한 Qt PDF 이미지 플러그인/런타임(qpdf.dll, qt6pdf.dll,
# libqpdf.so, libqt6pdf.so.6)은 배포 번들에서 제외한다.
excluded_binaries = {
    "opengl32sw.dll",
    "qpdf.dll",
    "qt6pdf.dll",
    "libqpdf.so",
    "libqt6pdf.so.6",
    "qwebengineview.dll",
    "libqwebengineview.so",
}

# Linux 전용 런타임 패키지의 고지 파일은 Windows 배포 폴더에서 제외한다.
excluded_windows_license_dirs = (
    "cffi-2.1.1",
    "cryptography-50.0.2",
    "icu-73.2",
    "jeepney-0.9.0",
    "pycparser-3.12",
    "secretstorage-3.5.0",
    "qtwebengine",
    "qtmultimedia",
)

# 동적 import 문자열(`importlib.import_module`)이라 정적 분석 대상이 아니므로
# publishable 설정 모듈을 명시적으로 포함한다. 없으면 PyInstaller가 무시한다.
# Essentials만 설치하면 PyInstaller의 PySide6 메타패키지 검사가 이 모듈을 놓친다.
hiddenimports = ["mdlogger.remote._bundled_config", "PySide6.support.deprecated"]

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "_tkinter",
        "setuptools",
        "pkg_resources",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
    ],
    noarchive=False,
    optimize=0,
)
a.binaries = [
    entry
    for entry in a.binaries
    if Path(entry[0].replace("\\", "/")).name.lower() not in excluded_binaries
]
a.datas = [
    entry
    for entry in a.datas
    if entry[0].replace("\\", "/") not in excluded_pyqtgraph_data
    and entry[0].replace("\\", "/") != "PySide6/resources/icudtl.dat"
]
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
    icon=["icon/MDLogger-icon.ico"],  # Windows exe·태스크바·Inno 바로가기 아이콘
)

# onedir 산출물: dist/MDLogger/(MDLogger(.exe) + _internal/ 런타임 부속 파일)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="MDLogger",
)

# 사용자가 즉시 찾을 수 있도록 프로젝트와 제3자 법률 문서를 onedir 최상위에 둔다.
# 내부 CI 검증용 JSON(licenses/inventory/)과 유지보수 문서(licenses/sources/)는 제외한다.
distribution_root = Path(DISTPATH) / "MDLogger"
copy2("LICENSE", distribution_root / "LICENSE")
copy2("THIRD_PARTY_NOTICES.txt", distribution_root / "THIRD_PARTY_NOTICES.txt")
distribution_licenses = distribution_root / "licenses"
if distribution_licenses.exists():
    rmtree(distribution_licenses)
copytree(
    "licenses/desktop",
    distribution_licenses / "desktop",
    ignore=ignore_patterns(*excluded_windows_license_dirs),
)
