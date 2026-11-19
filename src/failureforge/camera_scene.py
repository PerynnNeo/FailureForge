"""Presentation geometry in metres. Each camera samples the same recorded instant."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np


@dataclass
class Object3D:
    kind: str
    size: tuple
    color: tuple
    vertices: np.ndarray | None = None
    faces: np.ndarray | None = None


@dataclass
class Camera:
    eye: tuple
    target: tuple
    up: tuple = (0., 0., 1.)
    fovy: float = 40.
    aspect: float | None = None


@dataclass
class Frame:
    positions: np.ndarray
    rotations: np.ndarray | None
    cameras: tuple[Camera, Camera]
    colors: np.ndarray | None = None


@dataclass
class Scene:
    objects: Sequence[Object3D]
    duration_s: float
    view_labels: tuple[str, str]
    description: str
    frame: Callable[[float], Frame]
    floor_z: float | None = None
