import importlib


def test_game_image_carousel_returns_game_specific_images():
    app_module = importlib.import_module('app')

    with app_module.app.test_request_context('/'):
        context = app_module.utility_processor()
        carousel = context['game_image_carousel']('PUBG')

    assert isinstance(carousel, list)
    assert len(carousel) >= 2
    assert any('PUBG' in item for item in carousel)
