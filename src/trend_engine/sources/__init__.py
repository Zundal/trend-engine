"""Source registry. Add a new source: implement Source, register it here, add a fixture, done.

See docs/ADDING_A_SOURCE.md.
"""

from __future__ import annotations

from .apple import AppleCharts
from .base import Source, SourceError
from .google_news import GoogleNews
from .google_trends import GoogleTrends
from .japan import BillboardJapan, Hatena, LivedoorTrend, NicoVideo, YahooTopics
from .local import ETtoday, Kenh14, Pixiv, Reddit, Steam
from .melon import Melon
from .nate import Nate
from .netflix import Netflix
from .signal_bz import SignalBz
from .wikipedia import Wikipedia
from .world import (BBCNews, BillboardUS, DanTri, GnnTW, KKBoxTW, OfficialCharts, ThanhNien, TuoiTre, VnExpress,
                    YahooTrending, YahooTW, YahooTWSearch, YahooUS)
from .xtrends import GetDayTrends, Trends24, YahooRealtimeJP
from .youtube import YouTube
from .zum import ZumIssue

REGISTRY: dict[str, Source] = {
    s.name: s for s in [GoogleTrends(), SignalBz(), Nate(), Wikipedia(), YouTube(), GoogleNews(), AppleCharts(),
                       Pixiv(), ETtoday(), Reddit(), Kenh14(), Steam(), Melon(), Netflix(),
                       YahooTopics(), Hatena(), NicoVideo(), BillboardJapan(), LivedoorTrend(),
                       BillboardUS(), YahooUS(), OfficialCharts(), BBCNews(), KKBoxTW(), YahooTWSearch(), YahooTW(), GnnTW(), VnExpress(),
                       TuoiTre(), DanTri(), ThanhNien(), YahooTrending(), Trends24(), GetDayTrends(),
                       YahooRealtimeJP(), ZumIssue()]
}

__all__ = ["REGISTRY", "Source", "SourceError"]
