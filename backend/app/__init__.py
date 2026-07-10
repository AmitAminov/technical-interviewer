"""Technical Interviewer backend application package."""
from __future__ import annotations

import os

# Defensive: must be set before any transformers/sentence_transformers import.
os.environ.setdefault("USE_TF", "0")
