"""Small, bounded catalogue search. No availability or audio is inferred here."""
import datetime
import difflib
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor


def normal(value):
    return ' '.join(re.sub(r'[^\w]+', ' ', ''.join(c for c in unicodedata.normalize('NFKD', str(value).casefold()) if not unicodedata.combining(c))).split())


def parse(query, kind='all'):
    text=' '.join(str(query).strip().split())[:120]
    parts=text.split(' ',1)
    prefixes={'film':'movie','filmy':'movie','movie':'movie','serial':'tv','serialy':'tv','tv':'tv'}
    if len(parts)==2 and normal(parts[0]) in prefixes:
        kind=prefixes[normal(parts[0])];text=parts[1]
    year=None
    match=re.search(r'\s+\(?((?:19|20)\d{2})\)?$',text)
    if match and 1900<=int(match[1])<=datetime.date.today().year+3:
        year=int(match[1]);text=text[:match.start()].rstrip()
    return {'text':text,'year':year,'kind':kind if kind in ('movie','tv') else 'all'}


def title(row):return row.get('title') or row.get('name') or ''
def original(row):return row.get('original_title') or row.get('original_name') or ''
def year(row):return (row.get('release_date') or row.get('first_air_date') or '')[:4]


def rank(rows, spec, person=False):
    unique={};query=normal(spec['text'])
    for row in rows:
        kind=row.get('media_type')
        if kind not in ('movie','tv','person') or not row.get('id') or row.get('adult'):continue
        if kind=='person':
            names=normal(title(row)).split();tokens=query.split()
            matches=normal(title(row))==query or (len(query)>=3 and all(any(n.startswith(t) for n in names) for t in tokens))
            if person or spec['kind']!='all' or spec['year'] or not matches:continue
        else:
            if spec['kind']!='all' and kind!=spec['kind']:continue
            if spec['year'] and year(row)!=str(spec['year']):continue
        unique.setdefault((kind,row['id']),row)
    def score(row):
        names=[normal(title(row)),normal(original(row))]
        exact=query in names
        tokens=max((sum(t in n.split() for t in query.split())/max(1,len(query.split())) for n in names),default=0)
        similar=max(difflib.SequenceMatcher(None,query,n).ratio() for n in names)
        # Filmography is ranked by popularity, rather than similarity to a person's name.
        if person:return (0,0,float(row.get('vote_count') or 0),float(row.get('popularity') or 0),year(row))
        return (int(exact),tokens,similar,float(row.get('popularity') or 0),year(row))
    ordered=sorted(unique.values(),key=score,reverse=True);people=0;result=[]
    for row in ordered:
        if row['media_type']=='person':
            people+=1
            if people>3:continue
        result.append(row)
    return result


def available(core, rows, cancel=None):
    """Keep people plus only media with a confirmed Webshare video."""
    stopped=lambda:cancel is not None and cancel.is_set()
    token=core.get_webshare_token()
    media=[]
    for index,row in enumerate(rows):
        if row.get('media_type') not in ('movie','tv'):
            continue
        media.append((index, row, {'kind':row['media_type'],'tmdb_id':row['id'],
                                  'title':title(row),'year':int(year(row) or 0)}))
    statuses={}
    with ThreadPoolExecutor(max_workers=min(4,max(1,len(media)))) as pool:
        futures=[(index,pool.submit(core.check_availability,item['kind'],item,token)) for index,_,item in media]
        for index,future in futures:
            if stopped():break
            try:statuses[index]=future.result().get('state')=='AVAILABLE'
            except Exception:statuses[index]=False
    return [row for index,row in enumerate(rows)
            if row.get('media_type')=='person' or statuses.get(index,False)]


def fetch(core,query,kind='all',page=1,person_id=0,cancel=None):
    spec=parse(query,kind);page=max(1,int(page));person_id=int(person_id or 0)
    key=core.hashed_name(repr(('v5-webshare',spec,page,person_id)))
    cached=core.read_cache_entry('search',key,600)
    if cached is not None:return cached
    def stopped():return cancel is not None and cancel.is_set()
    def request(path,params):
        if stopped():return {}
        return core.tmdb_request(path,params)
    similar=False;more=False;next_page=page+1
    if person_id:
        # Credits are returned as one complete response. Reuse that snapshot
        # for subsequent pages and filters so their ordering stays consistent.
        credits_key='person_credits_v1_'+str(person_id)
        data=core.read_cache_entry('search',credits_key,600)
        if data is None:
            data=request('/person/{}/combined_credits'.format(person_id),{})
            if not stopped():core.write_cache_entry('search',credits_key,data)
        rows=list(data.get('cast',[]))+[r for r in data.get('crew',[]) if r.get('job') in ('Director','Creator','Screenplay','Writer')]
        rows=rank(rows,spec,person=True)
        more=len(rows)>page*40;rows=rows[(page-1)*40:page*40]
    else:
        def lookup(text):
            kinds=('movie','tv') if spec['year'] and spec['kind']=='all' else (spec['kind'],)
            def one(k):
                params={'query':text,'page':page,'include_adult':'false'}
                if spec['year'] and k=='movie':params['primary_release_year']=spec['year']
                if spec['year'] and k=='tv':params['first_air_date_year']=spec['year']
                data=request('/search/'+('multi' if k=='all' else k),params)
                items=data.get('results',[])
                if k!='all':items=[dict(r,media_type=k) for r in items]
                return items,int(data.get('total_pages') or 0)>page
            if len(kinds)==2:
                with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(one,kinds))
            else:responses=[one(kinds[0])]
            return [r for items,_ in responses for r in items],any(m for _,m in responses)
        raw,more=lookup(spec['text']);rows=rank(raw,spec)
        if not rows and page==1 and len(spec['text'])>=4 and not stopped():
            words=spec['text'].split()
            alternative=max(words,key=len) if len(words)>1 else spec['text'][:max(3,len(spec['text'])-2)]
            if alternative!=spec['text']:
                raw,_=lookup(alternative);rows=rank(raw,spec);similar=bool(rows);more=False
    rows=available(core,rows,cancel)
    result={'rows':rows,'more':more,'next':next_page,'similar':similar,'spec':spec}
    if not stopped():core.write_cache_entry('search',key,result)
    return result


def history(core):
    values=core.read_json(os.path.join(core.PROFILE,'search-history.json'),[]) or []
    return [q for q in values if isinstance(q,str) and q.strip()][:8]


def remember(core,query):
    query=' '.join(query.split())[:120]
    values=[q for q in history(core) if normal(q)!=normal(query)]
    core.write_json(os.path.join(core.PROFILE,'search-history.json'),([query]+values)[:8] if query else values)


def label2(row):
    if row.get('media_type')=='person':return 'Osobnost · filmy a seriály'
    parts=['Film' if row['media_type']=='movie' else 'Seriál']
    if year(row):parts.append(year(row))
    if original(row) and normal(original(row))!=normal(title(row)):parts.append(original(row))
    return ' · '.join(parts)
