"""
Force a platform-tagged, Python-version-agnostic wheel.  PYPLANTUML_PLAT_TAG
lets CI override the platform tag with the right manylinux / musllinux
baseline for the build container.
"""
import os

from setuptools import setup

try:
    from setuptools.command.bdist_wheel import bdist_wheel as _BDistWheel
except ImportError:
    from wheel.bdist_wheel import bdist_wheel as _BDistWheel  # type: ignore


class BDistWheelPlatform(_BDistWheel):
    def finalize_options(self):
        super().finalize_options()
        self.root_is_pure = False

    def get_tag(self):
        _, _, plat = super().get_tag()
        plat = os.environ.get("PYPLANTUML_PLAT_TAG", plat)
        return "py3", "none", plat


setup(cmdclass={"bdist_wheel": BDistWheelPlatform})
