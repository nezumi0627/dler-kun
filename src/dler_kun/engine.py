from __future__ import annotations

from abc import ABC, abstractmethod

from .models import (
    CrawlRequest,
    CrawlResult,
    DownloadRequest,
    DownloadResult,
    EngineCapability,
    JobStatus,
)


class IDownloader(ABC):
    engine_id: str
    display_name: str
    capabilities: EngineCapability = EngineCapability()

    @abstractmethod
    def detect(self, url: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def download(self, request: DownloadRequest) -> DownloadResult:
        raise NotImplementedError

    def crawl(self, request: CrawlRequest) -> CrawlResult:
        return CrawlResult(
            job_id=request.job_id,
            engine_id=self.engine_id,
            status=JobStatus.UNSUPPORTED,
            message=f"{self.display_name} does not support crawl.",
        )

    def ranking(self, request: CrawlRequest) -> CrawlResult:
        return CrawlResult(
            job_id=request.job_id,
            engine_id=self.engine_id,
            status=JobStatus.UNSUPPORTED,
            message=f"{self.display_name} does not support ranking.",
        )

    def get_metadata(self, url: str) -> dict:
        return {"url": url, "engine_id": self.engine_id}

    def login(self, settings: dict) -> dict:
        return {"status": "unsupported", "engine_id": self.engine_id}
