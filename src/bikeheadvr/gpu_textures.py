from __future__ import annotations

import ctypes
from dataclasses import dataclass

import openvr
import pyglet
from pyglet import gl

from .overlay_ui import OverlayTexture


@dataclass
class GpuTexture:
    texture_id: int
    width_px: int
    height_px: int
    vr_texture: openvr.Texture_t


class OpenGLTextureManager:
    def __init__(self) -> None:
        config = gl.Config(double_buffer=False)
        self._window = pyglet.window.Window(width=1, height=1, visible=False, config=config)
        self._window.switch_to()
        self._textures: dict[int, GpuTexture] = {}

    def create_overlay_texture(self, overlay_handle: int, texture: OverlayTexture) -> None:
        self._window.switch_to()
        texture_id = gl.GLuint()
        gl.glGenTextures(1, ctypes.byref(texture_id))
        gl.glBindTexture(gl.GL_TEXTURE_2D, texture_id.value)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
        self._tex_image_2d(texture)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)

        vr_texture = openvr.Texture_t()
        vr_texture.handle = ctypes.c_void_p(texture_id.value)
        vr_texture.eType = openvr.TextureType_OpenGL
        vr_texture.eColorSpace = openvr.ColorSpace_Gamma
        self._textures[overlay_handle] = GpuTexture(
            texture_id=texture_id.value,
            width_px=texture.width_px,
            height_px=texture.height_px,
            vr_texture=vr_texture,
        )

    def update_overlay_texture(self, overlay_handle: int, texture: OverlayTexture) -> None:
        gpu_texture = self._textures[overlay_handle]
        self._window.switch_to()
        gl.glBindTexture(gl.GL_TEXTURE_2D, gpu_texture.texture_id)
        buffer = ctypes.create_string_buffer(texture.rgba_bytes, len(texture.rgba_bytes))
        gl.glTexSubImage2D(
            gl.GL_TEXTURE_2D,
            0,
            0,
            0,
            texture.width_px,
            texture.height_px,
            gl.GL_RGBA,
            gl.GL_UNSIGNED_BYTE,
            ctypes.cast(buffer, ctypes.c_void_p),
        )
        gl.glFinish()
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        gpu_texture.width_px = texture.width_px
        gpu_texture.height_px = texture.height_px

    def get_vr_texture(self, overlay_handle: int) -> openvr.Texture_t:
        return self._textures[overlay_handle].vr_texture

    def destroy(self) -> None:
        self._window.switch_to()
        for gpu_texture in self._textures.values():
            texture_id = gl.GLuint(gpu_texture.texture_id)
            gl.glDeleteTextures(1, ctypes.byref(texture_id))
        self._textures.clear()
        self._window.close()

    def _tex_image_2d(self, texture: OverlayTexture) -> None:
        buffer = ctypes.create_string_buffer(texture.rgba_bytes, len(texture.rgba_bytes))
        gl.glTexImage2D(
            gl.GL_TEXTURE_2D,
            0,
            gl.GL_RGBA8,
            texture.width_px,
            texture.height_px,
            0,
            gl.GL_RGBA,
            gl.GL_UNSIGNED_BYTE,
            ctypes.cast(buffer, ctypes.c_void_p),
        )
