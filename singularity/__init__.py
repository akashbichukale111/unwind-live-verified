"""Singularity-Mesh: a zero-trust operating architecture for an autonomous
agent fleet, layered as Card 5 of the UNWIND instrument.

This package does not replace or wrap `hyperion/` (the immune layer over
Card 2's Gateway) and does not touch `tower/gateway.py`. It is an
independent concern with its own collection, its own two deterministic
decision engines, and its own honesty accounting -- see `DESIGN.md`.
"""
