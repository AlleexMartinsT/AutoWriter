import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], cwd: Path) -> None:
    print(">", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd), check=True)


def _remove_if_exists(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)
    print(f"Removido: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build do PdfWatcher com PyInstaller.")
    parser.add_argument("--clean", action="store_true", help="Limpa pastas de build antes de compilar.")
    parser.add_argument(
        "--install-dev",
        action="store_true",
        help="Instala dependencias de build (requirements-dev.txt) antes de compilar.",
    )
    parser.add_argument(
        "--noconfirm",
        action="store_true",
        help="Passa --noconfirm para o PyInstaller.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    python = sys.executable
    spec = root / "PdfWatcher.spec"
    exe = root / "dist" / "PdfWatcher.exe"

    if not spec.exists():
        print(f"Arquivo de spec nao encontrado: {spec}")
        return 1

    if args.clean:
        _remove_if_exists(root / "build")
        _remove_if_exists(root / "dist")

    if args.install_dev:
        req_dev = root / "requirements-dev.txt"
        if not req_dev.exists():
            print(f"Arquivo nao encontrado: {req_dev}")
            return 1
        _run([python, "-m", "pip", "install", "-r", str(req_dev)], cwd=root)

    cmd = [python, "-m", "PyInstaller"]
    if args.noconfirm:
        cmd.append("--noconfirm")
    cmd.append(str(spec))

    _run(cmd, cwd=root)

    if exe.exists():
        print(f"Build finalizado: {exe}")
        return 0

    print("Build executado, mas o executavel nao foi encontrado em dist/PdfWatcher.exe")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
