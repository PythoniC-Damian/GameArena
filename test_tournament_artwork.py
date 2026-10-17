"""Real decoding, private previews, ordered publication and atomic replacement."""
import io
from datetime import datetime, timedelta
from PIL import Image
import pytest
from app import app, db
from gamearena.models import OrganizerDraft, OrganizerProfile, TournamentArtwork, Tournament
from test_interface_contracts import player, client, token


def artwork_uploads():
    result = []
    for color in ('red', 'green', 'blue'):
        image = Image.new('RGB', (640, 360), color)
        output = io.BytesIO()
        image.save(output, 'PNG')
        output.seek(0)
        result.append((output, color + '.png'))
    return result


def event_data():
    return dict(name='Carousel test cup', game='COD Mobile', rules='First to the published score wins; disputes need evidence.', entry_gp='0', prize_gp='0', capacity='16', starts_at=(datetime.utcnow()+timedelta(days=3)).strftime('%Y-%m-%dT%H:%M'))


def post(browser, path, data):
    return browser.post(path, data=dict(data, csrf_token=token(browser.get('/organizers'))))


def test_private_preview_publishes_only_approved_ordered_images():
    with app.app_context():
        owner=player('art_owner'); other=player('art_other'); admin=player('art_admin'); admin.is_admin=True
        db.session.add(OrganizerProfile(user_id=owner.id,contact='verified@example.test',status='approved'));db.session.commit()
        browser=client(owner); stranger=client(other); reviewer=client(admin); anonymous=app.test_client()
        assert post(browser,'/organizers',dict(event_data(),images=artwork_uploads())).status_code==302
        draft=OrganizerDraft.query.one();ids=[image.id for image in draft.artwork]
        assert len(ids)==3
        url=f'/media/tournament-artwork/{ids[0]}.webp'
        preview=browser.get(url)
        assert preview.status_code==200 and preview.mimetype=='image/webp'
        assert 'no-store' in preview.headers['Cache-Control']
        with Image.open(io.BytesIO(preview.data)) as image:
            assert image.format=='WEBP' and image.size==(1280,720)
        assert stranger.get(url).status_code==anonymous.get(url).status_code==404
        assert reviewer.get(url).status_code==200
        assert post(browser,f'/organizers/{draft.id}/submit',{'agree':'yes'}).status_code==302
        assert anonymous.get(url).status_code==404
        assert post(reviewer,f'/organizers/{draft.id}/review',{'action':'approve','checked':'yes'}).status_code==302
        public=anonymous.get(url)
        assert public.status_code==200 and 'immutable' in public.headers['Cache-Control']
        assert anonymous.get(url,headers={'If-None-Match':public.headers['ETag']}).status_code==304
        event=db.session.get(Tournament,draft.tournament_id)
        assert [image.id for image in event.artwork]==ids
        html=anonymous.get('/tournaments').text
        positions=[html.index(f'/media/tournament-artwork/{image_id}.webp') for image_id in ids]
        assert positions==sorted(positions) and 'data-carousel' in html
        api=anonymous.get(f'/api/v1/tournaments/{event.id}').json
        assert api['data']['image_urls']==[f'/media/tournament-artwork/{image_id}.webp' for image_id in ids]


@pytest.mark.parametrize('kind',['missing','two','invalid','large','small'])
def test_invalid_uploads_do_not_create_partial_events(kind):
    with app.app_context():
        browser=client(player('art_invalid'))
        files=artwork_uploads()
        if kind=='missing': files=[]
        if kind=='two': files=files[:2]
        if kind=='invalid': files[1]=(io.BytesIO(b'<svg onload="alert(1)"></svg>'),'pretend.png')
        if kind=='large': files[1]=(io.BytesIO(b'x'*(1024*1024+1)),'large.png')
        if kind=='small':
            small=io.BytesIO();Image.new('RGB',(10,10)).save(small,'PNG');small.seek(0);files[1]=(small,'small.png')
        response=post(browser,'/organizers',dict(event_data(),images=files))
        assert response.status_code==400 and 'Carousel test cup' in response.text
        assert OrganizerDraft.query.count()==TournamentArtwork.query.count()==0


def test_edit_keeps_images_or_replaces_all_atomically():
    with app.app_context():
        owner=player('art_editor');browser=client(owner)
        assert post(browser,'/organizers',dict(event_data(),images=artwork_uploads())).status_code==302
        draft=OrganizerDraft.query.one();url=f'/organizers/{draft.id}/edit';ids=[image.id for image in draft.artwork]
        assert post(browser,url,event_data()).status_code==302
        db.session.expire_all();assert [image.id for image in draft.artwork]==ids
        invalid=artwork_uploads();invalid[2]=(io.BytesIO(b'not an image'),'fake.png')
        assert post(browser,url,dict(event_data(),images=invalid)).status_code==400
        db.session.expire_all();assert [image.id for image in draft.artwork]==ids
        assert post(browser,url,dict(event_data(),images=artwork_uploads())).status_code==302
        db.session.expire_all();assert len(draft.artwork)==3 and not set(ids)&{image.id for image in draft.artwork}
        assert TournamentArtwork.query.count()==3
        assert browser.get(f'/media/tournament-artwork/{ids[0]}.webp').status_code==404


def test_legacy_draft_needs_images_before_submission():
    with app.app_context():
        owner=player('legacy_art');db.session.add(OrganizerProfile(user_id=owner.id,contact='approved@example.test',status='approved'))
        draft=OrganizerDraft(owner_id=owner.id,name='Legacy cup',game='Free Fire',rules='Published rules and scoring.',entry_fee=0,prize_pool=0,capacity=16,starts_at=datetime.utcnow()+timedelta(days=3))
        db.session.add(draft);db.session.commit();browser=client(owner)
        assert post(browser,f'/organizers/{draft.id}/submit',{'agree':'yes'}).status_code==400
        assert draft.status=='draft'
