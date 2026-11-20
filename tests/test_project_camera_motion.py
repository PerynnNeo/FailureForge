import hashlib
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from failureforge.camera_mesh import mesh_surface, stl_triangles
from failureforge.packaging_lift import PackagingLift, run_packaging_lift
from failureforge.project_camera_motion import motion_scene
from failureforge.project_robot import HAND_TARGET, RobotRunRequest, run_robot


ROOT = Path(__file__).resolve().parents[1]
ASCII_STL = b"""solid flag
facet normal 0 0 1
outer loop
vertex 0 0 0
vertex 1 0 0
vertex 0 1 0
endloop
endfacet
endsolid flag
"""
MODEL = b"""<robot name="sideways slide">
 <link name="base"><visual><geometry><box size=".1 .1 .1"/></geometry></visual></link>
 <link name="slide"><visual><origin xyz=".02 0 0" rpy="0 0 1.5707963267948966"/>
 <geometry><mesh filename="package://test/flag.stl" scale=".003 .004 .005"/></geometry></visual></link>
 <joint name="q" type="prismatic"><parent link="base"/><child link="slide"/>
 <origin xyz=".1 0 0" rpy="0 0 1.5707963267948966"/><axis xyz="1 0 0"/>
 <limit lower="0" upper=".2" velocity="1"/></joint></robot>"""


def test_binary_and_ascii_stl_share_the_same_local_coordinates():
    facets = stl_triangles(ASCII_STL)
    header = b"solid but binary".ljust(80, b" ")
    binary = header + struct.pack("<I12fH",1,0,0,1,*facets.ravel(),0)
    assert np.array_equal(stl_triangles(binary), facets)
    vertices, faces, simplified = mesh_surface(facets)
    assert not simplified
    assert np.array_equal(vertices[faces], facets)
    with pytest.raises(ValueError):
        stl_triangles(ASCII_STL.replace(b"endfacet", b"other"))


def test_reference_fingers_reach_both_recorded_tips_without_inventing_a_grasped_object():
    result = run_robot(RobotRunRequest(targets=HAND_TARGET, samples=3))
    scene = motion_scene({"adapter":"robot_motion", "result":result})
    first, end = scene.frame(0), scene.frame(scene.duration_s)
    assert scene.view_labels == ("Workcell overview", "Tool close-up")
    assert sum(obj.kind == "capsule" for obj in scene.objects) == 2
    assert np.allclose(scene.frame(.99).positions, first.positions)
    for index in range(2):
        capsule = scene.objects[index]
        assert np.allclose(capsule.size, [.006,.035])
        end_tip = end.positions[index] + end.rotations[index,:,2]*capsule.size[1]
        if index == 0:
            assert np.allclose(end_tip, result["trajectory"]["tip_xyz_m"][-1])
        assert not np.allclose(end.rotations[index], first.rotations[index])
    assert not np.allclose(first.cameras[0].eye, first.cameras[1].eye)


def test_current_recorded_pose_and_full_visual_origins_apply_to_an_arbitrary_mesh():
    result = run_robot(RobotRunRequest(model_asset_id="u", targets={"q":.10}, samples=3),MODEL)
    run = {"adapter":"robot_motion", "result":result}
    scene = motion_scene(run,MODEL,{"package://test/flag.stl":ASCII_STL})
    index, obj = next((i,item) for i,item in enumerate(scene.objects) if item.kind=="mesh")
    pose = scene.frame(2)
    local = obj.vertices[obj.faces[0]]
    world = pose.positions[index] + local @ pose.rotations[index].T
    assert np.allclose(world, [[.1,.12,0],[.097,.12,0],[.1,.116,0]])
    assert np.allclose(scene.frame(.5).positions[index], scene.frame(0).positions[index])
    assert "Frame guides" in motion_scene(run,MODEL,{}).description
    assert "saved tip positions" in motion_scene(run).description
    with pytest.raises(ValueError,match="differs"):
        motion_scene(run,MODEL+b" ")


def test_manufacturer_meshes_bind_to_both_gripper_links():
    data = (ROOT/"examples/openmanipulator-x/open_manipulator_x.urdf").read_bytes()
    result = run_robot(RobotRunRequest(model_asset_id="omx",targets={"joint1":.35,"gripper_left_joint":.005},
                                      tip_link="end_effector_link"),data)
    pack = ROOT/"src/failureforge/visual_models"/hashlib.sha256(data).hexdigest()
    manifest = json.loads((pack/"manifest.json").read_text())
    meshes = {uri:(pack/entry["filename"]).read_bytes() for uri,entry in manifest["meshes"].items()}
    scene = motion_scene({"adapter":"robot_motion","result":result},data,meshes)
    shapes = [i for i,obj in enumerate(scene.objects) if obj.kind == "mesh"]
    assert len(shapes) == 7
    assert all(np.isfinite(scene.objects[i].vertices).all() for i in shapes)
    assert "Frame guides" not in scene.description
    assert not np.allclose(scene.frame(0).positions[shapes[-1]], scene.frame(scene.duration_s).positions[shapes[-1]])


def test_lift_replays_height_and_switches_force_exactly_at_recorded_sample():
    result = run_packaging_lift(PackagingLift(payload_kg=.5, head_force_n=2))
    scene = motion_scene({"adapter":"packaging_lift","result":result})
    first, before, hold, end = (scene.frame(t) for t in (0,.999,1,2))
    tray = next(i for i,obj in enumerate(scene.objects) if obj.size == (.093,.066,.0045))
    arrow = next(i for i,obj in enumerate(scene.objects) if obj.kind == "mesh")
    assert np.isclose(first.positions[tray,2]+.0045,0)
    assert np.isclose(end.positions[tray,2]+.0045,result["series"]["position_m"][-1])
    assert before.positions[arrow,2] < scene.floor_z
    assert hold.positions[arrow,2] > hold.positions[tray,2]
    assert scene.duration_s == 2
    assert "150 mm" in scene.description and "10 mm" in scene.description
    recorded_peak = f"{1000*result['summary']['max_hold_error_m']:.2f} mm"
    assert "0.5 kg" in scene.description and "2 N" in scene.description and recorded_peak in scene.description
    times = np.array(result["series"]["time_s"])
    errors = np.abs(np.array(result["series"]["position_m"]) - result["fixture"]["target_m"])
    crossing = np.flatnonzero((times >= result["fixture"]["arrival_deadline_s"]) &
                              (errors > result["fixture"]["error_limit_m"]))[0]
    assert scene.frame(times[crossing-1]).colors is None
    np.testing.assert_allclose(scene.frame(times[crossing]).colors[tray], (.86,.18,.52))
    assert "turns pink" in scene.description
    unloaded = run_packaging_lift(PackagingLift(payload_kg=0,head_force_n=0))
    unloaded_scene = motion_scene({"adapter":"packaging_lift","result":unloaded})
    assert not any(obj.kind == "mesh" for obj in unloaded_scene.objects)
    assert "arrow" not in unloaded_scene.description
    assert "turns pink" not in unloaded_scene.description


def test_model_cameras_use_mounted_optical_axes_motion_and_sensor_aspect():
    body = b"""<robot name="instrumented hinge">
      <link name="base"/><link name="arm"/>
      <joint name="yaw" type="revolute"><parent link="base"/><child link="arm"/>
        <origin xyz=".4 0 .2" rpy="0 0 1.5707963267948966"/><axis xyz="0 0 1"/>
        <limit lower="-2" upper="2" velocity="2"/></joint>
      <gazebo reference="arm"><sensor name="wrist_camera" type="camera">
        <pose>.1 0 0 0 0 1.5707963267948966</pose><camera>
        <pose>0 0 0 0 .5235987755982988 0</pose><horizontal_fov>1.5707963267948966</horizontal_fov>
        <image><width>800</width><height>600</height></image></camera>
      </sensor></gazebo>
      <gazebo reference="base"><sensor name="inspection_camera" type="camera">
        <pose>1 2 3 0 0 0</pose><camera><horizontal_fov>.8</horizontal_fov></camera>
      </sensor></gazebo></robot>"""
    def instrumented(model):
        data = run_robot(RobotRunRequest(model_asset_id="test",targets={"yaw":np.pi/2},samples=3),model)
        return motion_scene({"adapter":"robot_motion","result":data},model)
    scene = instrumented(body)
    main, detail = scene.frame(0).cameras
    final_main, final_detail = scene.frame(scene.duration_s).cameras
    assert scene.view_labels == ("inspection_camera (rendered)","wrist_camera (rendered)")
    assert np.allclose(main.eye, [1,2,3]) and np.allclose(main.eye, final_main.eye)
    assert np.allclose(detail.eye, [.4,.1,.2]) and np.allclose(final_detail.eye,[.3,0,.2])
    for camera, direction, up in (
        (detail,[-np.sqrt(.75),0,-.5],[-.5,0,np.sqrt(.75)]),
        (final_detail,[0,-np.sqrt(.75),-.5],[0,-.5,np.sqrt(.75)]),
    ):
        ray = np.subtract(camera.target,camera.eye)
        assert np.allclose(ray/np.linalg.norm(ray),direction)
        assert np.allclose(camera.up,up)
        assert camera.aspect == 4/3
        assert camera.fovy == pytest.approx(np.degrees(2*np.arctan(.75)))
    unsupported = instrumented(body.replace(b'<sensor name="inspection_camera" type="camera">',
                                           b'<sensor name="inspection_camera" type="lidar">')
                                   .replace(b"<width>800</width>",b"<width>0</width>"))
    assert unsupported.view_labels == ("Workcell overview","Tool close-up")
