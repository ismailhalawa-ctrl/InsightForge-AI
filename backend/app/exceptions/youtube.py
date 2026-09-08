from app.exceptions.base import AppError


class InvalidYouTubeURLError(AppError):
    def __init__(self, message: str = "Invalid YouTube URL") -> None:
        super().__init__(message, status_code=400)


class VideoNotFoundError(AppError):
    # YouTube's public videos.list endpoint returns an empty items[] for a
    # private, deleted, and a never-existed video identically -- there is no
    # API-key-only signal that distinguishes those three, so this message is
    # honest about the ambiguity rather than picking one to claim.
    def __init__(self, message: str = "Video not found, private, or has been removed") -> None:
        super().__init__(message, status_code=404)


class YouTubeAuthError(AppError):
    def __init__(self, message: str = "YouTube API request was rejected") -> None:
        super().__init__(message, status_code=502)


class YouTubeQuotaExceededError(AppError):
    def __init__(self, message: str = "YouTube API quota exceeded") -> None:
        super().__init__(message, status_code=429)


class YouTubeServiceError(AppError):
    def __init__(self, message: str = "YouTube service is unavailable") -> None:
        super().__init__(message, status_code=503)


class YouTubePersistenceError(AppError):
    def __init__(self, message: str = "Failed to save video metadata") -> None:
        super().__init__(message, status_code=500)


class CommentsDisabledError(AppError):
    def __init__(self, message: str = "Comments are disabled for this video") -> None:
        super().__init__(message, status_code=403)
