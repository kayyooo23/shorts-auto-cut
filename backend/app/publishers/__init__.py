from app.models import Platform, SocialAccount
from app.publishers.base import Publisher
from app.publishers.youtube import YouTubePublisher
from app.publishers.tiktok import TikTokPublisher
from app.publishers.instagram import InstagramPublisher

_PUBLISHERS = {
    Platform.YOUTUBE: YouTubePublisher,
    Platform.TIKTOK: TikTokPublisher,
    Platform.INSTAGRAM: InstagramPublisher,
}


def get_publisher(account: SocialAccount) -> Publisher:
    cls = _PUBLISHERS.get(account.platform)
    if cls is None:
        raise ValueError(f"Нет реализации Publisher для платформы {account.platform}")
    return cls(account)
