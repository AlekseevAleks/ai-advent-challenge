"""Agent memory model: three layers with different purpose and lifetime.

Submodules:

* :mod:`backend.memory.short_term` — the current dialogue (per chat);
* :mod:`backend.memory.working`    — the state of the current task (per chat);
* :mod:`backend.memory.long_term`  — durable facts about the user (global);
* :mod:`backend.memory.extractor`  — proposes what could be stored;
* :mod:`backend.memory.manager`    — decides what is actually stored.

Import the concrete modules directly to avoid import cycles with the
database layer, which depends on :mod:`backend.memory.models`.
"""

from __future__ import annotations
