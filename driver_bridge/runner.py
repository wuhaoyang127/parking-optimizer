"""Stable entry point for the reviewed online research adapter."""
from pathlib import Path
import runpy

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).with_name('runner_v2.py')), run_name='__main__')
