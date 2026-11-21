import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="souvenirs-data-"))
os.environ.setdefault("ADMIN_CODE", "test")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
