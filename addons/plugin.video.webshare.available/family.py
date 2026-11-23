# -*- coding: utf-8 -*-
"""Family-facing navigation and a strictly matched, metadata-aware resolver."""
import hashlib
import json
import os
import queue
import re
import sys
import threading
import time
import uuid
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

import core
from matching import attributes, episode_source_titles, normal, rank_source, source_label, valid_source
from matching import source_attributes, track_lines, source_summary
from streams import HTTPReader, inspect as inspect_streams

ID = 'plugin.video.webshare.available'
ADDON = xbmcaddon.Addon(ID)
PATH = xbmcvfs.translatePath(ADDON.getAddonInfo('path'))
PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
HOME = xbmcgui.Window(10000)
HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 and str(sys.argv[1]).lstrip('-').isdigit() else -1
PARAMS = {k: v[0] for k, v in parse_qs(sys.argv[2][1:] if len(sys.argv) > 2 and sys.argv[2].startswith('?') else '').items()}
BASE = 'plugin://' + ID + '/'
PENDING_PLAYBACK = None
MOVIE_STATUS = None
ORIGINAL_SOURCE = core.fetch_source
ORIGINAL_AUTH = core.get_trakt_auth


def begin_invocation(arguments):
    global HANDLE, PARAMS, PENDING_PLAYBACK, MOVIE_STATUS
    HANDLE = int(arguments[1]) if len(arguments)>1 and str(arguments[1]).lstrip('-').isdigit() else -1
    PARAMS = {key:values[0] for key,values in parse_qs(arguments[2][1:] if len(arguments)>2 and arguments[2].startswith('?') else '').items()}
    PENDING_PLAYBACK = None
    MOVIE_STATUS = None

def rpc(method, params=None):
    request = {'jsonrpc': '2.0', 'id': 1, 'method': method}
    if params is not None:
        request['params'] = params
    return json.loads(xbmc.executeJSONRPC(json.dumps(request))).get('result')

def url(action, **data):
    return BASE + '?' + urlencode({'action': action, **{k: v for k, v in data.items() if v is not None}})

def auth():
    client_id = core.trakt_client_id()
    candidates = core.trakt_token_candidates()
    signature = hashlib.sha256(json.dumps([row['access_token'] for row in candidates]).encode()).hexdigest()
    cached = HOME.getProperty('Family.TraktValidated').split(':')
    try:recent = len(cached)==3 and cached[1]==signature and time.time()-float(cached[2])<300
    except ValueError:recent = False
    if recent and client_id:
        for stored in candidates:
            token=stored['access_token']
            digest=hashlib.sha256((client_id+'\0'+token).encode()).hexdigest()
            if cached[0]==digest:return client_id,token
    result = ORIGINAL_AUTH()
    # Cache the pair that actually passed validation, rather than the first
    # candidate (which may be a stale session after credential migration).
    digest=hashlib.sha256((result[0]+'\0'+result[1]).encode()).hexdigest()
    HOME.setProperty('Family.TraktValidated', digest + ':' + signature + ':' + str(time.time()))
    return result

core.get_trakt_auth = auth

def progress_file():
    return os.path.join(PROFILE, 'family-progress.json')

def local_progress():
    return core.read_json(progress_file(), {}) or {}

def movie_status():
    from movie_watch import MovieStatus

    return MovieStatus(sys.modules[__name__])

def media_key(kind, ident, season=None, episode=None):
    return ':'.join(str(v) for v in (kind, ident, season, episode))

def episode_item(row):
    ep, show = row.get('episode') or {}, row.get('show') or {}
    ids = show.get('ids') or {}
    return {'kind': 'episode', 'tmdb_id': ids.get('tmdb'), 'imdb_id': ids.get('imdb'),
            'trakt_id': ids.get('trakt'), 'show_title': show.get('title', ''), 'show_year': show.get('year', 0),
            'season': ep.get('season', 0), 'episode': ep.get('number', 0), 'episode_title': ep.get('title', ''),
            'premiered': ep.get('first_aired', ''), 'progress': row.get('progress', 0)}

def family_source(kind, source, force=False):
    if source == 'playback' and kind == 'movie':
        rows = core.trakt_request('/sync/playback/movies', {'extended': 'full', 'limit': 36})
        items = [dict(core.normalise_trakt_media(row, 'movie'), progress=row.get('progress', 0)) for row in rows]
    elif source == 'collection' and kind in ('movie', 'tv'):
        rows = core.trakt_request('/sync/collection/' + ('movies' if kind == 'movie' else 'shows'), {'extended': 'full'})
        items = [core.normalise_trakt_media(row, kind) for row in rows[:36]]
    elif source == 'history':
        suffix = '' if kind == 'both' else ('/movies' if kind == 'movie' else '/shows')
        rows = core.trakt_request('/sync/history' + suffix, {'extended': 'full', 'limit': 36})
        items = [episode_item(row) if row.get('episode') else core.normalise_trakt_media(row, 'movie') for row in rows]
    else:
        items = ORIGINAL_SOURCE(kind, source, force)
    if source == 'playback':
        found = {media_key(x.get('kind', kind), x.get('tmdb_id'), x.get('season'), x.get('episode')) for x in items}
        for key, record in local_progress().items():
            if record.get('kind') != kind or record.get('completed') or record.get('position', 0) < 15 or key in found:
                continue
            items.insert(0, record['item'])
    return items

core.fetch_source = family_source

def classify_error(exc):
    text = str(exc)
    if 'TRAKT_CLIENT_UNAVAILABLE' in text:
        return 'Připojení Traktu vyžaduje kontrolu.', 'Otevři Moje → Servis → Kontrola rodinného kina. Rozhraní doplňku Trakt není dostupné.'
    if 'SOURCE_UNAVAILABLE' in text:
        return 'Vybraný zdroj nyní není dostupný.', 'Vyber jiný jazyk nebo kvalitu. Tlačítko Zpět tě vrátí ke kartě titulu.'
    status = getattr(exc, 'code', 0)
    match = re.search(r'\bHTTP\s+(\d{3})', text)
    if not status and match:
        status = int(match[1])
    if status in (401, 403) or any(x in text.lower() for x in ('token', 'auth_required', 'přihlaš')):
        return 'Přihlášení vyžaduje kontrolu.', 'Otevři Servis a ověř přihlášení k příslušné službě.'
    if status == 420:
        return 'Tento seznam není pro účet dostupný.', 'Ostatní části kina můžeš používat dál.'
    if isinstance(exc, (URLError, TimeoutError)) or status == 429 or any(x in text.lower() for x in ('timed out', 'timeout', 'network')):
        return 'Služba nyní neodpovídá.', 'Zkus to za chvíli znovu. Tlačítko Zpět se vrátí k titulu.'
    return 'Obsah se nepodařilo načíst.', 'Zkus to znovu. Pokud problém trvá, otevři kontrolu v Servisu.'

def async_work(function, message, cancel=None, progress_value=None):
    results = queue.Queue(1)
    generation = HOME.getProperty('Family.CancelGeneration')
    def worker():
        try:
            results.put((True, function()))
        except Exception as exc:
            results.put((False, exc))
    threading.Thread(target=worker, daemon=True).start()
    progress = xbmcgui.DialogProgress()
    progress.create('Rodinné kino', message)
    monitor = xbmc.Monitor()
    start = time.monotonic()
    try:
        while not monitor.abortRequested():
            if progress.iscanceled() or HOME.getProperty('Family.CancelGeneration') != generation:
                return None
            try:
                ok, value = results.get_nowait()
                if ok:
                    return value
                raise value
            except queue.Empty:
                pass
            if time.monotonic() - start > 45:
                raise TimeoutError('Lookup deadline')
            done,total = progress_value() if progress_value else (0,0)
            progress.update(int(done*100/total) if total else 0, message + ('\n{} / {}'.format(done,total) if total else '') + '\nZpět = zrušit')
            monitor.waitForAbort(0.1)
        return None
    finally:
        if cancel:
            cancel.set()
        progress.close()

def origin():
    gui = rpc('GUI.GetProperties', {'properties': ['currentwindow', 'currentcontrol']}) or {}
    wid = xbmcgui.getCurrentWindowId()
    try:
        cid = xbmcgui.Window(wid).getFocusId()
    except RuntimeError:
        cid = int(xbmc.getInfoLabel('System.CurrentControlID') or 0)
    pos = int(xbmc.getInfoLabel('Container({}).CurrentItem'.format(cid)) or 1) - 1
    path = xbmc.getInfoLabel('Container.FolderPath') if wid == 10025 else ''
    if path and not path.startswith(('plugin://' + ID + '/', 'plugin://plugin.video.themoviedb.helper/')):
        path = ''
    watch_catalog = (parse_qs(urlsplit(path).query).get('source', [''])[0].startswith('provider_')
                     or (wid == 11104 and '_provider_' in xbmc.getInfoLabel('ListItem.Property(family.paging.key)')))
    row = xbmc.getInfoLabel('Container(601).CurrentItem')
    return {'window': wid if wid in (10000, 10025, 11101, 11102, 11103, 11104, 11105) else 10000,
            'control': cid, 'position': max(0, pos), 'path': path, 'watch_catalog': watch_catalog,
            'row': max(0, int(row) - 1) if row.isdigit() else None,
            'tmdb_id': xbmc.getInfoLabel('ListItem.Property(tmdb_id)'),
            'season': xbmc.getInfoLabel('ListItem.Season'), 'episode': xbmc.getInfoLabel('ListItem.Episode')}

def item_from_params(data):
    kind = data.get('kind', 'movie')
    ident = int(data.get('tmdb_id') or data.get('tmdb') or 0)
    if kind == 'tv' and data.get('episode') is not None:
        kind = 'episode'
    item = {'kind': kind, 'tmdb_id': ident, 'title': data.get('title', ''), 'year': int(data.get('year') or 0)}
    if kind == 'episode':
        item.update({'season': int(data.get('season') or 0), 'episode': int(data.get('episode') or 0), 'show_title': data.get('show_title') or data.get('showname', '')})
    if ident <= 0 or kind not in ('movie', 'tv', 'episode') or (kind == 'episode' and item['episode'] <= 0):
        raise ValueError('Missing media identity')
    return item

def record_for(item):
    meta = core.fetch_meta(item['kind'], item)
    if item['kind'] == 'episode':
        payload = core.tmdb_request('/tv/{}/season/{}/episode/{}'.format(item['tmdb_id'], item['season'], item['episode']), {'append_to_response': 'external_ids'})
        meta = dict(meta, episode_tmdb_id=payload.get('id'), external_ids=payload.get('external_ids') or {})
        item.update(show_title=meta.get('show_title', ''), episode_title=meta.get('title', ''))
    else:
        item.update(title=meta.get('title', item.get('title', '')), year=meta.get('year', item.get('year', 0)))
    record = {'item': item, 'meta': meta}
    if item['kind'] != 'tv':
        saved = local_progress().get(media_key(item['kind'], item['tmdb_id'], item.get('season'), item.get('episode')))
        if saved is None:
            # Existing cloud progress is read once and kept locally; account data
            # never leaves the box. Newly stopped playback takes precedence.
            key = 'family_resume_' + ('movies' if item['kind'] == 'movie' else 'episodes')
            rows = core.read_cache_entry('source', key, 300)
            if rows is None:
                try:
                    rows = core.trakt_request('/sync/playback/' + ('movies' if item['kind'] == 'movie' else 'episodes'), {'extended': 'full', 'limit': 100})
                    core.write_cache_entry('source', key, rows)
                except Exception:
                    # Cloud resume is optional; a temporary cloud outage must not
                    # prevent opening an otherwise available title.
                    rows = []
                    record['cloud_resume_unavailable'] = True
            for row in rows:
                media = row.get('movie') if item['kind'] == 'movie' else row.get('show')
                if (media or {}).get('ids', {}).get('tmdb') != item['tmdb_id']:
                    continue
                ep = row.get('episode') or {}
                if item['kind'] == 'episode' and (ep.get('season'), ep.get('number')) != (item['season'], item['episode']):
                    continue
                runtime = meta.get('runtime') or (media or {}).get('runtime') or 0
                record['cloud_resume'] = round(float(row.get('progress') or 0) * float(runtime) * .6, 2)
                break
    return record


def resume_position(record):
    item = record['item']
    saved = local_progress().get(media_key(item['kind'], item['tmdb_id'], item.get('season'), item.get('episode')))
    if saved is not None:
        return 0 if saved.get('completed') else saved.get('position', 0)
    return record.get('cloud_resume', 0)

def record_title(record):
    item, meta = record['item'], record['meta']
    if item['kind'] == 'episode':
        return '{} • S{:02d}E{:02d}'.format(meta.get('show_title') or item.get('show_title'), item['season'], item['episode'])
    return meta.get('title') or item.get('title', 'Titul')

def metadata_item(record, path=''):
    item, meta = record['item'], record['meta']
    label = record_title(record)
    if item['kind'] == 'episode' and meta.get('title'):
        label += ' – ' + meta['title']
    # The directory/resolver owns this new item until it is handed to Kodi.
    # Acquiring the GUI lock while VideoPlayer waits for a resolver can
    # deadlock the application (captured at setInfo on Kodi 21.2).
    li = xbmcgui.ListItem(label=label, path=path, offscreen=True)
    values = {'mediatype': 'tvshow' if item['kind'] == 'tv' else item['kind'],
              'title': meta.get('title') or item.get('title', ''), 'originaltitle': meta.get('original_title', ''),
              'plot': meta.get('plot', ''), 'year': int(meta.get('year') or item.get('year') or 0),
              'premiered': meta.get('premiered', ''), 'rating': float(meta.get('rating') or 0),
              'duration': int(meta.get('runtime') or 0) * 60, 'genre': meta.get('genres', [])}
    ids = {'tmdb': str(item['tmdb_id'])}
    if item.get('imdb_id'):
        ids['imdb'] = item['imdb_id']
    if item['kind'] == 'episode':
        values.update({'tvshowtitle': meta.get('show_title') or item.get('show_title', ''), 'season': item['season'], 'episode': item['episode']})
        ids = {'tmdb': str(meta.get('episode_tmdb_id') or ''), 'tvshow.tmdb': str(item['tmdb_id'])}
        if (meta.get('external_ids') or {}).get('imdb_id'):
            ids['imdb'] = meta['external_ids']['imdb_id']
    li.setInfo('video', values)
    li.setMimeType('video/x-matroska')
    tag = li.getVideoInfoTag()
    tag.setMediaType(values['mediatype'])
    tag.setTitle(values['title'])
    tag.setDuration(values['duration'])
    if item['kind'] == 'episode':
        tag.setTvShowTitle(values['tvshowtitle'])
        tag.setSeason(item['season'])
        tag.setEpisode(item['episode'])
    li.setUniqueIDs({k:v for k,v in ids.items() if v}, 'tmdb')
    art = core.artwork(meta)
    if PARAMS.get('action') == 'streaming_catalogue' and meta.get('poster_path'):
        import streaming
        poster = streaming.cached_poster(core, meta['poster_path'])
        if poster:
            art.update(poster=poster, thumb=poster, icon=poster)
    li.setArt(art)
    li.setProperty('family.kind', item['kind'])
    li.setProperty('family.tmdb_id', str(item['tmdb_id']))
    li.setProperty('tmdb_id', str(item['tmdb_id']))
    li.setProperty('tmdb_type', item['kind'])
    return li

def card_url(item):
    catalogue=1 if PARAMS.get('action')=='streaming_catalogue' else None
    return url('card', kind=item['kind'], tmdb_id=item['tmdb_id'], season=item.get('season'),
               episode=item.get('episode'), catalogue=catalogue)

def widget_action(item, command):
    item.setProperty('node.target_url','favourites://' + quote(command, safe='') + '/')

def add_record(record,paged=None):
    global MOVIE_STATUS
    li = metadata_item(record, card_url(record['item']))
    if record['item']['kind'] == 'movie':
        if MOVIE_STATUS is None:
            MOVIE_STATUS = movie_status()
        MOVIE_STATUS.decorate(li, record['item']['tmdb_id'])
    li.setProperty('IsPlayable', 'false')
    li.setProperty('OverrideInfotag', 'true')
    if paged:
        for name,value in paged.items():li.setProperty('family.paging.'+name,str(value))
    if PARAMS.get('action')=='streaming_catalogue':
        widget_action(li,'RunPlugin(' + card_url(record['item']) + ')')
    xbmcplugin.addDirectoryItem(HANDLE, card_url(record['item']), li, isFolder=False)

core.add_movie = add_record
core.add_tv = add_record
core.add_episode = add_record

def state_item(title, message, state, retry=None, key='', command=''):
    path = retry or url('message', title=title, message=message)
    li = xbmcgui.ListItem(label=title, label2=message, path=path, offscreen=True)
    li.setProperty('IsPlayable', 'false')
    li.setProperty('family.state', state)
    if state == 'account':li.setProperty('family.action', 'accounts')
    if key:li.setProperty('family.paging.key', key)
    if command:widget_action(li,command)
    li.setInfo('video', {'title': title, 'plot': message})
    li.setArt({'icon': 'DefaultInfo.png', 'thumb': 'DefaultInfo.png'})
    xbmcplugin.addDirectoryItem(HANDLE, path, li, isFolder=False)

def render_list(kind, source, personal=False):
    import paging

    category = 'Moje' if personal else {'movie': 'Filmy', 'tv': 'Seriály', 'episode': 'Epizody'}.get(kind, 'Kino')
    provider = paging.provider_id(source)
    widget = PARAMS.get('action')=='streaming_catalogue'
    retry_command = 'SetProperty(Family.Streaming.retry.'+kind+',1,Home)' if widget else ''
    if provider:
        import streaming
        category = ' · '.join(part for part in
                              (streaming.cached_name(core, kind, provider), category, streaming.ATTRIBUTION) if part)
    xbmcplugin.setPluginCategory(HANDLE, category)
    xbmcplugin.setContent(HANDLE, 'episodes' if kind == 'episode' else ('tvshows' if kind == 'tv' else 'movies'))
    try:
        family = sys.modules[__name__]
        value = paging.route(kind, source, personal)
        account = missing_list_account(value)
        if account:
            command = 'RunScript(script.michal.family.repair,accounts)'
            state_item('Připojit ' + account, 'Dokonči přihlášení. OK otevře průvodce účty.',
                       'account', url('accounts'), command=command)
            xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)
            return
        # The Home property is the single source of truth.  In particular, it
        # lets paging migrate stale pre-batch values before any network work.
        count = paging.requested(family, value)
        key = paging.key(value)
        heartbeat=HOME.getProperty('Family.Service.Heartbeat')
        background=paging.display_list(value) and heartbeat and time.time()-float(heartbeat)<10
        data = paging.display(family,value,count) if background else paging.ensure(family,value,count)
        if data is None:
            retry = url('retry',kind=kind,source=source,personal=int(personal))
            if HOME.getProperty(paging.display_property(value,'Error')):
                state_item('Zkusit znovu','Načtení seznamu se nepodařilo.','error',retry,key)
            else:
                state_item('Načítám seznam…','Položky se doplní automaticky.','loading',key=key)
            xbmcplugin.endOfDirectory(HANDLE,cacheToDisc=False)
            return
        records = data['records']
        paged = {'key': paging.key(value), 'more': 'true' if data['more'] else 'false', 'count': count}
        HOME.setProperty('Family.Paging.LastRequest', json.dumps({
            'key': paged['key'], 'count': count, 'items': len(records), 'more': data['more'],
            'source_pages': data['source_pages'],
        }))
        for record in records:
            add_record(record,paged)
        if data['more']:
            # A new footer has a new path. When the old footer is focused,
            # Kodi keeps that index on the first newly added title instead of
            # moving the selection to the new footer and skipping ten titles.
            path=url('list_more',key=paged['key'],after=count);li=xbmcgui.ListItem(label='Další tituly →' if records else 'Hledám dostupné tituly…',label2='Další výběr se doplní při procházení',path=path,offscreen=True)
            li.setProperty('IsPlayable','false');li.setProperty('family.action','list_more');li.setProperty('family.paging.key',paged['key'])
            li.setProperty('family.paging.more','true');li.setProperty('family.paging.count',str(count));li.setArt({'icon':'DefaultFolder.png','poster':'DefaultFolder.png'});li.setInfo('video',{'title':'Další tituly','plot':'Načtou se automaticky při procházení. OK zkusí načtení znovu.'})
            if widget:widget_action(li,'SetProperty(Family.Paging.Force,'+key+',Home)')
            xbmcplugin.addDirectoryItem(HANDLE,path,li,isFolder=False)
        if not records and not data['more']:
            message = ('V české nabídce služby pro tento typ teď nejsou žádné tituly.'
                       if provider else
                       'Vrať se tlačítkem Zpět nebo přidej titul do seznamu v Traktu.')
            state_item('Seznam je zatím prázdný',message,'empty',key=key,
                       command='SetProperty(Family.Streaming.back,1,Home)' if widget else '')
    except Exception as exc:
        title, message = classify_error(exc)
        retry = url('retry', kind=kind, source=source, personal=int(personal))
        key=paging.key(paging.route(kind,source,personal))
        # Never fall back to a legacy, unverified list. A temporary error is
        # preferable to displaying a title that cannot be played.
        state_item(title + '  •  Zkusit znovu',message,'error',retry,key,retry_command)
        HOME.setProperty('Family.LastListError', json.dumps({'kind': kind, 'source': source, 'class': type(exc).__name__}))
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)

def missing_list_account(value):
    import paging
    if value['personal'] or value['source'] in ('playback', 'next', 'recommendations', 'watchlist', 'history'):
        if not core.trakt_token_candidates():
            return 'Trakt'
    if paging.needs_availability(value):
        try:
            core.get_webshare_token()
        except RuntimeError:
            return 'Webshare'
    return ''

def find_sources(record):
    item, meta = record['item'], record['meta']
    key = 'family_sources_v3_' + media_key(item['kind'], item['tmdb_id'], item.get('season'), item.get('episode'))
    cached = core.read_cache_entry('list', key, 600)
    if cached is not None:
        return cached
    aliases = meta.get('show_titles') if item['kind'] == 'episode' else meta.get('titles')
    aliases = list(dict.fromkeys([v for v in [meta.get('title'), meta.get('original_title')] + (aliases or []) + [item.get('title')] if v]))
    # An episode title is never a substitute for a show identity.
    if item['kind'] == 'episode':
        aliases = list(dict.fromkeys([v for v in [meta.get('show_title'), meta.get('original_show_title')] + (meta.get('show_titles') or []) + [item.get('show_title')] if v]))
        aliases, search_titles = episode_source_titles(aliases)
    else:
        search_titles = aliases[:4]
    token = core.get_webshare_token()
    output, seen, queries = [], set(), []
    for alias in search_titles:
        query = '{} S{:02d}E{:02d}'.format(alias, item['season'], item['episode']) if item['kind'] == 'episode' else '{} {}'.format(alias, meta.get('year') or item.get('year') or '')
        queries.append(query)
        for candidate in core.webshare_search(query, token, limit=100):
            if candidate['ident'] in seen:
                continue
            seen.add(candidate['ident'])
            if valid_source(candidate, aliases, item['kind'], meta.get('year') or item.get('year', 0), item.get('season'), item.get('episode')):
                output.append(candidate)
        # Search the bounded alias list in full. Many unlabelled releases of
        # the original title must never suppress localized/dubbed releases.
    output.sort(key=rank_source)
    core.write_cache_entry('list', key, output)
    languages = [attributes(row['name'])['language'] for row in output]
    HOME.setProperty('Family.LastSources', json.dumps({'media': media_key(item['kind'], item['tmdb_id'], item.get('season'), item.get('episode')), 'accepted': len(output), 'inspected': len(seen), 'strict_episode': item['kind'] == 'episode', 'queries': queries, 'language_counts': {name: languages.count(name) for name in set(languages)}}))
    return output

def file_link(candidate, verify=True, _retried=False):
    token = core.get_webshare_token()
    yawsp = xbmcaddon.Addon(core.YAWSP_ID)
    device = yawsp.getSetting('duuid')
    if not device:
        device = str(uuid.uuid4())
        yawsp.setSetting('duuid', device)
    xml = core.xml_post(core.WEBSHARE_API + '/file_link/', {'ident': candidate['ident'], 'wst': token, 'download_type': 'video_stream', 'device_uuid': device}, timeout=12)
    if xml.findtext('status') != 'OK':
        try:
            account = core.xml_post(core.WEBSHARE_API + '/user_data/', {'wst': token}, timeout=8)
            xbmc.log('FamilyLink: account check status={} vip={}'.format(
                (account.findtext('status') or 'missing')[:30],
                account.findtext('vip') if account.findtext('status') == 'OK' else 'unknown'), xbmc.LOGWARNING)
            if verify and not _retried and account.findtext('status') != 'OK':
                core.refresh_webshare_token()
                xbmc.log('FamilyLink: renewed expired Webshare token', xbmc.LOGINFO)
                return file_link(candidate, verify=verify, _retried=True)
        except (RuntimeError, ValueError, OSError, HTTPError, URLError, TimeoutError) as exc:
            xbmc.log('FamilyLink: account check failed ({})'.format(type(exc).__name__), xbmc.LOGWARNING)
        xbmc.log('FamilyLink: file_link API rejected request (status={}, code={})'.format(
            (xml.findtext('status') or 'missing')[:30],
            (xml.findtext('code') or 'missing')[:40]), xbmc.LOGWARNING)
        raise RuntimeError('SOURCE_UNAVAILABLE')
    link = xml.findtext('link') or ''
    parts = urlsplit(link)
    host = (parts.hostname or '').lower()
    if parts.scheme not in ('https', 'http') or not any(host == domain or host.endswith('.' + domain) for domain in ('webshare.cz', 'wsfiles.cz')):
        xbmc.log('FamilyLink: unsupported source URL host', xbmc.LOGWARNING)
        raise RuntimeError('Unexpected source URL')
    headers = {'User-Agent': core.WEBSHARE_USER_AGENT, 'Referer': 'https://webshare.cz', 'Cookie': 'wst=' + token}
    if not verify:
        return link + '|' + urlencode(headers)
    request = Request(link, headers=dict(headers, Range='bytes=0-127', Connection='close'))
    try:
        with urlopen(request, timeout=7) as response:
            content_type = response.headers.get('Content-Type', '').lower()
            first = response.read(32)
            if len(first) < 8 or any(x in content_type for x in ('text/html', 'application/json', 'text/xml')):
                xbmc.log('FamilyLink: source probe returned non-video data (type={})'.format(content_type[:60]), xbmc.LOGWARNING)
                try:
                    account = core.xml_post(core.WEBSHARE_API + '/user_data/', {'wst': token}, timeout=8)
                    xbmc.log('FamilyLink: account check status={} vip={}'.format(
                        (account.findtext('status') or 'missing')[:30],
                        account.findtext('vip') if account.findtext('status') == 'OK' else 'unknown'), xbmc.LOGWARNING)
                    if not _retried and account.findtext('status') != 'OK':
                        core.refresh_webshare_token()
                        xbmc.log('FamilyLink: renewed expired Webshare token', xbmc.LOGINFO)
                        return file_link(candidate, verify=verify, _retried=True)
                except (RuntimeError, ValueError, OSError, HTTPError, URLError, TimeoutError) as exc:
                    xbmc.log('FamilyLink: account check failed ({})'.format(type(exc).__name__), xbmc.LOGWARNING)
                raise RuntimeError('SOURCE_UNAVAILABLE')
    except (HTTPError, URLError, TimeoutError) as exc:
        xbmc.log('FamilyLink: source probe failed (class={}, http={})'.format(
            type(exc).__name__, getattr(exc, 'code', '-')), xbmc.LOGWARNING)
        raise RuntimeError('SOURCE_UNAVAILABLE') from exc
    return link + '|' + urlencode(headers)

def inspect_sources(sources, cancel, progress):
    deadline=time.monotonic()+32
    jobs,results=queue.Queue(),queue.Queue()
    for index,candidate in enumerate(sources):
        jobs.put((index,candidate))
    def worker():
        while not cancel.is_set() and time.monotonic()<deadline:
            try:index,candidate=jobs.get_nowait()
            except queue.Empty:return
            key='family_tracks_v2_'+hashlib.sha256((candidate['ident']+':'+str(candidate.get('size'))).encode()).hexdigest()
            metadata=core.read_cache_entry('meta',key,7*86400)
            if metadata and metadata.get('state')!='verified' and time.time()-metadata.get('checked_at',0)>300:
                metadata=None
            if metadata is None:
                try:
                    uri=file_link(candidate,verify=False)
                    link,separator,encoded_headers=uri.partition('|')
                    headers={k:v[0] for k,v in parse_qs(encoded_headers).items()}
                    reader=HTTPReader(link,headers,candidate.get('size'),timeout=min(12,max(.2,deadline-time.monotonic())),cancel=cancel)
                    metadata=inspect_streams(reader)
                except Exception:
                    # No exception text or signed links enter persistent metadata.
                    metadata={'state':'unverified','tracks':[]}
                metadata['checked_at']=time.time()
                if not cancel.is_set():
                    core.write_cache_entry('meta',key,metadata)
            results.put((index,dict(candidate,streams=metadata)))
    for _ in range(min(3,len(sources))):
        threading.Thread(target=worker,daemon=True).start()
    found={}
    while len(found)<len(sources) and not cancel.is_set() and time.monotonic()<deadline:
        try:
            index,candidate=results.get(timeout=.15)
            found[index]=candidate
            progress['done']=len(found)
        except queue.Empty:
            pass
    cancel.set()
    output=[found.get(i,dict(candidate,streams={'state':'unverified','tracks':[]})) for i,candidate in enumerate(sources)]
    output.sort(key=rank_source)
    audio_languages={}
    for candidate in output:
        for lang in {t.get('language') or 'und' for t in candidate['streams'].get('tracks',[]) if t['type']=='audio'}:
            audio_languages[lang]=audio_languages.get(lang,0)+1
    HOME.setProperty('Family.LastTracks',json.dumps({'total':len(output),'verified':sum(s['streams'].get('state')=='verified' for s in output),'czech_audio':audio_languages.get('cs',0),'audio_languages':audio_languages}))
    HOME.setProperty('Family.LastTrackSample',json.dumps([{'name':candidate['name'],'streams':candidate['streams']} for candidate in output[:2]]))
    return output

def source_choice(sources, heading, ultra=None):
    selected=0
    while True:
        rows=[]
        for candidate in sources:
            rows.append(xbmcgui.ListItem(label=candidate.get('name') or 'Soubor bez názvu',label2=source_label(candidate)+'  •  '+source_summary(candidate)))
        if ultra:
            rows.append(xbmcgui.ListItem(label='4K – zobrazit další kvality ({})'.format(len(ultra))))
        details=len(rows)
        rows.append(xbmcgui.ListItem(label='Podrobnosti zvukových stop a titulků…'))
        choice=xbmcgui.Dialog().select(heading,rows,useDetails=True,preselect=selected)
        if choice<0:return None
        selected=choice
        if choice==details:
            index=xbmcgui.Dialog().select('Vyber soubor pro podrobnosti',[source_label(s) for s in sources+(ultra or [])])
            if index>=0:
                candidate=(sources+(ultra or []))[index]
                xbmcgui.Dialog().textviewer('Skutečné stopy souboru',candidate['name']+'\n\n'+'\n\n'.join(track_lines(candidate)))
        elif choice==len(sources) and ultra:
            candidate=source_choice(ultra,heading+' – 4K')
            if candidate:return candidate
        else:
            return sources[choice]

def select_source(record, sources_only=False):
    sources = async_work(lambda: find_sources(record), 'Hledám ověřené zdroje pro ' + record_title(record))
    if sources is None:
        return None
    if not sources:
        xbmcgui.Dialog().ok('Správný díl není dostupný' if record['item']['kind'] == 'episode' else 'Titul není dostupný', 'Pro tento titul nyní nemám ověřený zdroj. Můžeš to zkusit později nebo se vrátit tlačítkem Zpět.')
        return None
    cancel=threading.Event()
    progress={'done':0}
    sources=async_work(lambda:inspect_sources(sources,cancel,progress),'Čtu skutečné zvukové stopy a titulky…',cancel=cancel,progress_value=lambda:(progress['done'],len(sources)))
    if sources is None:return None
    regular = [s for s in sources if source_attributes(s)['resolution'] != 2160]
    ultra = [s for s in sources if source_attributes(s)['resolution'] == 2160]
    candidate=source_choice(regular,record_title(record) + ' – jazyk a kvalita',ultra)
    if not candidate:return None
    link = async_work(lambda: file_link(candidate), 'Ověřuji vybraný zdroj…')
    return (candidate, link) if link else None

def prepared_key(item):
    return hashlib.sha256(media_key(item['kind'], item['tmdb_id'], item.get('season'), item.get('episode')).encode()).hexdigest()[:24]

def start_playback(record, chosen, source_origin, resume=True):
    candidate, link = chosen
    item = record['item']
    key = prepared_key(item)
    # Kodi 21 can load an old, metadata-free bookmark over a resolved plugin
    # item. Resume identity is our stable media_key; each player session gets
    # a fresh path so its complete metadata remains authoritative.
    canonical = url('resolve', kind=item['kind'], tmdb_id=item['tmdb_id'], season=item.get('season'), episode=item.get('episode'), playback=time.time_ns())
    position = resume_position(record) if resume else 0
    source_info = source_attributes(candidate)
    context = {'record': record, 'link': link, 'created': time.time(), 'origin': source_origin, 'canonical': canonical, 'resume': position,
               'source': {'language': source_info['language'], 'quality': source_info['quality'], 'extension': os.path.splitext(candidate['name'])[1].lower()}}
    HOME.setProperty('Family.Prepared.' + key, json.dumps(context, ensure_ascii=True))
    if source_origin.get('search_snapshot'):
        HOME.setProperty('Family.Search.PlaybackReturn',str(source_origin['search_snapshot']))
    HOME.clearProperty('Family.ResumeApplied')
    HOME.setProperty('Family.PlaybackContext', json.dumps({k:v for k,v in context.items() if k != 'link'}, ensure_ascii=True))
    if HANDLE >= 0:
        # A poster can be invoked by Kodi's PlayMedia path. Resolve that
        # original request instead of starting a second nested player.
        deliver_resolved(context)
    else:
        rpc('Player.Open', {'item': {'file': canonical}})
        HOME.setProperty('Family.LastResolve', json.dumps({'stage': 'requested', 'handle': HANDLE}))


def deliver_pending_playback():
    global PENDING_PLAYBACK
    pending = PENDING_PLAYBACK
    PENDING_PLAYBACK = None
    if pending:
        start_playback(*pending[:3], resume=pending[3])
    elif HANDLE >= 0 and PARAMS.get('action') in ('card', 'play', 'search'):
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())


def deliver_resolved(prepared):
    li = metadata_item(prepared['record'], prepared['link'])
    li.setProperty('IsPlayable', 'true')
    li.setMimeType({'.mp4': 'video/mp4', '.m4v': 'video/mp4', '.avi': 'video/x-msvideo', '.ts': 'video/mp2t', '.m2ts': 'video/mp2t', '.webm': 'video/webm'}.get(prepared.get('source', {}).get('extension'), 'video/x-matroska'))
    li.setContentLookup(False)
    HOME.setProperty('Family.ManagedStartAt', str(time.time()))
    xbmcplugin.setResolvedUrl(HANDLE, True, li)
    tag = li.getVideoInfoTag()
    HOME.setProperty('Family.LastResolve', json.dumps({'stage': 'resolved', 'handle': HANDLE, 'resume': prepared.get('resume', 0), 'tag_type': tag.getMediaType(), 'tag_title': tag.getTitle()}))

def resolve():
    item = item_from_params(PARAMS)
    text = HOME.getProperty('Family.Prepared.' + prepared_key(item))
    try:
        prepared = json.loads(text)
        if time.time() - prepared['created'] > 90 or prepared['record']['item']['tmdb_id'] != item['tmdb_id']:
            raise RuntimeError('Prepared source expired')
        deliver_resolved(prepared)
    except Exception as exc:
        HOME.setProperty('Family.LastResolve', json.dumps({'stage': 'failed', 'class': type(exc).__name__, 'handle': HANDLE}))
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())

def show_card(record, source_origin=None):
    from browser import show
    return show(sys.modules[__name__], record, source_origin or origin())


def search():
    if PARAMS.get('entry')=='hub':
        if HOME.getProperty('Family.Search.Active') or (rpc('Player.GetActivePlayers') or []):
            return None
        restore=HOME.getProperty('Family.Search.Restore') or HOME.getProperty('Family.Search.PlaybackReturn')
        if restore:PARAMS['restore']=restore
    from discover_ui import show
    return show(sys.modules[__name__], origin(), PARAMS)

def streaming_menu(service=None, cards=False):
    import streaming

    try:
        services = streaming.providers(core)
    except Exception as exc:
        title, message = classify_error(exc)
        state_item(title + '  •  Zkusit znovu', message, 'error', url('streaming', service=service))
        xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)
        return
    if service:
        selected = next((entry for entry in services if entry['label'] == service), None)
        xbmcplugin.setPluginCategory(HANDLE, service + ' · ' + streaming.ATTRIBUTION)
        entries = [(label, url('list', kind=kind, source='provider_' + str(selected['ids'][kind])), '', {})
                   for kind, label in (('movie', 'Filmy'), ('tv', 'Seriály'))
                   if selected and kind in selected['ids']]
    else:
        xbmcplugin.setPluginCategory(HANDLE, 'Streamovací služby · ' + streaming.ATTRIBUTION)
        entries = [(entry['label'], url('streaming', service=entry['label']), entry['logo'], entry['ids'])
                   for entry in services]
    for label, path, logo, provider_ids in entries:
        item = xbmcgui.ListItem(label=label, label2='Předplatné · ČR · JustWatch', offscreen=True)
        if logo.startswith('/'):
            artwork = 'https://image.tmdb.org/t/p/w185' + logo
            item.setArt({'thumb': artwork, 'icon': artwork, 'poster': artwork})
        for kind, provider in provider_ids.items():
            item.setProperty('family.streaming.' + kind, str(provider))
        service_card = cards and bool(provider_ids)
        if service_card:
            item.setProperty('family.streaming.card', 'true')
            item.setProperty('IsPlayable', 'false')
            choice='|'.join((label,str(provider_ids.get('movie','')),str(provider_ids.get('tv',''))))
            widget_action(item,'SetProperty(Family.Streaming.request,'+choice+',Home)')
        xbmcplugin.addDirectoryItem(HANDLE, path, item, isFolder=not service_card)
    if not entries:
        state_item('Nabídka není k dispozici', streaming.ATTRIBUTION, 'empty')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)

def route():
    core.ensure_dirs()
    action = PARAMS.get('action', '')
    if action in ('list', 'recommendations_movies', 'personal'):
        kind = PARAMS.get('kind', 'movie')
        source = PARAMS.get('source', 'recommendations')
        render_list(kind, source, action == 'personal')
    elif action in ('card', 'play'):
        source_origin = origin()
        if PARAMS.get('catalogue')=='1':
            source_origin['watch_catalog']=True
        item = item_from_params(PARAMS)
        record = async_work(lambda: record_for(item), 'Načítám kartu titulu…')
        if record:
            show_card(record, source_origin)
    elif action == 'resolve':
        resolve()
    elif action == 'search':
        search()
    elif action == 'streaming':
        streaming_menu(PARAMS.get('service'), cards=PARAMS.get('view') == 'cards')
    elif action == 'streaming_catalogue':
        import paging

        kind = PARAMS.get('kind', '')
        source = 'provider_' + PARAMS.get('provider', '')
        if kind in ('movie', 'tv') and paging.provider_id(source):
            render_list(kind, source)
        else:
            xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)
    elif action == 'list_more':
        import paging
        value=paging.from_key(PARAMS.get('key',''))
        HOME.setProperty('Family.Paging.Force',paging.key(value))
    elif action == 'diagnostic_cancel':
        def delayed():
            time.sleep(3)
            return True
        result = async_work(delayed, 'Zkouška zrušení načítání – stiskni Zpět')
        HOME.setProperty('Family.CancelTest', 'cancelled' if result is None else 'completed')
    elif action == 'catalog':
        kind = PARAMS.get('kind', 'movie')
        section = PARAMS.get('section', 'genres')
        if kind not in ('movie', 'tv') or section not in ('genres', 'upcoming', 'now_playing', 'airing_today', 'on_the_air'):
            raise ValueError('Unknown catalog')
        if section == 'genres':
            import paging
            try:refresh=json.loads(HOME.getProperty('Family.Paging.GenreRefresh') or '{}')
            except ValueError:refresh={}
            HOME.clearProperty('Family.Paging.GenreRefresh')
            active=xbmc.getInfoLabel('ListItem.Property(family.paging.key)')
            value=None
            if refresh.get('key')==active and time.time()-refresh.get('time',0)<10:
                try:candidate=paging.from_key(active)
                except ValueError:candidate=None
                if candidate and candidate['kind']==kind and candidate['source'].startswith('genre_'):value=candidate
            if value:
                source=value['source']
            else:
                genres = core.tmdb_request('/genre/' + kind + '/list').get('genres', [])
                choice = xbmcgui.Dialog().select('Žánry', [g['name'] for g in genres])
                if choice < 0:
                    xbmcplugin.endOfDirectory(HANDLE, succeeded=False, cacheToDisc=False)
                    return
                source='genre_'+str(int(genres[choice]['id']))
        else:
            source=section
        render_list(kind,source)
    elif action == 'message':
        xbmcgui.Dialog().ok(PARAMS.get('title', 'Rodinné kino'), PARAMS.get('message', ''))
    elif action == 'retry':
        import paging
        value = paging.route(PARAMS.get('kind', 'movie'), PARAMS.get('source', 'watchlist'), PARAMS.get('personal') == '1')
        result = async_work(lambda: paging.ensure(sys.modules[__name__], value), 'Obnovuji seznam…')
        if result is not None:
            xbmc.executebuiltin('Container.Refresh')
    elif action == 'accounts':
        xbmc.executebuiltin('RunScript(script.michal.family.repair,accounts)')
    elif action == 'service':
        xbmc.executebuiltin('RunScript(script.michal.family.repair,menu)')
    else:
        for label, kind, source in [('Pokračovat – filmy', 'movie', 'playback'), ('Další epizody', 'episode', 'next'), ('Filmy', 'movie', 'recommendations'), ('Seriály', 'tv', 'recommendations')]:
            li = xbmcgui.ListItem(label=label)
            xbmcplugin.addDirectoryItem(HANDLE, url('list', kind=kind, source=source), li, isFolder=True)
        xbmcplugin.addDirectoryItem(HANDLE, url('streaming'), xbmcgui.ListItem(label='Streamovací služby'), isFolder=True)
        state_item('Hledat', 'Film nebo seriál', 'action', url('search'))
        state_item('Servis', 'Kontrola sestavy a zálohy', 'action', url('service'))
        xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)
