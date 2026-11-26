"""Shared picture-gap policy for script review and storyboard assembly.

A sub-frame rounding remainder is not a missing documentary shot. It cannot be
represented as a stand-alone 30 fps picture interval, and must not cause one
component to demand footage that another component deliberately excludes.

Actual gaps of one frame or more are NOT waived by this rule.
"""

OUTPUT_FPS = 30


def is_subframe_gap(start_ms: int, end_ms: int) -> bool:
    """True only for a positive non-renderable gap shorter than one output frame.

    Use duration, not the phase of a rounded frame boundary: otherwise a 5 ms
    discrepancy would be treated differently depending on where it occurred in
    the minute, and could reintroduce sporadic blocked builds.
    """
    span = end_ms - start_ms
    return 0 < span < (1000.0 / OUTPUT_FPS)
