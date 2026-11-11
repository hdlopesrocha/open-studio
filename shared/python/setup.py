"""Docker build helper that copies the shared Python library into an image."""

from __future__ import annotations

from setuptools import find_packages, setup

setup(
    name="openstudio-common",
    version="1.0.0",
    description="Shared runtime for Open Studio micro-services",
    packages=find_packages(),
    python_requires=">=3.10",
)
