"""Shared visibility policy for customer entry points in immutable editions."""
from __future__ import annotations

# Online and Offline are separate packages. Retain the former activation flow
# for compatibility, but do not offer a mode switch or license exchange in UI.
OFFLINE_ACTIVATION_ENABLED = False
