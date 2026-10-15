"""mempalace-sync: scheduled, idempotent capture into a MemPalace palace.

Stdlib only (plus ``tomli`` on Python < 3.11). MemPalace itself is never
imported: it is always driven through its CLI, so this package can be tested
without MemPalace installed.
"""

__version__ = "1.0.0"
