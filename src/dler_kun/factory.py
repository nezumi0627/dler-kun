from __future__ import annotations

from .detector import ServiceDetector
from .engine import IDownloader


class DownloaderFactory:
    def __init__(self, detector: ServiceDetector | None = None) -> None:
        self._detector = detector or ServiceDetector()
        self._engines: dict[str, IDownloader] = {}

    def register(self, engine: IDownloader) -> None:
        self._engines[engine.engine_id] = engine

    def get(self, engine_id: str) -> IDownloader | None:
        return self._engines.get(engine_id)

    def detect(self, url: str) -> IDownloader | None:
        engine_id = self._detector.detect(url)
        if not engine_id:
            return None
        return self.get(engine_id)

    def list_engines(self) -> list[dict]:
        return [
            {
                "id": engine.engine_id,
                "name": engine.display_name,
                "capabilities": {
                    "download": engine.capabilities.download,
                    "crawl": engine.capabilities.crawl,
                    "ranking": engine.capabilities.ranking,
                    "metadata": engine.capabilities.metadata,
                    "login": engine.capabilities.login,
                },
            }
            for engine in self._engines.values()
        ]
