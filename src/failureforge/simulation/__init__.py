"""Optional robotics runtime. Importing this package never imports CUDA or LIBERO."""

from .libero import LiberoRunner, SimulationError
from .profile import doctor
from .qualification import approve_scene_review, qualify

__all__ = ["LiberoRunner", "SimulationError", "doctor", "qualify", "approve_scene_review"]
