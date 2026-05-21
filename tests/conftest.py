import sys
from pathlib import Path

# Allow tests to import from the project root (agent, connectors, etc.)
sys.path.insert(0, str(Path(__file__).parent.parent))
