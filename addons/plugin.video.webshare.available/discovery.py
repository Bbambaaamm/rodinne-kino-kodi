"""Catalogue discovery with bounded requests, explicit filters and local snapshots."""
import copy
import datetime
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
import searching as search

MOODS=[
    ('comedy','Chci se zasmát','Komedie',{'movie':'35','tv':'35'}),
    ('thriller','Něco napínavého','Thrillery a krimi',{'movie':'53|80|9648','tv':'80|9648'}),
    ('adventure','Dobrodružství','Výpravy a velké příběhy',{'movie':'12','tv':'10759'}),
    ('scifi','Sci-fi a fantasy','Jiné světy',{'movie':'878|14','tv':'10765'}),
    ('family','Pro rodinu','Rodinné a animované',{'movie':'10751|16','tv':'10751|16'}),
    ('documentary','Ze skutečného života','Dokumenty',{'movie':'99','tv':'99'})]
PERIODS=[('','Kdykoliv'),('recent','Posledních pět let'),('2020s','2020 a novější'),('2010s','2010–2019'),('2000s','2000–2009'),('1990s','1990–1999'),('1980s','1980–1989'),('older','Před rokem 1980')]
DURATIONS=[('','Libovolná délka'),('short','Do 100 minut'),('medium','100–140 minut'),('long','Nad 140 minut')]

def root_record():return {'item':{'kind':'search','title':'Hledat a objevovat'},'meta':{'title':'Hledat a objevovat'}}

def spec(**changes):
    result={'mode':'home','query':'','kind':'all','mood':'','period':'','duration':'','person':0,'reference':None}
    result.update(changes)
    result['kind']=result['kind'] if result['kind'] in ('movie','tv') else 'all'
    if result['duration']:result['kind']='movie'
    return result

def bounds(period):
    today=datetime.date.today();end=today.isoformat()
    if not period:return None,end
    if period=='recent':return '{}-01-01'.format(today.year-4),end
    if period=='older':return None,'1979-12-31'
    if period.startswith('year:'):
        year=int(period[5:]);return '{}-01-01'.format(year),min(end,'{}-12-31'.format(year))
    year=int(period[:4]);return '{}-01-01'.format(year),min(end,'{}-12-31'.format(year+9))

def period_label(value):
    if value.startswith('year:'):return value[5:]
    return dict(PERIODS).get(value,'Kdykoliv')

def description(value):
    labels=[]
    if value.get('kind') in ('movie','tv'):labels.append('Filmy' if value['kind']=='movie' else 'Seriály')
    if value.get('mood'):labels.append(next((m[2] for m in MOODS if m[0]==value['mood']),''))
    if value.get('period'):labels.append(period_label(value['period']))
    if value.get('duration'):labels.append(dict(DURATIONS).get(value['duration'],''))
    return ' · '.join(filter(None,labels))

def filtered(rows,value):
    start,end=bounds(value.get('period',''));out=[];seen=set()
    mood=next((m for m in MOODS if m[0]==value.get('mood')),None)
    for row in rows:
        kind=row.get('media_type');identity=(kind,row.get('id'))
        if kind not in ('movie','tv','person') or row.get('adult') or not row.get('id') or identity in seen:continue
        if kind=='person':
            if value.get('mode')!='query':continue
        else:
            if value.get('kind')!='all' and kind!=value['kind']:continue
            date=row.get('release_date') or row.get('first_air_date') or ''
            if date and date>end and (value.get('mode') not in ('query','person') or value.get('period')):continue
            if start and date<start:continue
            if value.get('period') and not date:continue
            if mood:
                genres={int(g) for g in mood[3][kind].split('|')}
                if not genres.intersection(row.get('genre_ids') or []):continue
        seen.add(identity);out.append(row)
    return out

def fetch(core,value,page=1,cancel=None):
    value=spec(**value);page=max(1,min(500,int(page)))
    key=core.hashed_name(repr(('discover-v3-webshare',value,page)))
    cached=core.read_cache_entry('search',key,600)
    if cached is not None:return cached
    stopped=lambda:cancel is not None and cancel.is_set()
    if value['mode'] in ('query','person'):
        query=value['query']
        if value.get('period','').startswith('year:') and search.parse(query)['year'] is None:query+=' '+value['period'][5:]
        backend_kind='all' if value['mode']=='query' and search.parse(query)['year'] is None else value['kind']
        payload=search.fetch(core,query,backend_kind,page,value.get('person',0),cancel)
        result=dict(payload,rows=filtered(payload['rows'],value))
    else:
        kinds=(value['kind'],) if value['kind']!='all' else ('movie','tv')
        if value['mode']=='related':kinds=(value['reference']['kind'],)
        def one(kind):
            if stopped():return [],False
            params={'include_adult':'false','page':page,'language':'cs-CZ'}
            if value['mode']=='related':
                path='/{}/{}/recommendations'.format(kind,int(value['reference']['id']))
            else:
                path='/discover/'+kind;params.update(sort_by='popularity.desc',**{'vote_count.gte':50 if kind=='movie' else 20})
                mood=next((m for m in MOODS if m[0]==value['mood']),None)
                if mood:params['with_genres']=mood[3][kind]
                lo,hi=bounds(value['period']);date='primary_release_date' if kind=='movie' else 'first_air_date'
                if lo:params[date+'.gte']=lo
                params[date+'.lte']=hi
                if kind=='movie':params['include_video']='false'
                if value['duration']=='short':params.update(**{'with_runtime.gte':10,'with_runtime.lte':100})
                elif value['duration']=='medium':params.update(**{'with_runtime.gte':100,'with_runtime.lte':140})
                elif value['duration']=='long':params['with_runtime.gte']=141
            data=core.tmdb_request(path,params)
            return [dict(r,media_type=kind) for r in data.get('results',[])],page<min(500,int(data.get('total_pages') or 0))
        if len(kinds)==2:
            with ThreadPoolExecutor(max_workers=2) as pool:parts=list(pool.map(one,kinds))
        else:parts=[one(kinds[0])]
        # Both content types remain represented; popularity scales differ.
        rows=[]
        for i in range(max((len(p[0]) for p in parts),default=0)):
            for items,_ in parts:
                if i<len(items):rows.append(items[i])
        result={'rows':search.available(core,filtered(rows,value),cancel),'more':any(p[1] for p in parts),'next':page+1,'similar':False}
    if not stopped():core.write_cache_entry('search',key,result)
    return result

def credits(core,record):
    item=record['item'];kind='tv' if item['kind'] in ('tv','episode') else 'movie';ident=int(item['tmdb_id'])
    key='credits_{}_{}'.format(kind,ident);cached=core.read_cache_entry('search',key,86400)
    if cached is not None:return cached
    data=core.tmdb_request('/{}/{}/{}'.format(kind,ident,'aggregate_credits' if kind=='tv' else 'credits'))
    result=[];seen=set()
    for group in ('cast','crew'):
        for row in data.get(group,[]):
            jobs={j.get('job') for j in row.get('jobs',[])}|{row.get('job')}
            if group=='crew' and not jobs.intersection(('Director','Creator','Writer','Screenplay')):continue
            if not row.get('id') or row['id'] in seen:continue
            seen.add(row['id']);roles=row.get('roles') or []
            role=row.get('character') or (roles[0].get('character') if roles else '')
            label='Herec' if group=='cast' else 'Režie' if 'Director' in jobs else 'Tvůrce'
            result.append({'id':row['id'],'name':row.get('name',''),'profile_path':row.get('profile_path'),'description':label+(' · '+role if role else '')})
            if len(result)>=40:break
    core.write_cache_entry('search',key,result);return result

def save_snapshot(core,frames):
    keys=('mode','query','kind','mood','period','duration','person','reference','selected','focus','rows','more','next','similar','loaded_pages')
    data=[]
    for frame in frames:
        if frame.get('page')!='search':continue
        value={k:copy.deepcopy(frame[k]) for k in keys if k in frame}
        value.update(page='search',record=root_record(),root_record=root_record())
        data.append(value)
    token=uuid.uuid4().hex
    core.write_json(os.path.join(core.PROFILE,'search-session.json'),{'token':token,'created':time.time(),'frames':data})
    return token

def restore_snapshot(core,token):
    saved=core.read_json(os.path.join(core.PROFILE,'search-session.json'),{}) or {}
    if saved.get('token')!=token or time.time()-saved.get('created',0)>172800:return None
    frames=saved.get('frames')
    if not isinstance(frames,list) or not frames:return None
    return frames
