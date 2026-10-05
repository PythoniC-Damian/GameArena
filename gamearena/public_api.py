"""Read-only public tournament and ranking API. No private account fields."""
from flask import Blueprint, request, jsonify, url_for
from sqlalchemy.orm import joinedload, selectinload
from gamearena.services.redis_support import public_json_cache
public_api = Blueprint('public_api', __name__)

API_MAX_PAGE_SIZE = 50
PUBLIC_TOURNAMENT_STATUSES = {'open', 'ongoing', 'live', 'finished', 'cancelled'}


def api_error(message, status_code=400):
    return jsonify({'error': {'message': message, 'status': status_code}}), status_code


def api_pagination(page, per_page, total):
    return {
        'page': page,
        'per_page': per_page,
        'total': total,
        'total_pages': (total + per_page - 1) // per_page if total else 0,
    }


def tournament_image_url(game_name):
    key = (game_name or '').strip().lower()
    image = GAME_IMAGE_MAP.get(key)
    return url_for('static', filename=image) if image else None


def serialize_tournament(tournament, include_description=True):
    participant_count = sum(
        1 for membership in tournament.participants
        if membership.payment_status in {'paid', 'free'}
    )
    payload = {
        'id': tournament.id,
        'name': tournament.name,
        'game': tournament.game,
        'entry_fee': tournament.entry_fee,
        'prize': tournament.prize,
        'max_participants': tournament.max_participants,
        'participant_count': participant_count,
        'status': tournament.status,
        'match_time': tournament.match_time.isoformat() if tournament.match_time else None,
        'created_at': tournament.created_at.isoformat() if tournament.created_at else None,
        'image_url': tournament_image_url(tournament.game),
    }
    if include_description:
        payload['description'] = tournament.description
    return payload


def public_api_response(payload, status_code=200):
    response = jsonify(payload)
    response.status_code = status_code
    # This data is public and changes infrequently; keep browser caching brief
    # while allowing a CDN to absorb repeated listing requests.
    response.headers['Cache-Control'] = 'public, max-age=30, s-maxage=60, stale-while-revalidate=60'
    response.headers['Vary'] = 'Accept'
    return response


@public_api.route('/api/v1/tournaments')
@public_json_cache()
def api_tournaments():
    page = max(request.args.get('page', 1, type=int) or 1, 1)
    per_page = min(max(request.args.get('per_page', 20, type=int) or 20, 1), API_MAX_PAGE_SIZE)
    status = (request.args.get('status') or '').strip().lower()
    if status and status not in PUBLIC_TOURNAMENT_STATUSES:
        return api_error('Unsupported tournament status.')

    query = Tournament.query.options(selectinload(Tournament.participants))
    if status:
        query = query.filter(Tournament.status == status)
    pagination = query.order_by(Tournament.match_time.asc().nullslast(), Tournament.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False,
    )
    return public_api_response({
        'data': [serialize_tournament(tournament) for tournament in pagination.items],
        'pagination': api_pagination(page, per_page, pagination.total),
    })


@public_api.route('/api/v1/tournaments/<int:tournament_id>')
@public_json_cache()
def api_tournament_detail(tournament_id):
    tournament = Tournament.query.options(
        selectinload(Tournament.participants),
        selectinload(Tournament.leaderboard).joinedload(TournamentStat.user),
        selectinload(Tournament.matches).joinedload(TournamentMatch.player_one),
        selectinload(Tournament.matches).joinedload(TournamentMatch.player_two),
    ).filter_by(id=tournament_id).first()
    if not tournament:
        return api_error('Tournament not found.', 404)

    payload = serialize_tournament(tournament)
    payload['leaderboard'] = [
        {
            'rank': entry.rank, 'points': entry.points, 'wins': entry.wins, 'kills': entry.kills,
            'player': {'id': entry.user.id, 'username': entry.user.username} if entry.user else None,
        }
        for entry in tournament.leaderboard
    ]
    # Room credentials, proof, and disputes deliberately remain private.
    payload['matches'] = [
        {
            'id': match.id, 'status': match.status,
            'player_one': {'id': match.player_one.id, 'username': match.player_one.username} if match.player_one else None,
            'player_two': {'id': match.player_two.id, 'username': match.player_two.username} if match.player_two else None,
            'winner_user_id': match.winner_user_id if match.status == 'confirmed' else None,
        }
        for match in tournament.matches
    ]
    return public_api_response({'data': payload})


@public_api.route('/api/v1/leaderboard')
@public_json_cache()
def api_leaderboard():
    page = max(request.args.get('page', 1, type=int) or 1, 1)
    per_page = min(max(request.args.get('per_page', 20, type=int) or 20, 1), API_MAX_PAGE_SIZE)
    query = TournamentStat.query.options(
        joinedload(TournamentStat.user), joinedload(TournamentStat.tournament),
    ).order_by(TournamentStat.rank.asc(), TournamentStat.points.desc(), TournamentStat.id.asc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    return public_api_response({
        'data': [
            {
                'id': entry.id, 'rank': entry.rank, 'points': entry.points,
                'wins': entry.wins, 'kills': entry.kills,
                'player': {'id': entry.user.id, 'username': entry.user.username} if entry.user else None,
                'tournament': {'id': entry.tournament.id, 'name': entry.tournament.name, 'game': entry.tournament.game} if entry.tournament else None,
            }
            for entry in pagination.items
        ],
        'pagination': api_pagination(page, per_page, pagination.total),
    })



def register_public_api(app, tournament, stat, match, image_map):
    global Tournament, TournamentStat, TournamentMatch, GAME_IMAGE_MAP
    Tournament, TournamentStat, TournamentMatch, GAME_IMAGE_MAP = tournament, stat, match, image_map
    app.register_blueprint(public_api)
    # Existing url_for names resolve to the same single registered routes.
    def legacy_api_url(error, endpoint, values):
        if endpoint in {'api_tournaments', 'api_tournament_detail', 'api_leaderboard'}:
            return url_for('public_api.' + endpoint, **values)
    app.url_build_error_handlers.append(legacy_api_url)
