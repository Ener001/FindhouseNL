from .base import Blocked, HttpFetcher, Source
from .funda import Funda
from .generic import Generic
from .holland2stay import Holland2Stay
from .pararius import Pararius

BUILTIN = {"pararius": Pararius, "funda": Funda, "holland2stay": Holland2Stay}


def build(name: str, opts: dict, debug_dir=None, fetcher=None) -> Source:
    if name in BUILTIN:
        return BUILTIN[name](opts, debug_dir, fetcher)
    return Generic(name, opts, debug_dir, fetcher)
