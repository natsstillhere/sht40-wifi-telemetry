import os
import runpy
from pathlib import Path

project_dir = Path(__file__).resolve().parent
os.chdir(project_dir)
runpy.run_path(str(project_dir / "telemetry_launcher.py"), run_name="__main__")
