"""Server-side SVG of the 24 h curve, for the preview step in Configure. Pure (no HA
import). Neutral greys and a transparent background, so it reads in light and dark themes."""

from __future__ import annotations

from html import escape

W, H = 640, 260
L, R, T, B = 40, 12, 14, 30  # margins


def _x(minute: float) -> float:
    return L + (W - L - R) * minute / 1440


def _y(vol: float, top: float) -> float:
    return T + (H - T - B) * (1 - vol / top)


def render(
    samples: list[float],
    step: int,
    marks: list[dict] | None = None,
    cap_window: list[int] | None = None,
    cap_volume: float | None = None,
    quiet_volume: float | None = None,
    now: int | None = None,
    error: str | None = None,
) -> str:
    top = max([*samples, cap_volume or 0, 10]) + 10
    top = min(100.0, ((int(top) + 9) // 10) * 10)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        'font-family="sans-serif" font-size="11">'
    ]
    grid = "#8888"
    for v in range(0, int(top) + 1, 10 if top <= 50 else 20):
        y = _y(v, top)
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y:.1f}" y2="{y:.1f}" stroke="{grid}" stroke-width="0.5"/>')
        out.append(f'<text x="{L - 6}" y="{y + 4:.1f}" text-anchor="end" fill="#888">{v}%</text>')
    for h in range(0, 25, 3):
        x = _x(h * 60)
        out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{T}" y2="{H - B}" stroke="{grid}" stroke-width="0.5"/>')
        out.append(f'<text x="{x:.1f}" y="{H - B + 16}" text-anchor="middle" fill="#888">{h:02d}:00</text>')
    if cap_window and cap_volume is not None:
        s, e = cap_window
        spans = [(s, e)] if s < e else [(s, 1440), (0, e)] if s != e else [(0, 1440)]
        yc = _y(cap_volume, top)
        for a, b in spans:
            out.append(
                f'<rect x="{_x(a):.1f}" y="{T}" width="{_x(b) - _x(a):.1f}" height="{yc - T:.1f}" '
                'fill="#e5484d" fill-opacity="0.12"/>'
            )
            out.append(
                f'<line x1="{_x(a):.1f}" x2="{_x(b):.1f}" y1="{yc:.1f}" y2="{yc:.1f}" '
                'stroke="#e5484d" stroke-width="1.5" stroke-dasharray="4 3"/>'
            )
        out.append(f'<text x="{_x(spans[0][0]) + 4:.1f}" y="{yc - 4:.1f}" fill="#e5484d">night cap {cap_volume:g}%</text>')
    if quiet_volume is not None:
        yq = _y(quiet_volume, top)
        out.append(
            f'<line x1="{L}" x2="{W - R}" y1="{yq:.1f}" y2="{yq:.1f}" stroke="#8e6fd8" '
            'stroke-width="1" stroke-dasharray="2 3"/>'
        )
        out.append(f'<text x="{W - R - 4}" y="{yq - 4:.1f}" text-anchor="end" fill="#8e6fd8">quiet mode {quiet_volume:g}%</text>')
    for m in marks or []:
        x = _x(m["at"])
        if m.get("ramp"):
            out.append(
                f'<rect x="{_x(m["at"] - m["ramp"] / 2):.1f}" y="{T}" width="{_x(m["ramp"]) - L:.1f}" '
                f'height="{H - T - B}" fill="#03a9f4" fill-opacity="0.06"/>'
            )
        if m.get("name"):
            out.append(f'<text x="{x:.1f}" y="{T + 10}" text-anchor="middle" fill="#888">{escape(m["name"])}</text>')
    if samples:
        pts = " ".join(f"{_x(i * step):.1f},{_y(v, top):.1f}" for i, v in enumerate(samples))
        out.append(f'<polyline points="{pts}" fill="none" stroke="#03a9f4" stroke-width="2.5" stroke-linejoin="round"/>')
    if now is not None and samples:
        v = samples[min(len(samples) - 1, round(now / step))]
        out.append(f'<line x1="{_x(now):.1f}" x2="{_x(now):.1f}" y1="{T}" y2="{H - B}" stroke="#888" stroke-width="1"/>')
        out.append(f'<circle cx="{_x(now):.1f}" cy="{_y(v, top):.1f}" r="4.5" fill="#03a9f4" stroke="#fff" stroke-width="1.5"/>')
        out.append(f'<text x="{_x(now) + 7:.1f}" y="{_y(v, top) - 7:.1f}" fill="#03a9f4">now {v:.0f}%</text>')
    if error:
        out.append(f'<text x="{W / 2}" y="{H / 2}" text-anchor="middle" fill="#e5484d" font-size="14">{escape(error)}</text>')
    out.append("</svg>")
    return "".join(out)
