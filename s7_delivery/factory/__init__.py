"""The S7 governed delivery factory — engine behind the Control Centre surface.

No HTTP in this package: `apps/control/server.py` is a thin translation layer
over it, the same split `apps/console` has with `s7_delivery/pipeline.py`.
Every gate condition and role check lives here so no surface can route
around it.
"""
