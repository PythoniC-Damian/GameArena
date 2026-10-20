"""Host selection is random per new pairing and durable through refresh/retry."""
import pytest
import app as application
from app import app,db
from gamearena.models import TournamentMatch,TournamentCheckIn
from test_interface_contracts import client
from test_competition_flow import fixture,check_in,start,post


@pytest.mark.parametrize('coin,expected',[(0,[11,22]),(1,[22,11])])
def test_either_opponent_can_be_selected_without_mutating_pair(monkeypatch,coin,expected):
    monkeypatch.setattr(application.secrets,'randbelow',lambda count:coin)
    pair=[11,22]
    assert application.choose_room_host(pair)==expected
    assert pair==[11,22]


def test_hosts_are_saved_with_correct_ids_and_selected_again_for_final(monkeypatch):
    with app.app_context():
        admin,users,event=fixture(monkeypatch)
        check_in(admin,users,event)
        monkeypatch.setattr(application.random,'shuffle',lambda values:None)
        coins=iter([1,0,1]);calls=[]
        def toss(count):
            assert count==2
            calls.append(count)
            return next(coins)
        monkeypatch.setattr(application.secrets,'randbelow',toss)
        start(admin,event)
        matches=TournamentMatch.query.filter_by(tournament_id=event.id,round_number=1).order_by(TournamentMatch.match_order).all()
        assert [(m.player_one_user_id,m.player_two_user_id) for m in matches]==[(users[1].id,users[0].id),(users[2].id,users[3].id)]
        for match in matches:
            assert match.player_one_profile_id==db.session.get(TournamentCheckIn,(event.id,match.player_one_user_id)).game_id
            assert match.player_two_profile_id==db.session.get(TournamentCheckIn,(event.id,match.player_two_user_id)).game_id
        first=matches[0];host,other=client(first.player_one),client(first.player_two)
        assert post(other,f'/match/{first.id}/room',{'room_code':'WRONG_HOST'}).status_code==403
        assert post(host,f'/match/{first.id}/room',{'room_code':'SYNTHETIC_ROOM'}).status_code==302
        for _ in range(2):assert host.get(f'/match/{first.id}/play').status_code==200
        application.create_tournament_matches(event)
        assert len(calls)==2
        winners=[m.player_one_user_id for m in matches]
        for match in matches:
            match.status='confirmed';match.winner_user_id=match.player_one_user_id
        db.session.commit()
        assert application.advance_tournament_bracket(matches[-1])
        final=TournamentMatch.query.filter_by(tournament_id=event.id,round_number=2).one()
        assert (final.player_one_user_id,final.player_two_user_id)==(winners[1],winners[0])
        assert final.player_one_profile_id==db.session.get(TournamentCheckIn,(event.id,winners[1])).game_id
        assert final.player_two_profile_id==db.session.get(TournamentCheckIn,(event.id,winners[0])).game_id
        assert not application.advance_tournament_bracket(matches[-1])
        assert len(calls)==3 and TournamentMatch.query.filter_by(tournament_id=event.id).count()==3
