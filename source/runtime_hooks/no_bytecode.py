"""Keep the signed macOS app bundle immutable while it is running."""

import sys

sys.dont_write_bytecode = True
