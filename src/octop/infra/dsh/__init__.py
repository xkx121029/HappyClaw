"""DSH integration seams for Octop.

Each subpackage owns one seam (session, skills, llm). Subpackages do not change
existing call paths by themselves; callers opt in explicitly.
"""
