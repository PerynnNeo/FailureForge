"""Stream true camera observations, retaining typed numeric evidence on errors."""

from __future__ import annotations

from pathlib import Path
from fractions import Fraction
from time import perf_counter

from .profile import write_json


class EpisodeRecorder:
    def __init__(self, directory: Path, fps: int = 20, physics_layout: dict | None = None):
        import av
        self.directory, self.fps = directory, fps
        self.physics_layout = physics_layout or {}
        self._av = av
        self._videos = []
        self._closed = False
        self.encode_seconds = 0.0
        self.frames, self.states, self.sim_states = [], [], []
        self.qpos, self.qvel = [], []
        self.actions, self.rewards, self.success, self.terminated, self.truncated = [], [], [], [], []
        try:
            for camera in ("main", "wrist"):
                container = av.open(str(directory / f"{camera}.mp4"), mode="w")
                stream = container.add_stream("libx264", rate=fps)
                stream.width = stream.height = 256
                stream.pix_fmt = "yuv420p"
                stream.options = {"crf": "18", "preset": "fast"}
                self._videos.append((container, stream))
        except Exception:
            self.close()
            raise

    def observation(self, pixels: dict, state, sim_state, simulation_time: float, success: bool,
                    qpos=None, qvel=None) -> None:
        import numpy as np
        index = len(self.frames)
        start = perf_counter()
        for name, (container, stream) in zip(("image", "image2"), self._videos, strict=True):
            # Same orientation as LiberoProcessorStep. No spectator camera or pixel corruption.
            image = np.ascontiguousarray(pixels[name][::-1, ::-1])
            if image.dtype != np.uint8 or image.shape != (256, 256, 3):
                raise ValueError(f"Unexpected {name} recording frame: {image.shape}/{image.dtype}")
            frame = self._av.VideoFrame.from_ndarray(image, format="rgb24")
            frame.pts = index
            frame.time_base = Fraction(1, self.fps)
            for packet in stream.encode(frame):
                container.mux(packet)
        self.encode_seconds += perf_counter() - start
        self.frames.append({"frame_index": index, "after_action_count": index,
                            "episode_time_seconds": index / self.fps, "simulation_time_seconds": simulation_time})
        self.states.append(np.asarray(state, dtype=np.float64).copy())
        self.sim_states.append(np.asarray(sim_state, dtype=np.float64).copy())
        self.qpos.append(np.asarray(qpos if qpos is not None else [], dtype=np.float64).copy())
        self.qvel.append(np.asarray(qvel if qvel is not None else [], dtype=np.float64).copy())
        self.success.append(bool(success))

    def action(self, action, reward: float, terminated: bool, truncated: bool) -> None:
        import numpy as np
        self.actions.append(np.asarray(action, dtype=np.float32).copy())
        self.rewards.append(float(reward))
        self.terminated.append(bool(terminated))
        self.truncated.append(bool(truncated))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first_error = None
        start = perf_counter()
        for container, stream in self._videos:
            try:
                for packet in stream.encode():
                    container.mux(packet)
            except Exception as exc:
                first_error = first_error or exc
            finally:
                container.close()
        self.encode_seconds += perf_counter() - start
        if self.frames:
            import numpy as np
            np.savez_compressed(self.directory / "traces.npz",
                timestamps=np.asarray([f["episode_time_seconds"] for f in self.frames], dtype=np.float64),
                simulation_timestamps=np.asarray([f["simulation_time_seconds"] for f in self.frames], dtype=np.float64),
                actions=np.asarray(self.actions, dtype=np.float32).reshape(-1, 7),
                states=np.asarray(self.states, dtype=np.float64), simulator_states=np.asarray(self.sim_states, dtype=np.float64),
                qpos=np.asarray(self.qpos, dtype=np.float64), qvel=np.asarray(self.qvel, dtype=np.float64),
                rewards=np.asarray(self.rewards, dtype=np.float64), success=np.asarray(self.success, dtype=np.bool_),
                terminated=np.asarray(self.terminated, dtype=np.bool_), truncated=np.asarray(self.truncated, dtype=np.bool_))
            write_json(self.directory / "frames.json", {"schema_version": "1.0", "fps": self.fps,
                "orientation": "180-degree rotation of both raw policy cameras, matching environment processor",
                "state_layout": ["eef_x", "eef_y", "eef_z", "eef_axisangle_x", "eef_axisangle_y", "eef_axisangle_z", "gripper_0", "gripper_1"],
                "physics_layout": self.physics_layout,
                "convention": "Frame/state 0 precedes action 0; frame/state i+1 follows action i. Final observation included.",
                "frames": self.frames})
        if first_error is not None:
            raise first_error
