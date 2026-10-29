"""Ephemeral E2E sim nodes for xezim: launch, run, pause or kill.

Cheapest possible shape by construction: hourly on-demand nodes with no
backup, encryption, BitNinja, reserved IP, snapshot, or volume code paths.
Pause uses ``power_off`` (compute billing stops, disk persists); kill uses
DELETE (everything stops).
"""

__version__ = "0.1.0"
