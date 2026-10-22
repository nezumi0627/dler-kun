from dler_kun2.application.experimental import _media_url


def test_experimental_media_filter_rejects_private_network_targets():
    assert not _media_url("http://127.0.0.1/video.mp4")
    assert not _media_url("http://169.254.169.254/latest/video.mp4")
    assert not _media_url("http://media.internal/video.mp4")


def test_experimental_media_filter_accepts_public_media_url():
    assert _media_url("https://cdn.example/video.mp4")
