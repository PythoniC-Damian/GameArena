"""Checked-in single-elimination competition; authoritative game results are not inferred."""
import hashlib
import io
import json
import re
import unicodedata
import uuid
from datetime import datetime, timedelta
from PIL import Image, ImageOps, UnidentifiedImageError
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload
from gamearena.extensions import db
from gamearena.models import (Tournament, TournamentMatch, UserTournament, OrganizerDraft, User,
    TournamentCompetition, TournamentCheckIn, MatchLobby, MatchEvidence, TournamentMatchDispute, TournamentMatchChatMessage, OrganizerProfile, TournamentStat)

competition = Blueprint('competition', __name__)
ACTIVE = {'scheduled','ongoing','pending_confirmation','disputed'}


def sync_standings(event):
    """Recompute from confirmed managed matches, under the caller's event lock.

    No score is invented and no financial fields are changed. Equal elimination
    rounds share placement; a semifinal loser is never arbitrarily made fourth.
    The caller commits this with its match/phase change.
    """
    if not db.session.get(TournamentCompetition, event.id): return
    db.session.flush()
    matches = TournamentMatch.query.filter_by(tournament_id=event.id).order_by(TournamentMatch.round_number).all()
    participants = {uid for m in matches for uid in (m.player_one_user_id,m.player_two_user_id)}
    stats = {s.user_id:s for s in TournamentStat.query.filter_by(tournament_id=event.id).all()}
    wins = dict.fromkeys(participants, 0)
    losses = {}
    confirmed = [m for m in matches if m.status=='confirmed' and m.winner_user_id in (m.player_one_user_id,m.player_two_user_id)]
    for match in confirmed:
        wins[match.winner_user_id] += 1
        loser = match.player_two_user_id if match.winner_user_id==match.player_one_user_id else match.player_one_user_id
        losses[loser] = match.round_number
    final_round = max((m.round_number or 0 for m in matches), default=0)
    finished = event.status=='finished' and len([m for m in confirmed if m.round_number==final_round])==1
    champion = next((m.winner_user_id for m in confirmed if m.round_number==final_round),None) if finished else None
    for uid in participants:
        stat = stats.get(uid)
        if not stat:
            stat = TournamentStat(user_id=uid,tournament_id=event.id)
            db.session.add(stat)
        stat.wins = wins[uid]
        stat.points = wins[uid]  # one point per confirmed win; never OCR-derived kills
        stat.kills = 0
        stat.rank = (1 if uid==champion else 2**(final_round-losses[uid])+1) if finished and (uid==champion or uid in losses) else 0


def supports_bracket(game):
    key=re.sub(r'[^a-z0-9]','',(game or '').lower())
    return key in {'cod','codmobile','callofdutymobile','efootball','efootballmobile'}


def can_manage(event):
    if not current_user.is_authenticated or current_user.suspended:
        return False
    if current_user.is_admin:return True
    profile=db.session.get(OrganizerProfile,current_user.id)
    return bool(current_user.email_verified and profile and profile.status=='approved' and OrganizerDraft.query.filter_by(tournament_id=event.id,owner_id=current_user.id,status='published').first())


def limit():
    from app import consume_rate_limit
    if consume_rate_limit('competition_change:'+str(current_user.id),20,60) is not None:
        abort(429,description='Too many changes. Please try again in a minute.')


def event_lock(event_id):
    return Tournament.query.filter_by(id=event_id).with_for_update().populate_existing().first_or_404()


def lock_match(match_id):
    original = db.session.get(TournamentMatch,match_id)
    if not original: abort(404)
    event = event_lock(original.tournament_id)
    if event.status in {'cancelled','finished'}:
        abort(409,description='This tournament is closed for match changes.')
    return TournamentMatch.query.filter_by(id=match_id).with_for_update().populate_existing().one()


def notify(ids, message, event_id, match_id=None):
    from app import create_and_emit_notification
    announce_change(event_id)
    for uid in set(ids):
        create_and_emit_notification(uid,message,'match' if match_id else 'tournament',
            f'/match/{match_id}/play' if match_id else f'/tournament/{event_id}')


def eligible(event_id):
    return UserTournament.query.join(User,User.id==UserTournament.user_id).filter(
        UserTournament.tournament_id==event_id,UserTournament.payment_status.in_(('paid','free'))).order_by(UserTournament.user_id).all()


def checked(event_id):
    return TournamentCheckIn.query.filter_by(tournament_id=event_id).order_by(TournamentCheckIn.user_id).all()


def own_match(event_id):
    if not current_user.is_authenticated: return None
    return TournamentMatch.query.filter(TournamentMatch.tournament_id==event_id,
        db.or_(TournamentMatch.player_one_user_id==current_user.id,TournamentMatch.player_two_user_id==current_user.id)
        ).order_by(TournamentMatch.round_number.desc().nullslast(),TournamentMatch.id.desc()).first()


def state(event):
    config=db.session.get(TournamentCompetition,event.id)
    match=own_match(event.id)
    lobby=db.session.get(MatchLobby,match.id) if match else None
    latest_chat=db.session.query(db.func.max(TournamentMatchChatMessage.id)).filter_by(match_id=match.id).scalar() if match else None
    values=[event.status,config.phase if config else '',str(config.checkin_closes_at) if config else '',TournamentCheckIn.query.filter_by(tournament_id=event.id).count(),
        match.id if match else None,match.status if match else None,str(match.updated_at) if match else '',latest_chat]
    progress=db.session.query(db.func.count(TournamentMatch.id),db.func.max(TournamentMatch.updated_at)).filter_by(tournament_id=event.id).one()
    values.extend([progress[0],str(progress[1])])
    if lobby: values.extend([str(lobby.published_at),str(lobby.player_one_ready_at),str(lobby.player_two_ready_at),lobby.review_note])
    return {'signature':hashlib.sha256(json.dumps(values).encode()).hexdigest()[:24],
        'match_url':url_for('competition.play',match_id=match.id) if match else None,'closed':event.status in {'cancelled','finished'}}


def context(event):
    config=db.session.get(TournamentCompetition,event.id)
    manager=can_manage(event)
    rows=checked(event.id) if config else []
    mine=next((row for row in rows if row.user_id==current_user.id),None) if current_user.is_authenticated else None
    final=TournamentMatch.query.filter_by(tournament_id=event.id,status='confirmed').order_by(TournamentMatch.round_number.desc(),TournamentMatch.id.desc()).first() if config and config.phase=='finished' else None
    return dict(competition_champion=final.winner if final else None,competition_config=config,competition_manager=manager,competition_supported=supports_bracket(event.game),
        competition_checked=len(rows),competition_eligible=len(eligible(event.id)) if config else 0,
        competition_checkin=mine,competition_roster=rows if manager else [],competition_match=own_match(event.id) if config else None,
        competition_now=datetime.utcnow(),competition_state=state(event) if config and current_user.is_authenticated else None)


@competition.route('/tournament/<int:tournament_id>/competition/setup',methods=['POST'])
@login_required
def setup(tournament_id):
    limit();event=event_lock(tournament_id)
    if not can_manage(event):abort(403)
    if event.status!='open' or TournamentMatch.query.filter_by(tournament_id=event.id).first():abort(409)
    if not supports_bracket(event.game):abort(400,description='1v1 brackets currently support COD Mobile and eFootball events.')
    if event.max_participants<2 or event.max_participants>128 or event.max_participants&(event.max_participants-1):
        abort(400,description='Choose a capacity of 2, 4, 8, 16, 32, 64 or 128 for a 1v1 bracket.')
    if db.session.get(TournamentCompetition,event.id):abort(409,description='The competition format and rules have already been published.')
    rules=request.form.get('game_rules','').strip();policy=request.form.get('no_show_policy','').strip()
    if not (20<=len(rules)<=10000 and 20<=len(policy)<=1000) or request.form.get('rules_ack')!='yes':
        abort(400,description='Publish the mode, map/settings, score target and no-show/disconnection rules before enabling this format.')
    if eligible(event.id):abort(409,description='Publish the competition rules before accepting entries. Use a new event if players have already joined.')
    db.session.add(TournamentCompetition(tournament_id=event.id,phase='registration',game_rules=rules,no_show_policy=policy))
    db.session.commit();flash('1v1 format and competition guidelines published.','success')
    return redirect(url_for('tournament_details',tournament_id=event.id))


@competition.route('/tournament/<int:tournament_id>/competition/open-check-in',methods=['POST'])
@login_required
def open_checkin(tournament_id):
    limit();event=event_lock(tournament_id)
    if not can_manage(event):abort(403)
    config=db.session.get(TournamentCompetition,event.id)
    if not config or config.phase not in {'registration','check_in'} or event.status not in {'open','ongoing'}:abort(409)
    try:deadline=datetime.strptime(request.form.get('deadline',''),'%Y-%m-%dT%H:%M')
    except ValueError:abort(400,description='Choose a future check-in deadline in UTC.')
    if not datetime.utcnow()<deadline<=datetime.utcnow()+timedelta(days=7):abort(400,description='The deadline must be in the next 7 days.')
    config.phase='check_in';config.checkin_closes_at=deadline;event.status='ongoing'
    ids=[row.user_id for row in eligible(event.id)]
    db.session.commit();notify(ids,'Check-in is open for '+event.name+'. Confirm your in-game ID and readiness.',event.id)
    return redirect(url_for('tournament_details',tournament_id=event.id))


@competition.route('/tournament/<int:tournament_id>/competition/reopen-registration',methods=['POST'])
@login_required
def reopen_registration(tournament_id):
    limit();event=event_lock(tournament_id)
    if not can_manage(event):abort(403)
    config=db.session.get(TournamentCompetition,event.id)
    if not config or config.phase not in {'registration','check_in'} or event.status not in {'open','ongoing'}:abort(409)
    if TournamentMatch.query.filter_by(tournament_id=event.id).first():
        abort(409,description='Registration cannot be reopened after competition matches have been created.')
    config.phase='registration';event.status='open'
    db.session.commit()
    return redirect(url_for('tournament_details',tournament_id=event.id))


@competition.route('/tournament/<int:tournament_id>/competition/check-in',methods=['POST'])
@login_required
def checkin(tournament_id):
    limit();event=event_lock(tournament_id);config=db.session.get(TournamentCompetition,event.id)
    membership=UserTournament.query.filter_by(tournament_id=event.id,user_id=current_user.id).first()
    if not membership or membership.payment_status not in {'paid','free'} or current_user.suspended:abort(403)
    if not config or config.phase!='check_in' or event.status!='ongoing' or not config.checkin_closes_at or datetime.utcnow()>config.checkin_closes_at:abort(409,description='Check-in is closed. Contact the organiser if you missed the deadline.')
    game_id=unicodedata.normalize('NFKC',request.form.get('game_id','')).strip()
    if not 3<=len(game_id)<=150 or any(ord(c)<32 for c in game_id) or request.form.get('agree')!='yes':
        abort(400,description='Enter your in-game ID and accept the published match rules.')
    normalized=' '.join(game_id.casefold().split())
    if len(normalized)>150:abort(400,description='The in-game ID is too long.')
    duplicate=TournamentCheckIn.query.filter_by(tournament_id=event.id,normalized_game_id=normalized).first()
    if duplicate and duplicate.user_id!=current_user.id:abort(409,description='That in-game ID is already checked in for this event.')
    row=db.session.get(TournamentCheckIn,(event.id,current_user.id))
    if not row:row=TournamentCheckIn(tournament_id=event.id,user_id=current_user.id);db.session.add(row)
    row.game_id=game_id;row.normalized_game_id=normalized;row.checked_at=datetime.utcnow();row.rules_version='1v1-v1'
    db.session.commit();announce_change(event.id);flash('Checked in. Stay available for your assigned match.','success')
    return redirect(url_for('tournament_details',tournament_id=event.id))


@competition.route('/tournament/<int:tournament_id>/competition/start',methods=['POST'])
@login_required
def start(tournament_id):
    limit();event=event_lock(tournament_id)
    if not can_manage(event):abort(403)
    from app import create_tournament_matches
    config=db.session.get(TournamentCompetition,event.id)
    if not config or config.phase!='check_in' or event.status!='ongoing':abort(409)
    matches=create_tournament_matches(event)
    if not matches:
        db.session.rollback();abort(409,description='Every eligible entrant must check in, pending payments must be resolved, and the field must contain 2, 4, 8, 16, 32, 64 or 128 players. Extend check-in or cancel/refund instead of silently dropping entrants.')
    return redirect(url_for('tournament_details',tournament_id=event.id))


@competition.route('/match/<int:match_id>/play')
@login_required
def play(match_id):
    from app import can_access_match
    match=TournamentMatch.query.get_or_404(match_id)
    if not can_access_match(current_user.id,match):abort(404)
    config=db.session.get(TournamentCompetition,match.tournament_id)
    if not config:return redirect(url_for('tournament_details',tournament_id=match.tournament_id))
    lobby=db.session.get(MatchLobby,match.id)
    messages=TournamentMatchChatMessage.query.filter_by(match_id=match.id).order_by(TournamentMatchChatMessage.id.desc()).limit(50).all()[::-1]
    evidence=MatchEvidence.query.filter_by(match_id=match.id).order_by(MatchEvidence.created_at,MatchEvidence.id).all()
    return render_template('competition_play.html',match=match,tournament=match.tournament,config=config,lobby=lobby,
        messages=messages,evidence=evidence,is_player=current_user.id in {match.player_one_user_id,match.player_two_user_id},
        competition_state=state(match.tournament))


@competition.route('/match/<int:match_id>/room',methods=['POST'])
@login_required
def room(match_id):
    limit();match=lock_match(match_id)
    if current_user.id!=match.player_one_user_id:abort(403,description='The assigned host creates and shares the room.')
    lobby=db.session.get(MatchLobby,match.id)
    if not lobby or match.status!='scheduled' or lobby.player_one_ready_at or lobby.player_two_ready_at:abort(409)
    code=request.form.get('room_code','').strip();password=request.form.get('room_password','').strip()
    if not 1<=len(code)<=100 or len(password)>100:abort(400)
    match.room_code=code;match.room_password=password;lobby.published_at=datetime.utcnow();match.updated_at=datetime.utcnow()
    db.session.commit();notify([match.player_two_user_id],'Your host shared the room for '+match.tournament.name+'.',match.tournament_id,match.id)
    return redirect(url_for('competition.play',match_id=match.id))


@competition.route('/match/<int:match_id>/ready',methods=['POST'])
@login_required
def ready(match_id):
    limit();match=lock_match(match_id)
    if current_user.id not in {match.player_one_user_id,match.player_two_user_id}:abort(403)
    lobby=db.session.get(MatchLobby,match.id)
    if not lobby or not lobby.published_at or not match.room_code or match.status not in {'scheduled','ongoing'} or request.form.get('agree')!='yes':abort(409)
    field='player_one_ready_at' if current_user.id==match.player_one_user_id else 'player_two_ready_at'
    changed=not getattr(lobby,field)
    if changed:setattr(lobby,field,datetime.utcnow())
    if lobby.player_one_ready_at and lobby.player_two_ready_at:match.status='ongoing'
    match.updated_at=datetime.utcnow();db.session.commit()
    if changed:
        other=match.player_two_user_id if current_user.id==match.player_one_user_id else match.player_one_user_id
        notify([other],'Your opponent is ready in the room for '+match.tournament.name+'.',match.tournament_id,match.id)
    return redirect(url_for('competition.play',match_id=match.id))


def store_evidence(match, upload):
    if not upload or not upload.filename:raise ValueError('Upload a result screenshot showing both game IDs and the final score.')
    raw=upload.stream.read(4*1024*1024+1)
    if not raw or len(raw)>4*1024*1024:raise ValueError('Evidence must be a JPEG, PNG or WebP image up to 4 MB.')
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in {'JPEG','PNG','WEBP'} or source.width*source.height>12_000_000:raise ValueError('Use a JPEG, PNG or WebP screenshot up to 12 megapixels.')
            if source.width<240 or source.height<240:raise ValueError('Use a readable screenshot at least 240 pixels wide and tall.')
            source.load();image=ImageOps.exif_transpose(source).convert('RGB');image.thumbnail((1600,1600))
            output=io.BytesIO();image.save(output,'WEBP',quality=90)
    except (OSError,UnidentifiedImageError,Image.DecompressionBombError) as error:raise ValueError('That evidence image could not be read.') from error
    if MatchEvidence.query.filter_by(match_id=match.id,user_id=current_user.id).count()>=10:
        raise ValueError('Too many evidence revisions. Contact staff for review.')
    row=MatchEvidence(id=uuid.uuid4().hex,match_id=match.id,user_id=current_user.id,image=output.getvalue());db.session.add(row)


def prepare_result(match):
    lobby=db.session.get(MatchLobby,match.id)
    if match.status!='ongoing' or not lobby or not lobby.player_one_ready_at or not lobby.player_two_ready_at:raise ValueError('Both players must join the room and mark ready before reporting a result.')
    scores=[]
    for key in ('player_one_score','player_two_score'):
        value=request.form.get(key,'')
        if not re.fullmatch(r'[0-9]{1,4}',value):raise ValueError('Enter both final scores using whole numbers from 0 to 9999.')
        scores.append(int(value))
    if scores[0]==scores[1]:raise ValueError('A knockout match needs a winner. Follow the published tie-break rules.')
    winner=match.player_one_user_id if scores[0]>scores[1] else match.player_two_user_id
    if str(winner)!=request.form.get('winner_user_id'):raise ValueError('The winner must match the submitted score.')
    store_evidence(match,request.files.get('evidence'))
    lobby.player_one_score,lobby.player_two_score=scores
    return dict(room_code=match.room_code,room_password=match.room_password or '',player_profile_id=match.player_one_profile_id,
        opponent_profile_id=match.player_two_profile_id,winner_user_id=winner,proof_note=request.form.get('proof_note','').strip())


@competition.route('/match/<int:match_id>/report-issue',methods=['POST'])
@login_required
def report_issue(match_id):
    limit();match=lock_match(match_id)
    if current_user.id not in {match.player_one_user_id,match.player_two_user_id}:abort(403)
    if not db.session.get(MatchLobby,match.id) or match.status not in {'scheduled','ongoing'}:abort(409)
    reason=request.form.get('reason','').strip()
    if not 10<=len(reason)<=2000:abort(400,description='Describe the no-show, connection or room issue in 10 to 2000 characters.')
    if request.files.get('evidence') and request.files['evidence'].filename:
        try:store_evidence(match,request.files['evidence'])
        except ValueError as error:db.session.rollback();abort(400,description=str(error))
    db.session.add(TournamentMatchDispute(match_id=match.id,user_id=current_user.id,reason=reason));match.status='disputed';db.session.commit()
    notify([match.player_one_user_id,match.player_two_user_id],'A match issue needs staff review. This match is paused.',match.tournament_id,match.id)
    return redirect(url_for('competition.play',match_id=match.id))


@competition.route('/media/match-evidence/<string:evidence_id>.webp')
@login_required
def evidence(evidence_id):
    from app import can_access_match
    row=db.session.get(MatchEvidence,evidence_id)
    if not row:abort(404)
    match=db.session.get(TournamentMatch,row.match_id)
    if not can_access_match(current_user.id,match):abort(404)
    from flask import Response
    return Response(row.image,mimetype='image/webp',headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})


@competition.route('/tournament/<int:tournament_id>/competition/status')
@login_required
def status(tournament_id):
    event=Tournament.query.get_or_404(tournament_id)
    member=UserTournament.query.filter_by(tournament_id=event.id,user_id=current_user.id).first()
    if not can_manage(event) and not (member and member.payment_status in {'paid','free','refunded'}):abort(403)
    return jsonify(state(event)),200,{'Cache-Control':'private, no-store'}


@competition.route('/tournaments/guide/1v1')
@competition.route('/tournaments/guide')
def guide():
    return render_template('competition_guide.html')


def announce_change(event_id):
    from app import socketio
    socketio.emit('competition_update',{'tournament_id':event_id},room='competition:'+str(event_id))


def register_socket(socketio):
    @socketio.on('watch_competition')
    def watch_competition(data):
        from gamearena.account_security import socket_identity_allowed
        if not socket_identity_allowed(): return {'status':'denied'}
        if not current_user.is_authenticated or current_user.suspended or not isinstance(data,dict):return {'status':'denied'}
        from app import consume_rate_limit
        if consume_rate_limit('competition_watch:'+str(current_user.id),20,60) is not None:return {'status':'limited'}
        value=data.get('tournament_id')
        if type(value) is not int or not 0<value<2147483647:return {'status':'denied'}
        event=db.session.get(Tournament,value)
        if not event:return {'status':'denied'}
        member=UserTournament.query.filter_by(tournament_id=value,user_id=current_user.id).first()
        if not can_manage(event) and not (member and member.payment_status in {'paid','free','refunded'}):return {'status':'denied'}
        from flask_socketio import join_room
        join_room('competition:'+str(value))
        return {'status':'ok'}


@competition.route('/admin/competition/reviews')
@login_required
def reviews():
    if not current_user.is_admin or current_user.suspended:abort(403)
    page=max(1,request.args.get('page',1,type=int) or 1)
    rows=TournamentMatch.query.options(joinedload(TournamentMatch.tournament),joinedload(TournamentMatch.player_one),joinedload(TournamentMatch.player_two)).join(TournamentCompetition,TournamentCompetition.tournament_id==TournamentMatch.tournament_id).join(Tournament,Tournament.id==TournamentMatch.tournament_id).filter(
        TournamentMatch.status=='disputed',Tournament.status.in_(('live','ongoing'))).order_by(TournamentMatch.updated_at,TournamentMatch.id).paginate(page=page,per_page=25,error_out=False)
    return render_template('competition_reviews.html',rows=rows)
