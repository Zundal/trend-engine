"""Source registry. Add a new source: implement Source, register it here, add a fixture, done.

See docs/ADDING_A_SOURCE.md.
"""

from __future__ import annotations

from .apple import AppleCharts
from .base import Source, SourceError
from .google_news import GoogleNews
from .google_trends import GoogleTrends
from .nate import Nate
from .signal_bz import SignalBz
from .wikipedia import Wikipedia
from .youtube import YouTube

REGISTRY: dict[str, Source] = {
    s.name: s for s in [GoogleTrends(), SignalBz(), Nate(), Wikipedia(), YouTube(), GoogleNews(), AppleCharts()]
}

__all__ = ["REGISTRY", "Source", "SourceError"]
