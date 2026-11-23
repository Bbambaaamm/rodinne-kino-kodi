"""Prefetch the next twenty, then refresh the same native carousel by URL."""
import json,queue,threading,time
import paging as p
import streaming

STREAMING_HUB = 11104
STREAMING_ROWS = {'movie': 502, 'tv': 503}
STREAMING_PROPERTY = 'Family.Streaming.'


def sync_streaming_counts(f):
    for kind in STREAMING_ROWS:
        provider = f.HOME.getProperty(STREAMING_PROPERTY + 'provider.' + kind)
        key = STREAMING_PROPERTY + 'count.' + kind
        source = 'provider_' + provider
        count = str(p.requested(f, p.route(kind, source))) if p.provider_id(source) else ''
        if count != f.HOME.getProperty(key):
            if count:f.HOME.setProperty(key, count)
            else:f.HOME.clearProperty(key)


def focus_streaming_catalogue(f, current_control):
    restore = f.HOME.getProperty(STREAMING_PROPERTY + 'restore')
    if restore:
        if current_control not in ('', '501', '502', '503', '601'):
            f.HOME.clearProperty(STREAMING_PROPERTY + 'restore')
        elif streaming_row_visible(f, 501):
            f.HOME.clearProperty(STREAMING_PROPERTY + 'restore')
            f.xbmc.executebuiltin('SetFocus(501,{},absolute)'.format(int(restore)))
        return
    if not f.HOME.getProperty(STREAMING_PROPERTY + 'service'):
        return
    pending = f.HOME.getProperty(STREAMING_PROPERTY + 'pending')
    selector='Container(601).ListItem.Property(widget_id)'
    second='Container(601).ListItemAbsolute(1).Property(widget_id)'
    candidates={kind:'Container({}).ListItemAbsolute(0).Property(family.paging.key)'.format(row)
                for kind,row in STREAMING_ROWS.items() if not f.HOME.getProperty(STREAMING_PROPERTY+'ready.'+kind)}
    labels=f.rpc('XBMC.GetInfoLabels',{'labels':[selector,second,*candidates.values()]}) or {}
    for kind, field in candidates.items():
        provider=f.HOME.getProperty(STREAMING_PROPERTY+'provider.'+kind)
        if provider and labels.get(field)=='list_'+kind+'_provider_'+provider:
            f.HOME.setProperty(STREAMING_PROPERTY+'ready.'+kind,'true')
    if pending in STREAMING_ROWS:
        if current_control=='501' and labels.get(second)==str(STREAMING_ROWS[pending]):
            f.HOME.setProperty(STREAMING_PROPERTY+'pending','focus.'+pending)
            f.xbmc.executebuiltin('SetFocus(601,1,absolute)')
        elif current_control not in ('','501'):
            f.HOME.clearProperty(STREAMING_PROPERTY+'pending')
        return
    if pending.startswith('focus.'):
        kind=pending.split('.',1)[1]
        row=STREAMING_ROWS[kind]
        if current_control not in ('','501','601',str(row)) or (current_control=='601' and labels.get(selector)!=str(row)):
            f.HOME.clearProperty(STREAMING_PROPERTY+'pending')
        elif (f.HOME.getProperty(STREAMING_PROPERTY+'ready.'+kind)
              and streaming_row_visible(f,row)):
            f.HOME.clearProperty(STREAMING_PROPERTY+'pending')
            focus_streaming_row(f,kind)
        return
    for kind,row in STREAMING_ROWS.items():
        if (current_control==str(row) and f.HOME.getProperty(STREAMING_PROPERTY+'fresh.'+kind)
                and f.HOME.getProperty(STREAMING_PROPERTY+'ready.'+kind)):
            focus_streaming_row(f,kind)


def focus_streaming_row(f, kind):
    first_visit = STREAMING_PROPERTY + 'fresh.' + kind
    offset = ',0,absolute' if f.HOME.getProperty(first_visit) else ''
    f.HOME.clearProperty(first_visit)
    f.xbmc.executebuiltin('SetFocus({}{})'.format(STREAMING_ROWS[kind], offset))


def streaming_row_visible(f, row):
    selected = 'Container(601).ListItem.Property(widget_id)'
    info = f.rpc('XBMC.GetInfoLabels', {'labels': [selected]}) or {}
    if info.get(selected) != str(row):
        return False
    condition = 'Control.IsVisible({})'.format(row)
    visible = f.rpc('XBMC.GetInfoBooleans', {'booleans': [condition]}) or {}
    return bool(visible.get(condition))


class Pager:
    def __init__(self,f):
        self.f=f;self.results=queue.Queue();self.inflight={};self.retry={};self.ready=[];self.next_poll=0;self.closed=False
        self.next_spotlight_sync = 0
        self.display_results = queue.Queue()
        self.display_job = None
        self.display_retry = {}
        self.account_stamp = ''
        self.poster_job = None
        self.poster_provider = ''
    def close(self):
        self.closed=True
        for cancel in self.inflight.values():cancel.set()
        if self.display_job:self.display_job.set()
        if self.poster_job:self.poster_job.set()
    def publish(self,key,state,**values):
        self.f.HOME.setProperty('Family.Paging.Status',json.dumps({'key':key,'state':state,**values}))
    def sync_spotlights(self):
        settings = ['HomeSwitcher.' + hub + '.Spotlight' for hub in ('Home', '1101', '1102', '1103')]
        keys = ['Skin.String(' + setting + '.' + field + ')' for setting in settings for field in ('Path', 'Limit')]
        labels = self.f.rpc('XBMC.GetInfoLabels', {'labels': keys}) or {}
        for setting in settings:
            original = labels.get('Skin.String(' + setting + '.Path)', '')
            path = p.spotlight_path(self.f, original)
            if path is None:
                continue
            if labels.get('Skin.String(' + setting + '.Limit)') != '0':
                self.f.xbmc.executebuiltin('Skin.SetString(' + setting + '.Limit,0)')
            if path != original:
                # A Skin.String used as content is evaluated once. Give Kodi
                # the concrete URL so a changed page count refreshes the row.
                self.f.xbmc.executebuiltin('Skin.SetString(' + setting + '.Path,"' + path + '")')
    def streaming_tick(self):
        f=self.f
        field='System.CurrentControlID'
        info=f.rpc('XBMC.GetInfoLabels',{'labels':[field]}) or {}
        sync_streaming_counts(f)
        focus_streaming_catalogue(f,info.get(field,''))
        self.prefetch_streaming_posters(info.get(field,''))

    def prefetch_streaming_posters(self, control):
        f = self.f
        if control != '501' or f.HOME.getProperty(STREAMING_PROPERTY + 'service'):
            return
        field = 'ListItem.Property(family.streaming.movie)'
        labels = f.rpc('XBMC.GetInfoLabels', {'labels': [field]}) or {}
        provider = labels.get(field, '')
        if provider == self.poster_provider or p.provider_id('provider_' + provider) is None:
            return
        if self.poster_job:
            self.poster_job.set()
        self.poster_provider = provider
        cancel = threading.Event()
        self.poster_job = cancel
        def load():
            try:
                value = p.route('movie', 'provider_' + provider)
                data = p.ensure(f, value, p.BATCH, cancel)
                if not cancel.is_set():
                    streaming.prefetch_posters(f.core, data['records'], cancel)
            except (OSError, RuntimeError, ValueError, TimeoutError, InterruptedError):
                pass
        threading.Thread(target=load, daemon=True).start()

    def refresh_display(self,window,focused):
        f=self.f
        stamp=f.HOME.getProperty('Family.Accounts.Changed')
        if stamp != self.account_stamp:
            self.account_stamp=stamp
            self.display_retry.clear()
        try:
            value,revision,ok=self.display_results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.display_job=None
            if revision==p.revision(f,value):
                error=p.display_property(value,'Error')
                if ok:
                    f.HOME.clearProperty(error)
                    self.display_retry.pop(p.key(value),None)
                else:
                    f.HOME.setProperty(error,'true')
                    self.display_retry[p.key(value)]=time.monotonic()+30
                f.HOME.setProperty(p.display_property(value,'Version'),str(time.time()))
                self.next_spotlight_sync=0
                if window==10025 and focused==p.key(value):
                    f.xbmc.executebuiltin('Container.Refresh()')
        if self.display_job:
            return
        for kind,source in p.HOME_LISTS:
            value=p.route(kind,source)
            prop=p.display_property(value,'Wanted')
            wanted=f.HOME.getProperty(prop)
            if not wanted.isdigit() or p.key(value) in self.inflight or time.monotonic()<self.display_retry.get(p.key(value),0):
                continue
            f.HOME.clearProperty(prop)
            cancel=threading.Event()
            self.display_job=cancel
            revision=p.revision(f,value)
            def load():
                try:
                    data=p.ensure(f,value,int(wanted),cancel)
                    ok=bool(data['records']) or not data['more']
                    if data['more'] and len(data['records'])<int(wanted):
                        self.display_retry[p.key(value)]=time.monotonic()+2
                except Exception:
                    ok=False
                self.display_results.put((value,revision,ok))
            threading.Thread(target=load,daemon=True).start()
            return

    def tick(self,window=10000):
        if self.closed or time.monotonic()<self.next_poll:return
        self.next_poll=time.monotonic()+.4;f=self.f
        while True:
            try:result=self.results.get_nowait()
            except queue.Empty:break
            self.inflight.pop(result[0],None);self.ready.append(result)
        # These labels are read only while the normal hub is active. No native
        # window focus calls, keyboard callbacks or playback are involved.
        labels=f.rpc('XBMC.GetInfoLabels',{'labels':['System.CurrentControlID','ListItem.Property(family.paging.key)','ListItem.Property(family.paging.more)','ListItem.Property(family.paging.count)']}) or {}
        for key,target,rev,ok,data in self.ready:
            value=p.from_key(key)
            if rev!=p.revision(f,value):continue
            if ok:
                f.HOME.setProperty(p.count_property(value),str(target))
                self.next_spotlight_sync = 0
                if window==10025 and labels.get('ListItem.Property(family.paging.key)')==key:
                    if value['source'].startswith('genre_'):f.HOME.setProperty('Family.Paging.GenreRefresh',json.dumps({'key':key,'time':time.time()}))
                    f.xbmc.executebuiltin('Container.Refresh()')
                self.retry.pop(key,None);self.publish(key,'ready',requested=target,items=len(data['records']),more=data['more'],source_pages=data.get('source_pages',0))
            else:
                self.retry[key]=time.monotonic()+30;self.publish(key,'error',error_type=data)
                if labels.get('ListItem.Property(family.paging.key)')==key:
                    f.core.notify('Další tituly se nepodařilo načíst. Potvrď Další tituly pro nový pokus.')
        self.ready=[]
        self.refresh_display(window,labels.get('ListItem.Property(family.paging.key)',''))
        if time.monotonic() >= self.next_spotlight_sync:
            self.next_spotlight_sync = time.monotonic() + 4
            self.sync_spotlights()
        try:cid=int(labels.get('System.CurrentControlID') or 0)
        except ValueError:return
        spotlight = window in (10000, 11101, 11102, 11103) and cid in (311, 312)
        container = 301 if spotlight else cid
        if not spotlight and not 501<=cid<=550 and not (window==10025 and cid>=50):return
        if spotlight:
            base='Container(301).ListItem.'
            keys=[base+'Property(family.paging.'+field+')' for field in ('key','more','count')]
            info=f.rpc('XBMC.GetInfoLabels',{'labels':keys}) or {}
            key=info.get(keys[0],'');more=info.get(keys[1]);stamp=info.get(keys[2])
        else:
            key=labels.get('ListItem.Property(family.paging.key)','');more=labels.get('ListItem.Property(family.paging.more)');stamp=labels.get('ListItem.Property(family.paging.count)')
        if not key or more!='true':return
        try:value=p.from_key(key)
        except ValueError:return
        desired=p.requested(f,value)
        if desired>=p.MAX_ITEMS:return
        try:
            if int(stamp or 0)!=desired:return
        except ValueError:return
        forced=f.HOME.getProperty('Family.Paging.Force')==key
        if forced:f.HOME.clearProperty('Family.Paging.Force');self.retry.pop(key,None)
        if key in self.inflight or time.monotonic()<self.retry.get(key,0):return
        keys=['Container({}).{}'.format(container,field) for field in ('NumItems','CurrentItem')]
        info=f.rpc('XBMC.GetInfoLabels',{'labels':keys}) or {}
        try:count=int(info[keys[0]]);selected=int(info[keys[1]])
        except (ValueError,KeyError):return
        if not forced and selected<max(1,count-5):return
        target=desired+p.BATCH;cancel=threading.Event();rev=p.revision(f,value);self.inflight[key]=cancel;self.publish(key,'loading',requested=target)
        def run():
            try:result=p.ensure(f,value,target,cancel);self.results.put((key,target,rev,True,result))
            except Exception as exc:self.results.put((key,target,rev,False,type(exc).__name__))
        threading.Thread(target=run,daemon=True).start()
