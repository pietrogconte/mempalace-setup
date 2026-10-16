"""Turn the search form into arguments for viewer/mpbridge.py."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

ALL = ""  # "no filter" value for wing/room selectors


class FilterError(ValueError):
    pass


@dataclass
class SearchRequest:
    query: str
    wing: str = ALL
    room: str = ALL
    start: Optional[date] = None   # inclusive
    end: Optional[date] = None     # inclusive (the UI shows calendar days)
    limit: int = 10

    def since(self) -> Optional[str]:
        return self.start.isoformat() if self.start else None

    def before(self) -> Optional[str]:
        # MemPalace's --before is exclusive; the day after `end` keeps `end` itself in.
        return (self.end + timedelta(days=1)).isoformat() if self.end else None


def build(query: str, wing: str = ALL, room: str = ALL, start=None, end=None, limit: int = 10) -> SearchRequest:
    query = (query or "").strip()
    if not query:
        raise FilterError("empty query")
    if start and end and start > end:
        raise FilterError("start date is after end date")
    if not 1 <= int(limit) <= 100:
        raise FilterError("limit must be between 1 and 100")
    return SearchRequest(query, wing or ALL, room or ALL, start, end, int(limit))


def rooms_for(wing: str, tree_rooms: dict) -> List[str]:
    """Rooms offered in the room selector: those of the chosen wing, or all of them."""
    if wing:
        return list(tree_rooms.get(wing, []))
    return sorted({r for rooms in tree_rooms.values() for r in rooms})


def bridge_argv(python: str, bridge: str, snapshot: str, live_palace: str, req: SearchRequest) -> List[str]:
    argv = [python, "-I", bridge, "--palace", snapshot, "--live-palace", live_palace,
            "--n", str(req.limit), "--query", req.query]
    if req.wing:
        argv += ["--wing", req.wing]
    if req.room:
        argv += ["--room", req.room]
    if req.since():
        argv += ["--since", req.since()]
    if req.before():
        argv += ["--before", req.before()]
    return argv
