"""FlashGuard: scan videos for flashing that can trigger photosensitive seizures."""

from .detector import analyze_video, AnalysisResult

__all__ = ["analyze_video", "AnalysisResult"]
__version__ = "0.1.0"
