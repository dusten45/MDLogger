"""실제 로드된 Python ABI3t shim만 수집하는 빌드 hook의 회귀 검증."""

from __future__ import annotations

import ast
import ctypes
import importlib
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyInstaller import compat, isolated

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "scripts/pyinstaller_hooks/hook-cryptography.hazmat.bindings._rust.py"


@pytest.fixture
def probe(monkeypatch):
    with monkeypatch.context() as context:
        context.setattr(compat, "is_win", False)
        namespace = runpy.run_path(str(HOOK))
    return namespace["_loaded_python_abi3t_dll"].__wrapped__


def fake_loader(monkeypatch, source: Path, *, loaded=True, result=None):
    class Function:
        def __init__(self, function):
            self.function = function

        def __call__(self, *args):
            return self.function(*args)

    queried = []

    def module_handle(name):
        queried.append(name)
        return 2**40 + 1 if loaded else 0

    def module_filename(handle, buffer, size):
        assert handle == 2**40 + 1
        buffer.value = str(source)
        return len(buffer.value) if result is None else result

    kernel = SimpleNamespace(
        GetModuleHandleW=Function(module_handle),
        GetModuleFileNameW=Function(module_filename),
    )
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False)
    return queried


@pytest.mark.parametrize("subdirectory", ["", "DLLs"])
def test_collects_loaded_shim_from_same_base_interpreter(
    probe, tmp_path, monkeypatch, subdirectory
):
    runtime = tmp_path / "Python315"
    source = runtime / subdirectory / "python3t.dll"
    source.parent.mkdir(parents=True)
    source.write_bytes("검증용 DLL 경로".encode())
    monkeypatch.setattr(sys, "base_prefix", str(runtime))
    queried = fake_loader(monkeypatch, source)

    assert probe() == str(source.resolve())
    assert queried == ["python3t.dll"]


@pytest.mark.parametrize("case", ["other-interpreter", "wrong-name", "directory"])
def test_rejects_ambiguous_or_foreign_dll(probe, tmp_path, monkeypatch, case):
    runtime = tmp_path / "Python315"
    runtime.mkdir()
    if case == "other-interpreter":
        source = tmp_path / "Python315t" / "python3t.dll"
        source.parent.mkdir()
    else:
        source = runtime / (
            "python315t.dll" if case == "wrong-name" else "python3t.dll"
        )
    if case == "directory":
        source.mkdir()
    else:
        source.write_bytes(b"test")
    monkeypatch.setattr(sys, "base_prefix", str(runtime))
    fake_loader(monkeypatch, source)

    with pytest.raises(RuntimeError, match="범위"):
        probe()


@pytest.mark.parametrize("length", [0, 32768])
def test_rejects_failed_or_truncated_loaded_path(probe, tmp_path, monkeypatch, length):
    fake_loader(monkeypatch, tmp_path / "python3t.dll", result=length)
    with pytest.raises(RuntimeError, match="경로"):
        probe()


def test_does_not_guess_shim_when_extension_did_not_load_one(
    probe, tmp_path, monkeypatch
):
    queried = fake_loader(monkeypatch, tmp_path / "python3t.dll", loaded=False)
    assert probe() is None
    assert queried == ["python3t.dll"]


def test_failed_source_import_aborts_collection(probe, tmp_path, monkeypatch):
    queried = fake_loader(monkeypatch, tmp_path / "python3t.dll")

    def fail_import(name):
        assert name == "cryptography.hazmat.bindings._rust"
        raise ImportError("원본 확장 모듈을 로드하지 못했습니다.")

    monkeypatch.setattr(importlib, "import_module", fail_import)
    with pytest.raises(ImportError, match="원본"):
        probe()
    assert queried == []


def test_non_windows_hook_collects_no_dll(monkeypatch):
    monkeypatch.setattr(compat, "is_win", False)
    monkeypatch.setattr(sys, "platform", "linux")
    namespace = runpy.run_path(str(HOOK))
    assert namespace["binaries"] == []
    assert namespace["_loaded_python_abi3t_dll"].__wrapped__() is None


def test_hook_adds_only_the_verified_shim_at_bundle_root(monkeypatch, tmp_path):
    source = str(tmp_path / "python3t.dll")
    monkeypatch.setattr(compat, "is_win", True)
    monkeypatch.setattr(isolated, "decorate", lambda function: lambda: source)
    namespace = runpy.run_path(str(HOOK))
    assert namespace["binaries"] == [(source, ".")]
    assert "hiddenimports" not in namespace


def test_spec_registers_focused_hook_without_replacing_upstream_hook():
    tree = ast.parse((ROOT / "MDLogger.spec").read_text(encoding="utf-8"))
    analysis = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Analysis"
    )
    hookspath = next(
        keyword.value for keyword in analysis.keywords if keyword.arg == "hookspath"
    )
    assert ast.literal_eval(hookspath) == ["scripts/pyinstaller_hooks"]
    assert not HOOK.with_name("hook-cryptography.py").exists()


@pytest.mark.skipif(
    sys.platform != "win32", reason="Windows의 실제 PE 의존성을 확인합니다."
)
def test_windows_wheel_dependency_has_collectable_same_runtime_shim():
    if sys.platform != "win32":
        pytest.skip("Windows의 실제 PE 의존성을 확인합니다.")
    import cryptography.hazmat.bindings._rust as rust
    import pefile

    binary = pefile.PE(rust.__file__, fast_load=True)
    try:
        binary.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]]
        )
        imports = {
            entry.dll.decode().lower()
            for entry in getattr(binary, "DIRECTORY_ENTRY_IMPORT")
        }
    finally:
        binary.close()
    if "python3t.dll" not in imports:
        pytest.skip("현재 wheel은 ABI3t shim을 요구하지 않습니다.")

    namespace = runpy.run_path(str(HOOK))
    assert len(namespace["binaries"]) == 1
    filename, destination = namespace["binaries"][0]
    source = Path(filename)
    assert source.name.lower() == "python3t.dll"
    assert source.is_file() and source.is_relative_to(Path(sys.base_prefix).resolve())
    assert destination == "."
