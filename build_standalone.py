import platform
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
ENTRY_POINT = ROOT / "src" / "browniantrack" / "__main__.py"


def main() -> None:
    system = platform.system()
    if system not in {"Linux", "Windows"}:
        raise SystemExit(f"Plataforma não suportada para este build: {system}")

    DIST.mkdir()

    with tempfile.TemporaryDirectory(prefix="browniantrack-build-") as temp_dir:
        temp_path = Path(temp_dir)
        app_dir = temp_path / "dist" / "BrownianTrack"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--onedir",
                "--windowed",
                "--name",
                "BrownianTrack",
                "--paths",
                str(ROOT / "src"),
                "--distpath",
                str(temp_path / "dist"),
                "--workpath",
                str(temp_path / "work"),
                "--specpath",
                str(temp_path),
                "--collect-all",
                "pims",
                "--collect-all",
                "trackpy",
                "--collect-all",
                "av",
                str(ENTRY_POINT),
            ],
            cwd=ROOT,
            check=True,
        )

        if system == "Windows":
            archive = DIST / "BrownianTrack-windows-x86_64.zip"
            with zipfile.ZipFile(
                archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
            ) as bundle:
                for path in app_dir.rglob("*"):
                    if path.is_file():
                        bundle.write(path, path.relative_to(app_dir.parent))
        else:
            archive = DIST / "BrownianTrack-linux-x86_64.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                bundle.add(app_dir, arcname=app_dir.name)

    print(f"Pacote standalone criado: {archive}")


if __name__ == "__main__":
    main()
