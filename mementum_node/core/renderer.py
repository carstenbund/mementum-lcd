"""Evaluated scene state -> composited RGBA frame.

The reference renderer. On the ESP32 this layer is ``render_lvgl.c``: it pushes
evaluated properties into LVGL/ThorVG objects instead of rasterising them here,
but it consumes exactly the same evaluated state and it writes into exactly the
same kind of frame. Below it is the sink; above it is nothing but pure
evaluation.

The design canvas is not the physical resolution (proposal §6). A node whose
display differs from ``scene.width x scene.height`` maps the canvas onto it with
the scene's ``fit`` policy -- which is what the virtual video wall makes
checkable by eye across a heterogeneous set.
"""

from __future__ import annotations

from .font5x7 import ADVANCE, CELL_H, CELL_W, resolve_font
from .framebuffer import Frame
from .geometry import flatten_path, trim_polyline
from .raster import fill_polygons, stroke_polyline
from .scene import Scene, SceneObject, Transform, parse_color

__all__ = ["Viewport", "draw_text", "render_scene"]

_BACKGROUND = (0, 0, 0, 255)


class Viewport:
    """Maps design-canvas coordinates onto a node's display (``fit`` policy)."""

    __slots__ = ("scale", "offset_x", "offset_y", "width", "height")

    def __init__(self, scene_w: int, scene_h: int, out_w: int, out_h: int, fit: str = "contain"):
        self.width, self.height = out_w, out_h
        if fit == "fill":
            self.scale = 1.0
            self.offset_x = self.offset_y = 0.0
            if (scene_w, scene_h) != (out_w, out_h):
                # Non-uniform scaling is deliberately not supported in v1.
                self.scale = min(out_w / scene_w, out_h / scene_h)
        elif fit in ("contain", "cover"):
            sx, sy = out_w / scene_w, out_h / scene_h
            self.scale = min(sx, sy) if fit == "contain" else max(sx, sy)
        else:
            raise ValueError(f"unsupported fit policy: {fit!r}")
        if fit != "fill":
            self.offset_x = (out_w - scene_w * self.scale) / 2.0
            self.offset_y = (out_h - scene_h * self.scale) / 2.0

    def point(self, x: float, y: float) -> tuple[float, float]:
        return (self.offset_x + x * self.scale, self.offset_y + y * self.scale)

    def length(self, v: float) -> float:
        return v * self.scale


def _object_transform(obj: SceneObject, viewport: Viewport):
    tf: Transform = obj.transform

    def to_device(x: float, y: float) -> tuple[float, float]:
        return viewport.point(x * tf.scale + tf.tx, y * tf.scale + tf.ty)

    return to_device, tf.scale


def _render_rect(frame: Frame, obj: SceneObject, viewport: Viewport, alpha: float) -> None:
    to_device, _ = _object_transform(obj, viewport)
    x, y = float(obj.props["x"]), float(obj.props["y"])
    w, h = float(obj.props["w"]), float(obj.props["h"])
    rgb = parse_color(obj.props.get("fill"))
    p0, p1 = to_device(x, y), to_device(x + w, y + h)
    if alpha >= 1.0 and p0[0] == int(p0[0]) and p0[1] == int(p0[1]) and p1[0] == int(p1[0]) and p1[1] == int(p1[1]):
        frame.fill_rect(int(p0[0]), int(p0[1]), int(p1[0] - p0[0]), int(p1[1] - p0[1]), rgb + (255,))
        return
    poly = [p0, (p1[0], p0[1]), p1, (p0[0], p1[1])]
    fill_polygons(frame, [poly], rgb, alpha)


def _render_path(frame: Frame, obj: SceneObject, viewport: Viewport, alpha: float) -> None:
    to_device, tf_scale = _object_transform(obj, viewport)
    progress = min(1.0, max(0.0, obj.progress))
    if progress <= 0.0:
        return
    width = viewport.length(float(obj.props.get("stroke_width", 1.0)) * tf_scale)
    rgb = parse_color(obj.props.get("stroke"))
    polys = []
    for subpath in flatten_path(obj.props["d"]):
        drawn = trim_polyline(subpath, progress)
        if len(drawn) < 2:
            continue
        polys.extend(stroke_polyline([to_device(x, y) for x, y in drawn], width))
    fill_polygons(frame, polys, rgb, alpha)


def _text_polygons(font, text: str, x: float, y: float, unit: float, to_device):
    polys = []
    for index, col, row in font.cells(text):
        cx = x + (index * ADVANCE + col) * unit
        cy = y + row * unit
        p0 = to_device(cx, cy)
        p1 = to_device(cx + unit, cy + unit)
        polys.append([p0, (p1[0], p0[1]), p1, (p0[0], p1[1])])
    return polys


def _render_text(frame: Frame, obj: SceneObject, viewport: Viewport, alpha: float) -> None:
    font = resolve_font(obj.props["font_id"])
    text = str(obj.props.get("content", ""))
    if not text:
        return
    to_device, tf_scale = _object_transform(obj, viewport)
    fill_polygons(
        frame,
        _text_polygons(
            font,
            text,
            float(obj.props["x"]),
            float(obj.props["y"]),
            font.scale * tf_scale,
            to_device,
        ),
        parse_color(obj.props.get("color")),
        alpha,
    )


def draw_text(
    frame: Frame,
    text: str,
    x: float,
    y: float,
    size: int = 7,
    rgb: tuple[int, int, int] = (255, 255, 255),
    alpha: float = 1.0,
) -> None:
    """Draw a label straight into a frame, in device pixels.

    Used for annotating captures and video-wall tiles. Not part of scene
    rendering: a scene's text is a scene object, evaluated like everything
    else."""
    font = resolve_font(f"label-{int(size)}")
    fill_polygons(
        frame,
        _text_polygons(font, text, x, y, font.scale, lambda px, py: (px, py)),
        rgb,
        alpha,
    )


_RENDERERS = {"rect": _render_rect, "path": _render_path, "text": _render_text}


def render_scene(
    state: Scene,
    width: int | None = None,
    height: int | None = None,
    frame: Frame | None = None,
) -> Frame:
    """Composite an *already evaluated* scene into an RGBA frame.

    ``state`` must come from :func:`~.evaluator.evaluate`; this function does no
    time arithmetic of its own, which is what keeps the render path free of the
    accumulators §10 forbids.
    """
    out_w = width if width is not None else state.width
    out_h = height if height is not None else state.height
    if frame is None:
        frame = Frame.filled(out_w, out_h, _BACKGROUND)
    else:
        frame.fill(_BACKGROUND)
    viewport = Viewport(state.width, state.height, out_w, out_h, state.fit)

    for layer in state.ordered_layers:
        for obj in layer.objects:
            if not obj.visible:
                continue
            alpha = min(1.0, max(0.0, obj.opacity))
            if alpha <= 0.0:
                continue
            renderer = _RENDERERS.get(obj.type)
            if renderer is None:
                raise ValueError(f"no renderer for object type {obj.type!r}")
            renderer(frame, obj, viewport, alpha)
    return frame
