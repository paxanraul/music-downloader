from dataclasses import dataclass
from pathlib import Path


@dataclass
class DownloadedTrack:
    file_path: Path
    title: str
    artist: str
