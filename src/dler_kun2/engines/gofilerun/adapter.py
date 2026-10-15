"""GoFile.run uses the fun800 API, with a separate engine identity."""

from dler_kun2.engines.mvfile.adapter import MvfileEngine


class GofileRunEngine(MvfileEngine):
    engine_id = "gofilerun"
