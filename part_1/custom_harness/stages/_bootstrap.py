from pathlib import Path
import sys

APPBOOK = Path(__file__).resolve().parents[1] / "appbook"
if str(APPBOOK) not in sys.path:
    sys.path.insert(0, str(APPBOOK))
