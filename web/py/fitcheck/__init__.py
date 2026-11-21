"""Fit comparison on top of Pyfa's Eos engine.

Two fits are equivalent when every computed stat (price excluded) matches.
The same module is used at build time (to compute puzzle targets with CPython)
and in the browser (Pyodide), so both sides use identical logic.
"""
