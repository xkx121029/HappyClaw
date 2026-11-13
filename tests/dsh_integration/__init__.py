"""Acceptance scaffold for the DSH integration lines.

The scaffold only *calls* the plugin runtime and the DSH tool bridge; it never
patches production modules. Every check reports one of three states: pass,
fail, or unimplemented, so a missing runtime piece is never mistaken for a
green result.
"""
