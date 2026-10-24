"""CPython 3.15의 cryptography ABI3t 의존성을 현재 인터프리터에서 수집한다."""

from PyInstaller import compat, isolated
from PyInstaller.utils.hooks import logger


@isolated.decorate
def _loaded_python_abi3t_dll() -> str | None:
    import ctypes
    import importlib
    import sys
    from pathlib import Path

    if sys.platform != "win32":
        return None

    # Windows 로더가 실제로 선택한 DLL을 조회한다. PATH에서 다른 Python을 찾지 않는다.
    importlib.import_module("cryptography.hazmat.bindings._rust")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    kernel.GetModuleHandleW.restype = ctypes.c_void_p
    kernel.GetModuleFileNameW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
    ]
    kernel.GetModuleFileNameW.restype = ctypes.c_uint32
    handle = kernel.GetModuleHandleW("python3t.dll")
    if not handle:
        return None

    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel.GetModuleFileNameW(handle, buffer, len(buffer))
    if not 0 < length < len(buffer):
        raise RuntimeError("로드된 Python ABI3t DLL 경로를 확인하지 못했습니다.")
    source = Path(buffer.value).resolve(strict=True)
    runtime = Path(sys.base_prefix).resolve(strict=True)
    if (
        source.name.lower() != "python3t.dll"
        or not source.is_file()
        or not source.is_relative_to(runtime)
    ):
        raise RuntimeError(
            "Python ABI3t DLL이 현재 인터프리터 배포 범위 밖에 있습니다."
        )
    return str(source)


binaries = []
if compat.is_win:
    source = _loaded_python_abi3t_dll()
    if source is not None:
        logger.info("cryptography의 Python ABI3t DLL 수집: %s", source)
        binaries.append((source, "."))
