"""Code shared by the command line runner and the offline tests.

PPA is a personal productivity assistant. The two notebooks of this track are
standalone and import nothing from here. This package exists for the parts that
may stay modular: ``metaharness/run_harness.py``, ``scripts/export_workspace.py``
and the tests.

``paths``             where this track keeps its files
``settings``          environment configuration and secret handling
``world``             the ONLY place that imports the shared world and policy
``memory``            memory provider factory and scoped helpers
``workspace_export``  the world written as files a coding harness can read
``harnesses``         pi, DeepSeek and Hermes adapters behind MemoRizz MetaHarness
``anchors``           rule-derived acceptance checks
``usage``             token normalisation and cost estimates

Nothing here hard-codes a person, a timezone, a thread or an event. Every such
value is read from the loaded world.
"""

__all__ = ["anchors", "harnesses", "memory", "paths", "settings", "usage", "workspace_export",
           "world"]
