"""Offline rule-extraction pipeline.

This package is NOT imported by the live FastAPI app. It runs from the command
line over exported SME feedback files, produces candidate rules for human
review, and never writes to the running system on its own.
"""
