"""Optional upstream adapters. ContextForge never depends on any of them being present.

Each adapter knows one upstream's conventions: which request headers it understands (so
ContextForge passes them through), and how it reports the model actually used and the
cost. Adding an upstream kind means adding one file and one registry entry.
"""
