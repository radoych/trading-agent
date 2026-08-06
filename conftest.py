"""Makes the project root importable so tests can `import brain` etc.

Without this each test file needs its own sys.path.insert boilerplate, and
`pytest` only works when invoked from the repository root.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
