from datetime import datetime
from typing import NamedTuple
from .i18n import tr


class Bar(NamedTuple):
    phase: str
    left_pct: float
    width_pct: float


class Marker(NamedTuple):
    left_pct: float
    icon: str
    title: str
    count: int = 1


def _t(ts: str) -> datetime:
    return datetime.fromisoformat(ts[:16])


def _pct(moment: datetime, start: datetime, end: datetime) -> float:
    return round((moment - start) / (end - start) * 100, 3)


def layout_bars(phases: list[tuple[str, str]], start: datetime, end: datetime,
                ausgezogen: str | None) -> list[Bar]:
    """One bar per phase segment, clipped to [start, end]; the last phase runs to ausgezogen or end."""
    stop = min(_t(ausgezogen), end) if ausgezogen else end
    bars = []
    for i, (phase, ab) in enumerate(phases):
        seg_start = max(_t(ab), start)
        seg_end = min(_t(phases[i + 1][1]) if i + 1 < len(phases) else stop, stop)
        if seg_end > seg_start:
            bars.append(Bar(phase, _pct(seg_start, start, end), _pct(seg_end, start, end) - _pct(seg_start, start, end)))
    return bars


def layout_markers(items: list[tuple[str, str, str]], start: datetime, end: datetime) -> list[Marker]:
    return [Marker(_pct(_t(ts), start, end), icon, title) for ts, icon, title in items
            if start <= _t(ts) <= end]


def cluster_markers(markers: list[Marker], gap_pct: float = 3.0) -> list[Marker]:
    """Merge neighbouring markers of the same icon so a week of waterings doesn't pile up."""
    out: list[Marker] = []
    for icon in dict.fromkeys(m.icon for m in markers):
        group: list[Marker] = []
        for m in sorted((m for m in markers if m.icon == icon), key=lambda m: m.left_pct):
            if group and m.left_pct - group[-1].left_pct >= gap_pct:
                out.append(_merge(group))
                group = []
            group.append(m)
        out.append(_merge(group))
    return sorted(out, key=lambda m: m.left_pct)


def _merge(group: list[Marker]) -> Marker:
    if len(group) == 1:
        return group[0]
    return Marker(group[0].left_pct, group[0].icon, tr("{n} Einträge", n=len(group)), len(group))
