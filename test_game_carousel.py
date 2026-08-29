import importlib


def test_game_image_carousel_returns_game_specific_images():
    app_module = importlib.import_module('app')

    with app_module.app.test_request_context('/'):
        context = app_module.utility_processor()
        carousel = context['game_image_carousel']('PUBG')

    assert isinstance(carousel, list)
    assert len(carousel) >= 2
    assert any('PUBG' in item for item in carousel)


def test_featured_tournaments_include_only_supported_local_games():
    app_module = importlib.import_module('app')

    class FakeTournament:
        def __init__(self, name, game, entry_fee=100, prize=1000):
            self.name = name
            self.game = game
            self.entry_fee = entry_fee
            self.prize = prize
            self.id = 1
            self.status = 'open'

    tournaments = [
        FakeTournament('PUBG Clash', 'PUBG', 3000, 50000),
        FakeTournament('Free Fire Brawl', 'Free Fire', 1500, 22000),
        FakeTournament('COD Rush', 'Call of Duty Mobile', 2500, 25000),
        FakeTournament('Efootball Final', 'eFootball', 2000, 18000),
        FakeTournament('DLS Cup', 'DLS', 5000, 60000),
    ]

    with app_module.app.test_request_context('/'):
        context = app_module.utility_processor()
        featured = context['featured_tournaments'](tournaments)

    assert [item.game for item in featured] == ['PUBG', 'Free Fire', 'Call of Duty Mobile', 'eFootball']
    assert all('DLS' not in item.game for item in featured)
    assert all('static/images/' in context['game_image_carousel'](item.game)[0] for item in featured)
