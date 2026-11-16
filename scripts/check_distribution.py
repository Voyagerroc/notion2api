"""Install the built wheel without network access and exercise its real commands."""

import os
from pathlib import Path
import subprocess
import tempfile
import venv


def main():
    wheel = next((Path(__file__).resolve().parents[1] / "dist").glob("*.whl"))
    with tempfile.TemporaryDirectory(prefix="notion2api-wheel-") as temporary:
        root = Path(temporary)
        environment = root / "environment"
        venv.create(environment, with_pip=True)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        subprocess.run([str(python), "-m", "pip", "install", "--no-deps", "--no-index", str(wheel)],
                       check=True, capture_output=True, text=True)
        env = dict(os.environ, NOTION2API_HOME=str(root / "unused-state"),
                   NOTION_ACCOUNTS="invalid", PYTHONIOENCODING="utf-8")
        for name in ("notion-ai", "voyager-relay", "notion-ai-server"):
            command = scripts / (name + (".exe" if os.name == "nt" else ""))
            result = subprocess.run([str(command), "--help"], cwd=root, env=env,
                                    capture_output=True, text=True, encoding="utf-8", timeout=20)
            if result.returncode:
                raise RuntimeError(f"Installed {name} --help failed: {result.stderr}")
        if (root / "unused-state").exists():
            raise AssertionError("Help must not create credential/state files")
    print("Wheel installation and all three offline help commands passed")


if __name__ == "__main__":
    main()
