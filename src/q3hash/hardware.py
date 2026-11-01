"""Public computed-source hardware assessment; numerical verification stays upstream."""

from ._version import __version__
from .hardware_report import HardwareReport, _prepare


def assess_hardware(source, profile, placements, context):
    """Derive a complete report from computed source evidence and explicit inputs."""
    inputs = _prepare(source, profile, placements, context)
    return HardwareReport._make(inputs, engine_version=__version__, evidence_origin="computed")
