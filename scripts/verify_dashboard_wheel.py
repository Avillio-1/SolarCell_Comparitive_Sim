"""Build a wheel and verify that the dashboard's runtime assets are packaged."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REQUIRED_ASSETS = {
    "solarclean/dashboard/defaults/riyadh_default.yaml",
    "solarclean/dashboard/templates/base.html",
    "solarclean/dashboard/templates/index.html",
    "solarclean/dashboard/templates/run_comparison.html",
    "solarclean/dashboard/static/dashboard.css",
    "solarclean/dashboard/static/dashboard.js",
    "solarclean/dashboard/static/chart.umd.js",
    "solarclean/dashboard/static/world_land.js",
    "solarclean/dashboard/static/fonts/IBMPlexSans-Regular.woff2",
    "solarclean/dashboard/static/fonts/OFL.txt",
}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="solarclean-wheel-") as temporary_directory:
        wheel_directory = Path(temporary_directory)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                ".",
                "--no-deps",
                "--no-build-isolation",
                "--wheel-dir",
                str(wheel_directory),
            ],
            check=True,
        )
        wheels = sorted(wheel_directory.glob("solarclean_dt-*.whl"))
        if len(wheels) != 1:
            raise SystemExit(f"Expected one SolarClean-DT wheel, found {len(wheels)}")
        with zipfile.ZipFile(wheels[0]) as archive:
            packaged_files = set(archive.namelist())
        missing = sorted(REQUIRED_ASSETS - packaged_files)
        if missing:
            raise SystemExit("Dashboard wheel is missing: " + ", ".join(missing))
        print(f"Verified {len(REQUIRED_ASSETS)} dashboard assets in {wheels[0].name}")


if __name__ == "__main__":
    main()
