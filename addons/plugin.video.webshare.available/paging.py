"""Stable, growing household lists. Network work never touches native controls."""
import contextlib
import copy
import hashlib
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs,urlsplit,urlencode,quote

BATCH=10
MAX_ITEMS=10000
TTL=600
DISPLAY_TTL=86400
HOME_LISTS=(('movie','playback'),('episode','playback'),('episode','next'),
            ('movie','recommendations'),('tv','recommendations'))
MOVIES={'playback','recommendations','watchlist','trending','popular','now_playing','top_rated','upcoming'}
SHOWS={'recommendations','watchlist','trending','popular','airing_today','on_the_air'}

def provider_id(source):
    if not source.startswith('provider_'):
        return None
    suffix = source[len('provider_'):]
    if 0 < len(suffix) <= 8 and suffix.isascii() and suffix.isdigit():
        return int(suffix) or None
    return None

def route(kind,source,personal=False):
    genre=source.startswith('genre_') and source[6:].isdigit() and int(source[6:])>0
    catalogue = kind in ('movie', 'tv') and (genre or provider_id(source) is not None)
    valid=(kind in ('movie','tv') and source in ('watchlist','collection','history') or kind=='both' and source=='history') if personal else (kind=='movie' and source in MOVIES or kind=='tv' and source in SHOWS or catalogue or kind=='episode' and source in ('playback','next'))
    if not valid:raise ValueError('Unsupported household list')
    return {'kind':kind,'source':source,'personal':bool(personal)}

def key(value):return ('personal' if value['personal'] else 'list')+'_'+value['kind']+'_'+value['source']
def from_key(value):
    parts=value.split('_',2)
    if len(parts)!=3 or parts[0] not in ('personal','list'):raise ValueError('Unsupported household key')
    return route(parts[1],parts[2],parts[0]=='personal')
def count_property(value):return 'Family.Paging.Count.'+key(value)
def display_list(value):return not value['personal'] and (value['kind'],value['source']) in HOME_LISTS
def display_property(value,field):return 'Family.Paging.Display.'+field+'.'+key(value)
def revision(f,value):return f.HOME.getProperty('Family.Paging.Revision') if value['source'] in ('playback','next','history') else ''
def cache_key(f,value,epoch=None):return 'v1_'+key(value)+'_'+hashlib.sha1((revision(f,value) if epoch is None else epoch).encode()).hexdigest()[:12]
def requested(f,value):
    try:amount=int(f.HOME.getProperty(count_property(value)) or BATCH)
    except ValueError:amount=BATCH
    return max(BATCH,min(MAX_ITEMS,amount))

def _list_binding(address):
    parts=urlsplit(address)
    if parts.scheme!='plugin' or parts.netloc!='plugin.video.webshare.available':return None
    params={k:v[0] for k,v in parse_qs(parts.query).items()}
    if params.get('action') not in ('list','personal'):return None
    value=route(params.get('kind',''),params.get('source',''),params['action']=='personal')
    for field in ('count','rev','refresh'):params.pop(field,None)
    params['infinite']='1'
    return value, params

def decorate_path(address):
    binding = _list_binding(address)
    if binding is None:return None
    value, params = binding
    result='plugin://plugin.video.webshare.available/?'+urlencode(params)+'&count=$INFO[Window(Home).Property('+count_property(value)+')]'
    if value['source'] in ('playback','next','history'):result+='&rev=$INFO[Window(Home).Property(Family.Paging.Revision)]'
    if display_list(value):result+='&refresh=$INFO[Window(Home).Property('+display_property(value,'Version')+')]'
    return result

def spotlight_path(f, address):
    binding = _list_binding(address)
    if binding is None:return None
    value, params = binding
    params['count'] = str(requested(f, value))
    epoch = revision(f, value)
    if epoch:params['rev'] = epoch
    if display_list(value):params['refresh']=f.HOME.getProperty(display_property(value,'Version'))
    return 'plugin://plugin.video.webshare.available/?' + urlencode(params)

def read(f,value,epoch=None):return f.core.read_cache_entry('paging',cache_key(f,value,epoch),TTL)
def usable(state,count):
    return state and (len(state['records'])>=count or state['source_done'] and not state['pending'])

def display(f,value,count):
    current=read(f,value)
    if usable(current,count):
        return view(current,count)
    f.HOME.setProperty(display_property(value,'Wanted'),str(count))
    previous=(current or f.core.read_cache_entry('paging',cache_key(f,value),DISPLAY_TTL)
              or f.core.read_cache_entry('paging-display',key(value),DISPLAY_TTL))
    if previous is None:
        return None
    data=view(previous,count)
    if value['source'] in ('playback','next'):
        completed={key for key,record in f.local_progress().items() if record.get('completed')}
        data['records']=[record for record in data['records'] if identity(f,record['item']) not in completed]
    return data if data['records'] else None

def write(f,value,data,epoch=None):
    filename=f.core.cache_path('paging',cache_key(f,value,epoch));os.makedirs(os.path.dirname(filename),exist_ok=True)
    temp=filename+'.'+uuid.uuid4().hex+'.new'
    try:
        with open(temp,'w',encoding='utf-8') as stream:json.dump({'ts':int(time.time()),'data':data},stream,ensure_ascii=False)
        os.replace(temp,filename)
    finally:
        if os.path.exists(temp):os.remove(temp)

@contextlib.contextmanager
def lock(f,value,cancel,epoch=None):
    filename=f.core.cache_path('paging',cache_key(f,value,epoch))+'.lock';os.makedirs(os.path.dirname(filename),exist_ok=True)
    token=uuid.uuid4().hex;until=time.monotonic()+40
    while True:
        if cancel and cancel.is_set():raise InterruptedError('List request cancelled')
        try:
            descriptor=os.open(filename,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
            with os.fdopen(descriptor,'w') as stream:stream.write(token)
            break
        except FileExistsError:
            try:
                if time.time()-os.path.getmtime(filename)>300:os.remove(filename);continue
            except FileNotFoundError:continue
            if time.monotonic()>until:raise TimeoutError('List request already running')
            time.sleep(.1)
    try:yield
    finally:
        try:
            with open(filename) as stream:owned=stream.read()==token
            if owned:os.remove(filename)
        except FileNotFoundError:pass

def identity(f,item):return f.media_key(item['kind'],item['tmdb_id'],item.get('season'),item.get('episode'))
def needs_availability(value):
    return (not value['personal'] and not value['source'].startswith(('genre_', 'provider_'))
            and value['source'] not in ('upcoming','on_the_air'))

def initial():return {'records':[],'pending':[],'page':1,'source_done':False,'seen':[],'signatures':[],'local_added':False}

def changed_show(f):
    show,_, stamp=f.HOME.getProperty('Family.Paging.ChangedShow').partition(':')
    return show,stamp

def fetch_page(f,value,state):
    core=f.core;kind=value['kind'];source=value['source'];personal=value['personal'];page=state['page'];more=False;numbered=False
    if source=='next':
        data=core.trakt_request('/sync/watched/shows',{'extended':'full'})
        recent,_=changed_show(f)
        data=sorted(data,key=lambda row:(
            bool(recent and str((row.get('show',{}).get('ids') or {}).get('tmdb'))==recent),
            row.get('last_watched_at') or ''
        ),reverse=True)
        items=[{'kind':'next_raw','row':row} for row in data]
    elif source=='collection':
        data=core.trakt_request('/sync/collection/'+('movies' if kind=='movie' else 'shows'),{'extended':'full'})
        items=[core.normalise_trakt_media(row,kind) for row in data]
    elif source in ('playback','recommendations','watchlist','history'):
        if source=='playback':path='/sync/playback/'+('movies' if kind=='movie' else 'episodes')
        elif source=='recommendations':path='/recommendations/'+('movies' if kind=='movie' else 'shows')
        elif source=='watchlist':path='/sync/watchlist/'+('movies' if kind=='movie' else 'shows')
        else:path='/sync/history'+('' if kind=='both' else '/movies' if kind=='movie' else '/shows')
        data,pagination=core.trakt_page(path,{'extended':'full','page':page,'limit':100})
        numbered='page-count' in pagination
        more=page<int(pagination['page-count']) if 'page-count' in pagination else len(data)>=100
        items=[f.episode_item(row) if row.get('episode') else dict(core.normalise_trakt_media(row,kind if kind in ('movie','tv') else 'movie'),progress=row.get('progress',0)) for row in data]
    else:
        paths={('movie','trending'):'/trending/movie/week',('movie','popular'):'/movie/popular',('movie','now_playing'):'/movie/now_playing',('movie','top_rated'):'/movie/top_rated',('movie','upcoming'):'/movie/upcoming',('tv','trending'):'/trending/tv/week',('tv','popular'):'/tv/popular',('tv','airing_today'):'/tv/airing_today',('tv','on_the_air'):'/tv/on_the_air'}
        params={'page':page,'region':'CZ'}
        provider = provider_id(source)
        if provider is not None:
            path = '/discover/' + kind
            params.update(watch_region='CZ', with_watch_providers=provider,
                          with_watch_monetization_types='flatrate', include_adult='false',
                          sort_by='popularity.desc')
        elif source.startswith('genre_'):path='/discover/'+kind;params['with_genres']=int(source[6:]);params['include_adult']='false'
        else:path=paths[kind,source]
        data=core.tmdb_request(path,params)
        numbered=True
        more=page<min(500,int(data.get('total_pages') or 0))
        items=[]
        for row in data.get('results',[]):
            item=core.normalise_tmdb_media(row,kind)
            if provider is not None:
                item['catalogue_meta']={
                    'title':item.get('title',''),'year':item.get('year',0),'premiered':item.get('premiered',''),
                    'poster_path':row.get('poster_path'),'backdrop_path':row.get('backdrop_path'),
                    'plot':row.get('overview') or '', 'rating':row.get('vote_average') or 0,
                }
            items.append(item)
    # An endpoint that ignores page must never repeat its first page forever.
    signature=hashlib.sha256(json.dumps(items,sort_keys=True).encode()).hexdigest()
    if signature in state['signatures'] and not numbered:items=[];more=False
    else:state['signatures'].append(signature)
    if source=='playback' and not state['local_added']:
        local=sorted(f.local_progress().values(),key=lambda row:row.get('updated',0),reverse=True)
        items=[row['item'] for row in local if row.get('kind')==kind and not row.get('completed') and row.get('position',0)>=15]+items
        state['local_added']=True
    state['page']=page+1;state['source_done']=not more;state['pending'].extend(items)

def next_episode(f,item):
    row=item['row'];show=row.get('show') or {};ids=show.get('ids') or {};slug=ids.get('slug') or ids.get('trakt')
    if not slug:return None
    stamp=row.get('last_watched_at') or ''
    recent,revision=changed_show(f)
    changed=revision if recent==str(ids.get('tmdb')) else ''
    cache_id='next_'+hashlib.sha256((str(slug)+'|'+stamp+'|'+changed).encode()).hexdigest()[:24]
    data=f.core.read_cache_entry('source',cache_id,TTL) if stamp else None
    if data is None:
        data=f.core.trakt_request('/shows/'+quote(str(slug),safe='')+'/progress/watched',{'hidden':'false','specials':'false','count_specials':'false','extended':'full'})
        if stamp:
            f.core.write_cache_entry('source',cache_id,data)
    ep=data.get('next_episode') or {}
    if not ep:return None
    # Compare full dates in the same format rather than choosing an unaired episode.
    import datetime
    aired=ep.get('first_aired') or ''
    if aired:
        try:
            if datetime.datetime.fromisoformat(aired.replace('Z','+00:00'))>datetime.datetime.now(datetime.timezone.utc):return None
        except ValueError:pass
    return {'kind':'episode','tmdb_id':ids.get('tmdb'),'trakt_id':ids.get('trakt'),'imdb_id':ids.get('imdb'),'show_title':show.get('title',''),'show_year':show.get('year',0),'season':ep.get('season',0),'episode':ep.get('number',0),'episode_title':ep.get('title',''),'premiered':aired}

def process(f,value,item,seen,token,local):
    if item.get('kind')=='next_raw':item=next_episode(f,item)
    if not item or not item.get('tmdb_id'):return None,None
    ident=identity(f,item)
    if ident in seen:return ident,None
    if value['source'] in ('playback','next') and (local.get(ident) or {}).get('completed'):return ident,None
    status=None
    if needs_availability(value):
        status=f.core.check_availability(item['kind'],item,token)
        if status.get('state')!='AVAILABLE':return ident,None
    meta=item.get('catalogue_meta') or f.core.fetch_meta(item['kind'],item)
    if item['kind']=='movie' and value['source']=='watchlist' and not value['personal']:
        date=meta.get('premiered') or item.get('premiered') or ''
        if date and date[:10]>time.strftime('%Y-%m-%d'):return ident,None
    record={'item':item,'meta':meta}
    if status is not None:record['availability']=status
    return ident,record

def view(state,count):
    return {'records':state['records'][:count],'more':count<MAX_ITEMS and (len(state['records'])>count or bool(state['pending']) or not state['source_done']),'requested':count,'cached_records':len(state['records']),'source_pages':state['page']-1}

def ensure(f,value,count=None,cancel=None):
    value=route(**value);epoch=revision(f,value);count=min(MAX_ITEMS,count or requested(f,value));state=read(f,value,epoch)
    if usable(state,count):return view(state,count)
    with lock(f,value,cancel,epoch):
        state=read(f,value,epoch) or initial()
        token=f.core.get_webshare_token() if needs_availability(value) else None
        local=f.local_progress() if value['source'] in ('playback','next') else {};scanned=0;deadline=time.monotonic()+25
        while len(state['records'])<count and scanned<64 and time.monotonic()<deadline:
            if cancel and cancel.is_set():break
            if not state['pending']:
                if state['source_done']:break
                fetch_page(f,value,state)
                if not state['pending']:continue
            batch=state['pending'][:min(4,max(1,count-len(state['records'])))];seen=set(state['seen'])
            with ThreadPoolExecutor(max_workers=min(4,len(batch))) as pool:
                results=list(pool.map(lambda item:process(f,value,item,seen,token,local),batch))
            if cancel and cancel.is_set():break
            for ident,record in results:
                if ident and ident not in seen:
                    seen.add(ident)
                    if record:state['records'].append(record)
            state['seen']=list(seen);del state['pending'][:len(batch)];scanned+=len(batch);write(f,value,state,epoch)
        write(f,value,state,epoch)
        if display_list(value) and epoch==revision(f,value):
            f.core.write_cache_entry('paging-display',key(value),state)
        return view(state,count)
