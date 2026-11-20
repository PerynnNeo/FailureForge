"""Headless two-camera rendering of a solved scene. No physics is re-integrated."""
from __future__ import annotations

import math
import os
import subprocess
from contextlib import ExitStack

import numpy as np

WIDTH, HEIGHT, FPS = 640, 360, 24

VERTEX = """#version 330
layout(location=0) in vec3 p;
layout(location=1) in vec3 n;
uniform mat4 viewProjection, model, lightProjection;
out vec3 point, normal;
out vec4 shadowCoord;
void main() {
    point = (model * vec4(p,1)).xyz;
    normal = mat3(model) * n;
    shadowCoord = lightProjection * vec4(point,1);
    gl_Position = viewProjection * vec4(point,1);
}"""

FRAGMENT = """#version 330
in vec3 point, normal;
in vec4 shadowCoord;
uniform vec3 albedo, eye;
uniform sampler2DShadow shadowMap;
uniform float grid;
uniform int mode;
out vec4 pixel;
void main() {
    vec3 uv = shadowCoord.xyz*0.5+0.5;
    float visible = 1.0;
    if (all(greaterThan(uv,vec3(0))) && all(lessThan(uv,vec3(1)))) {
        visible = texture(shadowMap,vec3(uv.xy,uv.z-0.0008));
    }
    if (mode > 0) {
        vec2 cell = point.xy / grid;
        vec2 dist = abs(fract(cell+0.5)-0.5) / max(fwidth(cell),vec2(0.001));
        float line = 1.0-min(min(dist.x,dist.y),1.0);
        float fade = 1.0-smoothstep(0.1,0.65,max(fwidth(cell.x),fwidth(cell.y)));
        vec3 surface = mix(vec3(0.73,0.77,0.79), vec3(0.60,0.65,0.67),line*fade);
        pixel=vec4(surface*mix(0.76,1.0,visible),1);
        return;
    }
    vec3 N=normalize(normal), V=normalize(eye-point);
    if (dot(N,V)<0) N=-N;
    vec3 L=normalize(vec3(-0.36,-0.47,0.81));
    float diffuse=0.44+0.54*visible*max(dot(N,L),0.0)+0.16*max(dot(N,normalize(vec3(0.8,0.2,0.4))),0.0);
    float highlight=0.22*visible*pow(max(dot(N,normalize(V+L)),0.0),34.0);
    pixel=vec4(clamp(pow(albedo,vec3(0.84))*diffuse + highlight,0.0,1.0),1);
}"""


def _flat(triangles):
    a, b, c = triangles.transpose(1, 0, 2)
    normals = np.cross(b-a, c-a)
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-30)
    return triangles.reshape(-1, 3), np.repeat(normals, 3, axis=0)


def _surface(obj):
    size = np.array(obj.size, dtype=float)
    if obj.kind == "mesh":
        triangles = np.asarray(obj.vertices, dtype=float)[np.asarray(obj.faces, dtype=int)]
        return _flat(triangles)
    if not np.isfinite(size).all() or np.any(size < 0):
        raise ValueError("Invalid primitive dimensions")
    if obj.kind == "box":
        points = np.array([[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],
                           [-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]]) * size
        quads = np.array([[3,2,1,0],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]])
        return _flat(points[quads[:, [0,1,2,0,2,3]]].reshape(-1,3,3))
    if obj.kind not in ("sphere", "cylinder", "capsule"):
        raise ValueError(f"Unsupported presentation geometry: {obj.kind}")
    angles = np.linspace(0, 2*np.pi, 33)
    c, s = np.cos(angles), np.sin(angles)
    radius = size[0]
    h = size[1] if obj.kind != "sphere" else 0.
    if obj.kind == "cylinder":
        rings = [(0,-h,0,-1),(radius,-h,0,-1),(radius,-h,1,0),
                 (radius,h,1,0),(radius,h,0,1),(0,h,0,1)]
    else:
        rings = []
        for offset, latitudes in ((-h,np.linspace(-np.pi/2,0,9)), (h,np.linspace(0,np.pi/2,9))):
            rings.extend((radius*np.cos(a), offset+radius*np.sin(a),np.cos(a),np.sin(a)) for a in latitudes)
    def ring(rad, z):
        return np.column_stack((rad*c,rad*s,np.full_like(c,z)))
    positions = np.array([ring(r,z) for r,z,_,_ in rings])
    normals = np.array([ring(nr,nz) for _,_,nr,nz in rings])
    def triangles(a):
        return np.stack([a[:-1,:-1],a[:-1,1:],a[1:,1:],a[:-1,:-1],a[1:,1:],a[1:,:-1]],axis=2).reshape(-1,3)
    return triangles(positions), triangles(normals)


def _camera(camera):
    eye, target = np.asarray(camera.eye), np.asarray(camera.target)
    forward = target-eye
    distance = np.linalg.norm(forward)
    if not np.isfinite(distance) or distance <= 0:
        raise ValueError("Camera needs a distinct, finite target")
    forward = forward / distance
    right = np.cross(forward, camera.up)
    if np.linalg.norm(right) < 1e-8:
        raise ValueError("Camera needs a distinct target and an orthogonal up direction")
    right /= np.linalg.norm(right)
    view = np.eye(4)
    view[:3,:3] = [right, np.cross(right,forward), -forward]
    view[:3,3] = -view[:3,:3] @ eye
    near, far = distance/1000, distance*100
    f = 1/math.tan(math.radians(camera.fovy)/2)
    aspect = camera.aspect or WIDTH/HEIGHT
    projection = np.array([[f/aspect,0,0,0], [0,f,0,0],
                           [0,0,(far+near)/(near-far),2*far*near/(near-far)],[0,0,-1,0]])
    return projection @ view


class Renderer:
    def __init__(self, scene):
        from OpenGL import GL as gl
        from OpenGL.GL.shaders import compileProgram, compileShader
        self.gl = gl
        # EGL creates a surfaceless context; use our own color and depth attachments.
        self.fbo = gl.glGenFramebuffers(1)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.fbo)
        for attachment, storage in ((gl.GL_COLOR_ATTACHMENT0,gl.GL_RGB8),(gl.GL_DEPTH_ATTACHMENT,gl.GL_DEPTH_COMPONENT24)):
            buffer = gl.glGenRenderbuffers(1)
            gl.glBindRenderbuffer(gl.GL_RENDERBUFFER,buffer)
            gl.glRenderbufferStorage(gl.GL_RENDERBUFFER,storage,WIDTH,HEIGHT)
            gl.glFramebufferRenderbuffer(gl.GL_FRAMEBUFFER,attachment,gl.GL_RENDERBUFFER,buffer)
        if gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER) != gl.GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError("Unable to allocate camera framebuffer")
        self.shadow_fbo = gl.glGenFramebuffers(1)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER,self.shadow_fbo)
        self.shadow = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D,self.shadow)
        gl.glTexImage2D(gl.GL_TEXTURE_2D,0,gl.GL_DEPTH_COMPONENT24,1024,1024,0,gl.GL_DEPTH_COMPONENT,gl.GL_FLOAT,None)
        for flag in (gl.GL_TEXTURE_MIN_FILTER,gl.GL_TEXTURE_MAG_FILTER):
            gl.glTexParameteri(gl.GL_TEXTURE_2D,flag,gl.GL_LINEAR)
        for flag in (gl.GL_TEXTURE_WRAP_S,gl.GL_TEXTURE_WRAP_T):
            gl.glTexParameteri(gl.GL_TEXTURE_2D,flag,gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,gl.GL_TEXTURE_COMPARE_MODE,gl.GL_COMPARE_REF_TO_TEXTURE)
        gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER,gl.GL_DEPTH_ATTACHMENT,gl.GL_TEXTURE_2D,self.shadow,0)
        gl.glDrawBuffer(gl.GL_NONE)
        gl.glReadBuffer(gl.GL_NONE)
        if gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER) != gl.GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError("Unable to allocate shadow framebuffer")
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER,self.fbo)
        program = compileProgram(compileShader(VERTEX,gl.GL_VERTEX_SHADER),compileShader(FRAGMENT,gl.GL_FRAGMENT_SHADER))
        gl.glUseProgram(program)
        self.uniform = {key: gl.glGetUniformLocation(program,key) for key in
                        ("viewProjection","model","mode","lightProjection","grid","albedo","eye")}
        first = scene.frame(0)
        self.scale = max(np.linalg.norm(np.subtract(first.cameras[0].eye,first.cameras[0].target)), 1e-8)
        self.floor = scene.floor_z
        vertices, bounds, self.ranges, start = [], [], [], 0
        for obj in scene.objects:
            points, normals = _surface(obj)
            bounds.append([points.min(axis=0),points.max(axis=0)])
            vertices.append(np.column_stack((points,normals)))
            self.ranges.append((start,len(points)))
            start += len(points)
        bounds = np.asarray(bounds)
        self.centers = bounds.mean(axis=1)
        self.half_extents = (bounds[:,1]-bounds[:,0])/2
        self.floor_start = start
        floor_center = first.cameras[0].target
        floor_xy = np.array([[-1,-1],[1,-1],[1,1],[-1,-1],[1,1],[-1,1]])*self.scale*75+floor_center[:2]
        vertices.append(np.column_stack((floor_xy,np.full(6,self.floor or 0),np.tile([0,0,1],(6,1)))))
        data = np.ascontiguousarray(np.vstack(vertices),dtype=np.float32)
        if not np.isfinite(data).all():
            raise ValueError("Camera geometry contains nonfinite coordinates")
        import ctypes
        gl.glBindVertexArray(gl.glGenVertexArrays(1))
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER,gl.glGenBuffers(1))
        gl.glBufferData(gl.GL_ARRAY_BUFFER,data.nbytes,data,gl.GL_STATIC_DRAW)
        for attribute in (0,1):
            gl.glEnableVertexAttribArray(attribute)
            gl.glVertexAttribPointer(attribute,3,gl.GL_FLOAT,False,24,ctypes.c_void_p(12*attribute))
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glViewport(0,0,WIDTH,HEIGHT)
        gl.glClearColor(.76,.80,.82,1)
        gl.glUniform1f(self.uniform["grid"],self.scale/12)
        self.colors = np.array([obj.color[:3] for obj in scene.objects])

    def prepare(self, frame):
        gl, u = self.gl, self.uniform
        transforms = np.tile(np.eye(4,dtype=np.float32),(len(self.ranges),1,1))
        transforms[:,:3,3] = frame.positions
        if frame.rotations is not None:
            transforms[:,:3,:3] = frame.rotations
        self.transforms = transforms
        self.frame = frame
        # Fit directional shadows to the transformed model bounds, independent of the camera mount.
        toward_light = np.array([-.36,-.47,.81])
        toward_light /= np.linalg.norm(toward_light)
        right = np.cross([0,0,1],toward_light)
        right /= np.linalg.norm(right)
        axes = np.array([right,np.cross(toward_light,right),-toward_light])
        rotations = transforms[:,:3,:3]
        centers = (np.einsum("nij,nj->ni",rotations,self.centers)+transforms[:,:3,3]) @ axes.T
        radii = np.einsum("nij,nj->ni",np.abs(axes @ rotations), self.half_extents)
        low, high = (centers-radii).min(axis=0), (centers+radii).max(axis=0)
        span = np.maximum(high-low,self.scale*.001)
        light = np.eye(4)
        light[:3,:3] = axes*(1.8/span)[:,None]
        light[:3,3] = -.9*(high+low)/span
        gl.glUniformMatrix4fv(u["lightProjection"],1,True,np.asarray(light,dtype=np.float32))
        gl.glUniformMatrix4fv(u["viewProjection"],1,True,np.asarray(light,dtype=np.float32))
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER,self.shadow_fbo)
        gl.glBindTexture(gl.GL_TEXTURE_2D,0)
        gl.glViewport(0,0,1024,1024)
        gl.glClear(gl.GL_DEPTH_BUFFER_BIT)
        gl.glEnable(gl.GL_POLYGON_OFFSET_FILL)
        gl.glPolygonOffset(2,2)
        for transform,(start,count) in zip(transforms,self.ranges,strict=True):
            gl.glUniformMatrix4fv(u["model"],1,True,transform)
            gl.glDrawArrays(gl.GL_TRIANGLES,start,count)
        gl.glDisable(gl.GL_POLYGON_OFFSET_FILL)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER,self.fbo)
        gl.glBindTexture(gl.GL_TEXTURE_2D,self.shadow)

    def image(self, frame, view):
        gl, u, cam = self.gl, self.uniform, frame.cameras[view]
        if getattr(self,"frame",None) is not frame:
            self.prepare(frame)
        aspect = cam.aspect or WIDTH/HEIGHT
        width, height = min(WIDTH, max(1,round(HEIGHT*aspect))), min(HEIGHT, max(1,round(WIDTH/aspect)))
        if width < WIDTH or height < HEIGHT:
            gl.glClearColor(.09,.12,.14,1)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)
            gl.glEnable(gl.GL_SCISSOR_TEST)
            gl.glScissor((WIDTH-width)//2,(HEIGHT-height)//2,width,height)
        gl.glViewport((WIDTH-width)//2,(HEIGHT-height)//2,width,height)
        gl.glClearColor(.76,.80,.82,1)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        gl.glDisable(gl.GL_SCISSOR_TEST)
        gl.glUniformMatrix4fv(u["viewProjection"],1,True,np.asarray(_camera(cam),dtype=np.float32))
        gl.glUniform3fv(u["eye"],1,cam.eye)
        colors = self.colors if frame.colors is None else frame.colors
        if self.floor is not None:
            gl.glUniform1i(u["mode"],1)
            gl.glUniformMatrix4fv(u["model"],1,True,np.eye(4,dtype=np.float32))
            gl.glDrawArrays(gl.GL_TRIANGLES,self.floor_start,6)
        gl.glUniform1i(u["mode"],0)
        for transform,color,(start,count) in zip(self.transforms,colors,self.ranges,strict=True):
            gl.glUniformMatrix4fv(u["model"],1,True,transform)
            gl.glUniform3fv(u["albedo"],1,color[:3])
            gl.glDrawArrays(gl.GL_TRIANGLES,start,count)
        pixels = gl.glReadPixels(0,0,WIDTH,HEIGHT,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)
        return np.frombuffer(pixels,dtype=np.uint8).reshape(HEIGHT,WIDTH,3)[::-1].tobytes()


def render(scene, directory):
    import mujoco
    if not 0 < scene.duration_s < 1e8 or not 0 < len(scene.objects) <= 4096:
        raise ValueError("Camera scene requires finite geometry and a positive duration")
    duration = min(12., max(.5,scene.duration_s))
    count = max(2,round(FPS*duration))
    with ExitStack() as stack:
        context = mujoco.GLContext(WIDTH,HEIGHT)
        context.make_current()
        stack.callback(context.free)
        renderer = Renderer(scene)
        writers = []
        for name in ("main","detail"):
            command = ["ffmpeg","-nostdin","-v","error","-y","-f","rawvideo","-pix_fmt","rgb24",
                       "-s",f"{WIDTH}x{HEIGHT}","-r",str(FPS),"-i","pipe:0","-an","-c:v","libx264",
                       "-threads","2","-preset","veryfast","-crf","19","-pix_fmt","yuv420p",
                       "-movflags","+faststart",os.fspath(directory/f"{name}.mp4")]
            writer = stack.enter_context(subprocess.Popen(command,stdin=subprocess.PIPE))
            stack.callback(writer.kill)
            writers.append(writer)
        for i in range(count):
            frame = scene.frame(scene.duration_s*i/(count-1))
            for view, writer in enumerate(writers):
                writer.stdin.write(renderer.image(frame,view))
        for writer in writers:
            writer.stdin.close()
            if writer.wait(timeout=20):
                raise RuntimeError("MP4 encoding did not complete")
    description = scene.description
    if abs(duration-scene.duration_s) > .05:
        description += f" The {duration:g}-second video covers {scene.duration_s:g} seconds of the source timeline."
    return {"description":description,"duration_s":count/FPS,"frame_count":count,"labels":list(scene.view_labels)}
