"""One visible entry point for search, discovery, people and title details."""
import copy
import json
import queue
import threading
import time
import xbmc
import xbmcgui
from browser import Browser
import searching as s
import discovery as d

SPEC_KEYS=('mode','query','kind','mood','period','duration','person','reference')
EXTRA=(410,413,414,415,416,417,418,420,421,422,423,424,425,426,427,428,430,431,432,512,611,612,613,614)

class Discover(Browser):
    def configure_search(self,family,origin,params):
        self.configure(family,d.root_record(),origin)
        self.params=params;self.initialized=False;self.initial_job=None;self.exit_requested=False;self.keyboard_requested=None;self.keyboard_open=False;self.trace=None;self.next_restore_poll=0
        self.home_frame(self.nav.current)
        self.more_request=None;self.more_running=False;self.more_cancel=None;self.more_results=queue.Queue()
        return self
    def home_frame(self,frame):
        frame.update(d.spec(),page='search',focus=406,selected=0,rows=[],more=False,loaded_pages=0)
    def onInit(self):
        if not self.initialized:
            self.initialized=True
            restored=self.apply_snapshot(self.params.get('restore',''))
            if not restored and self.params.get('query'):
                self.initial_job=d.spec(mode='person' if self.params.get('person') else 'query',query=self.params['query'],kind=self.params.get('filter','all'),person=int(self.params.get('person') or 0))
        super(Discover,self).onInit()
    def poll(self):
        if self.closed:return
        self.poll_more()
        if not self.busy and not self.keyboard_requested and time.monotonic()>=self.next_restore_poll:
            self.next_restore_poll=time.monotonic()+.25
            token=self.f.HOME.getProperty('Family.Search.RestoreRequest')
            if token:
                self.f.HOME.clearProperty('Family.Search.RestoreRequest');self.apply_snapshot(token)
        if self.keyboard_requested:
            kind=self.keyboard_requested;self.keyboard_requested=None;self.keyboard_open=True
            if self.trace:self.trace.mark('keyboard.open')
            try:
                if kind=='query':self.run_keyboard()
                else:self.run_year_keyboard()
            finally:
                self.keyboard_open=False
                if self.trace:self.trace.mark('keyboard.return')
        if self.initial_job:
            spec=self.initial_job;self.initial_job=None;self.request(spec)
        super(Discover,self).poll()
    def onAction(self,action):
        if self.keyboard_open:return
        super(Discover,self).onAction(action)
        frame=self.nav.current
        if action.getId() in (1,2,3,4,5,6) and not self.busy and frame.get('page')=='search' and frame.get('focus')==511 and frame.get('more') and frame.get('selected',0)>=max(0,len(frame.get('rows',[]))-6) and time.monotonic()>=frame.get('more_retry_at',0):
            self.more_request=(frame,self.values(frame),frame.get('next',2))
    def poll_more(self):
        if self.keyboard_open or self.keyboard_requested:return
        while True:
            try:frame,value,page,ok,payload=self.more_results.get_nowait()
            except queue.Empty:break
            self.more_running=False;frame['more_loading']=False
            exists=any(candidate is frame for candidate in self.nav.stack+[self.nav.current])
            if not exists or self.values(frame)!=value or frame.get('next',2)!=page:continue
            if ok is None:
                if self.nav.current is frame and not self.busy:self.getControl(4).setLabel('')
                continue
            if ok:
                rows=[];seen=set()
                for row in frame.get('rows',[])+payload['rows']:
                    ident=(row.get('media_type'),row.get('id'))
                    if ident not in seen:seen.add(ident);rows.append(row)
                frame.update(rows=rows,more=payload.get('more',False),next=payload.get('next',page+1),loaded_pages=page,more_error=False)
                if self.nav.current is frame and not self.busy:
                    # Bridge through a persistent control while rebuilding the
                    # panel; keep the frame's selection rather than reading focus.
                    self.setFocusId(404);self.render()
            else:
                frame['more_retry_at']=time.monotonic()+15;frame['more_error']=True
                if self.nav.current is frame and not self.busy:self.getControl(4).setLabel('Další výsledky se nepodařilo načíst. Zkus Další výsledky znovu.')
        if self.more_request and not self.more_running and not self.busy:
            frame,value,page=self.more_request;self.more_request=None
            if self.nav.current is not frame or self.values(frame)!=value or frame.get('next',2)!=page or not frame.get('more'):return
            self.more_running=True;self.more_cancel=threading.Event();cancel=self.more_cancel;frame['more_loading']=True
            self.getControl(4).setLabel('Načítám další tituly…')
            def run():
                try:
                    result=d.fetch(self.f.core,value,page,cancel)
                    self.more_results.put((frame,value,page,None if cancel.is_set() else True,result))
                except Exception as exc:self.more_results.put((frame,value,page,False,type(exc).__name__))
            threading.Thread(target=run,daemon=True).start()
    def remember(self):
        super(Discover,self).remember()
        if self.getFocusId() in (511,512):self.nav.current['selected']=self.getControl(self.getFocusId()).getSelectedPosition()
    def onClick(self,cid):
        if self.keyboard_open or self.keyboard_requested:return
        if cid==410 and not self.busy:self.go_home();return
        if cid in (511,512):
            if self.busy or self.closed:return
            self.remember();index=self.nav.current.get('selected',0)
            if 0<=index<len(self.row_actions):self.select(self.row_actions[index])
            return
        super(Discover,self).onClick(cid)
    def back(self):
        self.more_request=None
        if self.more_cancel:self.more_cancel.set()
        if not self.busy and not self.nav.stack:self.exit_requested=True
        super(Discover,self).back()
    def go_home(self):self.exit_requested=True;self.close()
    def close(self):
        if not self.closed:
            self.more_request=None
            if self.more_cancel:self.more_cancel.set()
            self.keyboard_requested=None
            if self.exit_requested:
                pending=self.f.HOME.getProperty('Family.Search.Restore') or self.f.HOME.getProperty('Family.Search.PlaybackReturn')
                if pending:self.f.HOME.setProperty('Family.Search.RestoredToken',pending)
                for name in ('Family.Search.Restore','Family.Search.PlaybackReturn','Family.Search.RestoreRequest'):self.f.HOME.clearProperty(name)
            self.f.HOME.clearProperty('Family.Search.Active');self.f.HOME.clearProperty('Family.SearchOpening')
        super(Discover,self).close()
    def apply_snapshot(self,token):
        if not token:return False
        snapshot=d.restore_snapshot(self.f.core,token)
        self.f.HOME.setProperty('Family.Search.RestoreStatus',json.dumps({'requested':True,'found':bool(snapshot),'frames':len(snapshot or [])}))
        if not snapshot:return False
        self.nav.stack=snapshot[:-1];self.nav.current=snapshot[-1]
        self.f.HOME.setProperty('Family.Search.RestoredToken',token)
        for name in ('Family.Search.Restore','Family.Search.PlaybackReturn','Family.Search.RestoreRequest'):
            if self.f.HOME.getProperty(name)==token:self.f.HOME.clearProperty(name)
        self.render();return True
    def values(self,frame=None):
        frame=frame or self.nav.current
        return d.spec(**{k:frame[k] for k in SPEC_KEYS if k in frame})
    def edit_query(self):
        self.keyboard_requested='query'
    def run_keyboard(self):
        frame=self.nav.current;default=frame.get('query','') if frame.get('mode')=='query' else ''
        keyboard=xbmc.Keyboard(default,'Název, herec nebo režisér')
        keyboard.doModal()
        if keyboard.isConfirmed():
            query=keyboard.getText().strip()
            if query:self.request(d.spec(mode='query',query=query,kind=frame.get('kind','all')))
            else:self.new_selection()
    def new_selection(self):
        self.nav.stack=[];self.home_frame(self.nav.current);self.render()
    def change_kind(self,kind):
        frame=self.nav.current
        if frame.get('kind')==kind:return
        value=self.values();value.update(kind=kind,duration='')
        if value['mode']=='home':frame.update(value);self.render()
        else:self.request(value)
    def browse(self,mood='',period=''):
        self.request(d.spec(mode='browse',kind=self.nav.current.get('kind','all'),mood=mood,period=period))
    def request(self,value,more=False,remember=True):
        value=d.spec(**value);old=self.nav.current;page=old.get('next',2) if more else 1
        if not more:
            self.more_request=None
            if self.more_cancel:self.more_cancel.set()
            for field in ('more_loading','more_error','more_retry_at'):old.pop(field,None)
        existing=list(old.get('rows',[])) if more else []
        if remember:self.remember()
        create=(old.get('mode')=='home' and value['mode']!='home') or old['page']!='search' or (value['mode']=='person' and old.get('person')!=value.get('person'))
        def done(payload):
            if create:self.nav.push('search',record=d.root_record(),root_record=d.root_record())
            frame=self.nav.current
            rows=[];seen=set()
            for row in existing+payload['rows']:
                key=(row.get('media_type'),row.get('id'))
                if key not in seen:seen.add(key);rows.append(row)
            selected=min(old.get('selected',0),len(rows)-1) if more and rows else 0
            frame.update(value,rows=rows,more=payload.get('more',False),next=payload.get('next',page+1),loaded_pages=page,similar=payload.get('similar',False),selected=max(0,selected),focus=511 if rows else 413)
            if value['mode']=='query':s.remember(self.f.core,value['query'])
            self.render()
        self.begin(lambda c,p:d.fetch(self.f.core,value,page,c),done,'Hledám vhodné tituly…',remember=False)
    def open_filters(self,only_year=False):
        value=self.values()
        if value['mode']=='home':value['mode']='browse'
        self.push('filters',settings=value,focus=512)
        # This automatic transition happens before Kodi applies native focus.
        # Keep the explicit return target instead of reading that stale focus.
        if only_year:self.open_options('period',remember=False)
    def open_options(self,field,remember=True):
        value=self.nav.current['settings']
        options=d.PERIODS+[('custom','Konkrétní rok…')] if field=='period' else [('', 'Všechny žánry')]+[(m[0],m[2]) for m in d.MOODS] if field=='mood' else d.DURATIONS
        current=value.get(field,'');selected=next((i for i,(k,_) in enumerate(options) if k==current),0)
        self.push('options',remember=remember,field=field,options=options,selected=selected,focus=512)
    def set_option(self,action):
        value=action['value'];field=self.nav.current['field']
        if value=='custom':
            self.keyboard_requested='year';return
        self.nav.back();self.nav.current['settings'][field]=value
        if field=='duration' and value:self.nav.current['settings']['kind']='movie'
        self.render()
    def run_year_keyboard(self):
        # Keep keyboard handling consistent with title search.
        keyboard=xbmc.Keyboard('','Rok premiéry (např. 1994)')
        keyboard.doModal()
        if not keyboard.isConfirmed():return
        text=keyboard.getText().strip()
        if not text:return
        if not text.isdigit() or not 1900<=int(text)<=int(time.strftime('%Y'))+3:
            self.getControl(4).setLabel('Zadej rok od 1900 do {}.'.format(int(time.strftime('%Y'))+3));return
        self.set_option({'value':'year:'+text})
    def apply_filters(self):
        value=copy.deepcopy(self.nav.current['settings'])
        if value['mode']=='query' and value['period']:
            parsed=s.parse(value['query']);value['query']=parsed['text']
            if value['period'].startswith('year:'):value['query']+=' '+value['period'][5:]
        # The visible controls still belong to Filters until results render.
        # Do not overwrite the restored parent's remembered focus/selection.
        self.nav.back();self.request(value,remember=False)
    def open_people(self):
        record=self.nav.root
        self.begin(lambda c,p:d.credits(self.f.core,record),lambda rows:self.push('people',remember=False,people=rows,focus=510),'Načítám obsazení a tvůrce…')
    def open_related(self):
        root=self.nav.root;item=root['item'];kind='tv' if item['kind'] in ('tv','episode') else 'movie'
        self.request(d.spec(mode='related',kind=kind,reference={'kind':kind,'id':item['tmdb_id'],'title':self.root_title()}))
    def person_spec(self,name,ident):
        value=self.values() if self.nav.current['page']=='search' else d.spec()
        value.update(mode='person',query=name,person=ident,reference=None,duration='')
        return value
    def show_history(self):self.push('history',history=s.history(self.f.core),focus=510)
    def select(self,action):
        kind=action['kind']
        if kind=='option':self.set_option(action);return
        if kind=='filter':self.open_options(action['field']);return
        if kind=='apply':self.apply_filters();return
        if kind=='clear_history':
            s.remember(self.f.core,'')
            import os
            self.f.core.write_json(os.path.join(self.f.core.PROFILE,'search-history.json'),[])
            self.nav.current['history']=[];self.render();return
        if kind=='history':self.request(d.spec(mode='query',query=action['query'],kind=self.nav.current.get('kind','all')));return
        if kind=='person':
            row=action['value'];self.request(self.person_spec(row['name'],row['id']));return
        if kind=='more':self.request(self.values(),more=True);return
        if kind!='result':return super(Discover,self).select(action)
        self.remember();row=action['value']
        if row['media_type']=='person':self.request(self.person_spec(s.title(row),row['id']));return
        item={'kind':row['media_type'],'tmdb_id':row['id'],'title':s.title(row)}
        def done(record):
            self.seasons=None;self.episodes={}
            self.push('overview' if item['kind']=='tv' else 'episode',remember=False,record=record,root_record=record,focus=401)
        self.begin(lambda c,p:self.f.record_for(item),done,'Načítám informace o titulu…')
    def prepare(self,source,resume,remember=True):
        token=d.save_snapshot(self.f.core,self.nav.stack+[self.nav.current])
        self.origin=dict(self.origin,window=11105,search_snapshot=token)
        super(Discover,self).prepare(source,resume,remember)
    def rows(self,entries,control=512):
        c=self.getControl(control);c.reset();self.row_actions=[];items=[]
        status = None
        for label,label2,action,art in entries:
            li=xbmcgui.ListItem(label=label,label2=label2,offscreen=True)
            if art:li.setArt(art)
            row = action.get('value') if action['kind'] == 'result' else None
            if row and row.get('media_type') == 'movie':
                if status is None:
                    status = self.f.movie_status()
                status.decorate(li, row['id'], native=False)
            items.append(li);self.row_actions.append(action)
        c.addItems(items);c.setVisible(bool(items))
        if items:c.selectItem(min(max(0,self.nav.current.get('selected',0)),len(items)-1))
        return bool(items)
    def heading(self):
        frame=self.nav.current;mode=frame.get('mode')
        if mode=='home':return 'Co si dnes pustíme?'
        if mode=='query':return 'Výsledky hledání'
        if mode=='person':return frame.get('query','')+' · filmy a seriály'
        if mode=='related':return 'Podobné jako '+(frame.get('reference') or {}).get('title','')
        return next((m[1] for m in d.MOODS if m[0]==frame.get('mood')),'Vyber si podle sebe')
    def render(self):
        if not self.ready or self.closed:return
        frame=self.nav.current;page=frame['page'];surface=page in ('search','filters','options','people','history','error')
        for cid in EXTRA+(511,):self.getControl(cid).setVisible(False)
        for cid in (406,407,408,409):self.getControl(cid).setVisible(False)
        if not surface:
            self.setProperty('discovery.surface','false')
            for cid,position,width,height in ((1,(360,195),1200,60),(4,(660,765),900,30),(404,(660,800),900,60),(510,(660,340),900,425),(520,(660,740),900,6)):
                c=self.getControl(cid);c.setPosition(*position);c.setWidth(width);c.setHeight(height)
            super(Discover,self).render()
            if page in ('overview','episode') and not self.busy:
                for cid,label,callback in ((415,'Podobné tituly',self.open_related),(416,'Obsazení',self.open_people)):
                    self.getControl(cid).setLabel(label);self.getControl(cid).setVisible(True);self.actions[cid]=callback
                self.getControl(415).controlDown(self.getControl(416));self.getControl(415).controlUp(self.getControl(404));self.getControl(415).controlRight(self.getControl(401))
                self.getControl(416).controlUp(self.getControl(415));self.getControl(416).controlDown(self.getControl(415));self.getControl(416).controlRight(self.getControl(404))
                for cid in (401,402,403,405):self.getControl(cid).controlLeft(self.getControl(415))
                if frame.get('focus') in (415,416):self.setFocusId(frame['focus'])
            return
        self.setProperty('discovery.surface','true');self.setProperty('family.view',page)
        self.f.HOME.setProperty('Family.UI.State','loading' if self.busy else page)
        for cid in (3,13,510,520):self.getControl(cid).setVisible(False)
        self.set_actions([]);self.actions={410:self.go_home}
        for cid,position,width,height in ((1,(250,140),1150,60),(4,(590,925),1080,30),(404,(250,915),300,48),(510,(250,350),1420,500),(520,(250,904),1420,6)):
            c=self.getControl(cid);c.setPosition(*position);c.setWidth(width);c.setHeight(height)
        self.getControl(410).setVisible(True);self.getControl(404).setVisible(True)
        self.getControl(404).setLabel('Zrušit načítání' if self.busy else 'Zpět')
        self.getControl(4).setLabel(self.message if self.busy else '')
        if not self.busy and frame.get('more_loading'):self.getControl(4).setLabel('Načítám další tituly…')
        elif not self.busy and frame.get('more_error'):self.getControl(4).setLabel('Další výsledky se nepodařilo načíst. Zkus Další výsledky znovu.')
        self.getControl(520).setVisible(self.busy)
        self.row_actions=[]
        if page=='search':
            self.getControl(1).setLabel(self.heading())
            for cid in (406,407,408,409,413,414):self.getControl(cid).setVisible(True)
            self.getControl(414).setLabel('Nový výběr');self.getControl(413).setLabel('Upřesnit výběr')
            self.getControl(406).setLabel(frame.get('query') if frame.get('mode')=='query' else 'Název, herec nebo režisér…')
            self.actions.update({406:self.edit_query,413:self.open_filters,414:self.new_selection})
            for cid,kind,label in ((407,'all','Vše'),(408,'movie','Filmy'),(409,'tv','Seriály')):
                self.getControl(cid).setLabel(('●  ' if frame.get('kind')==kind else '')+label)
                self.actions[cid]=lambda kind=kind:self.change_kind(kind)
            for cid in (407,408,409,413,414):self.getControl(cid).controlUp(self.getControl(406))
            self.getControl(406).controlUp(self.getControl(410));self.getControl(406).controlDown(self.getControl(407))
            if frame.get('mode')=='home':
                self.getControl(413).setVisible(False);self.getControl(414).setVisible(False)
                self.getControl(409).controlRight(self.getControl(409))
                history=s.history(self.f.core)[:3]
                for i,query in enumerate(history):
                    cid=430+i;self.getControl(cid).setLabel(query);self.getControl(cid).setVisible(True)
                    self.actions[cid]=lambda q=query:self.request(d.spec(mode='query',query=q,kind=self.nav.current.get('kind','all')))
                self.getControl(611).setLabel('Poslední hledání' if history else 'Hledej názvem, jménem nebo rokem');self.getControl(611).setVisible(True)
                self.getControl(612).setLabel('Nevím, co si pustit');self.getControl(612).setVisible(True)
                for i,mood in enumerate(d.MOODS):
                    cid=420+i;self.getControl(cid).setLabel(mood[1]);self.getControl(cid).setVisible(True)
                    self.actions[cid]=lambda key=mood[0]:self.browse(key)
                for cid,label,callback in ((426,'Vybrat podle roku',lambda:self.open_filters(True)),(427,'Procházet všechny tituly',lambda:self.browse()),(428,'Historie hledání',self.show_history)):
                    self.getControl(cid).setLabel(label);self.getControl(cid).setVisible(True);self.actions[cid]=callback
                for cid in (407,408,409,413,414):self.getControl(cid).controlDown(self.getControl(430 if history else 420))
                self.getControl(404).controlUp(self.getControl(426));self.getControl(404).controlDown(self.getControl(406))
            else:
                self.getControl(409).controlRight(self.getControl(414))
                self.getControl(613).setLabel(d.description(frame) or ('Podobné názvy' if frame.get('similar') else ''));self.getControl(613).setVisible(True)
                entries=[]
                for row in frame.get('rows',[]):
                    art=self.f.core.artwork(row)
                    if row.get('media_type')=='person' and row.get('profile_path'):art={'poster':self.f.core.POSTER_BASE+row['profile_path']}
                    entries.append((s.title(row),s.label2(row),{'kind':'result','value':row},art))
                if frame.get('more'):entries.append(('Další výsledky','Pokračovat ve výběru',{'kind':'more'},{}))
                shown=self.rows(entries,511)
                self.getControl(614).setLabel('Výsledky: {}'.format(len(frame.get('rows',[]))) if frame.get('rows') else 'Žádná shoda. Zkus odebrat některé omezení.');self.getControl(614).setVisible(True)
                for cid in (407,408,409,413,414):self.getControl(cid).controlDown(self.getControl(511 if shown else 404))
                self.getControl(404).controlUp(self.getControl(511 if shown else 406));self.getControl(404).controlDown(self.getControl(406))
        elif page=='error':
            self.getControl(1).setLabel(frame['title']);self.getControl(613).setLabel(frame['text']);self.getControl(613).setVisible(True)
            self.getControl(414).setLabel('Zkusit znovu');self.getControl(414).setVisible(True);self.actions[414]=self.retry
            self.getControl(414).controlUp(self.getControl(410));self.getControl(414).controlDown(self.getControl(404))
            frame['focus']=414
        else:
            entries=[]
            if page=='filters':
                value=frame['settings'];self.getControl(1).setLabel('Upřesnit výběr')
                entries=[('Rok a období',d.period_label(value['period']),{'kind':'filter','field':'period'},{}),('Žánr',next((m[2] for m in d.MOODS if m[0]==value['mood']),'Všechny žánry'),{'kind':'filter','field':'mood'}, {})]
                if value['mode']=='browse':entries.append(('Délka filmu',dict(d.DURATIONS).get(value['duration'],''),{'kind':'filter','field':'duration'},{}))
                entries.append(('Zobrazit výsledky',d.description(value),{'kind':'apply'},{}))
            elif page=='options':
                self.getControl(1).setLabel({'period':'Rok a období','mood':'Žánr','duration':'Délka filmu'}[frame['field']])
                entries=[(label,'',{'kind':'option','value':value},{}) for value,label in frame['options']]
            elif page=='people':
                self.getControl(1).setLabel('Obsazení a tvůrci · '+self.root_title())
                entries=[(p['name'],p['description'],{'kind':'person','value':p},{}) for p in frame['people']]
            elif page=='history':
                self.getControl(1).setLabel('Poslední hledání')
                entries=[(q,'Zopakovat hledání',{'kind':'history','query':q},{}) for q in frame['history']]
                if entries:entries.append(('Vymazat historii hledání','',{'kind':'clear_history'},{}))
            shown=self.rows(entries)
            if not shown:
                self.getControl(614).setLabel('Historie je prázdná.' if page=='history' else 'Obsazení zatím není k dispozici.')
                self.getControl(614).setVisible(True)
            self.getControl(404).controlUp(self.getControl(512 if shown else 410));self.getControl(404).controlDown(self.getControl(512 if shown else 410))
        focus=404 if self.busy else frame.get('focus',406)
        if focus==510:focus=512
        if focus in (511,512) and not self.row_actions:focus=404
        self.setFocusId(focus)

def show(family,origin,params):
    if family.HOME.getProperty('Family.Search.Active'):return False
    family.HOME.setProperty('Family.Search.Active','true')
    family.HOME.setProperty('Family.Search.ProfileOwner',family.core.ADDON.getAddonInfo('id'))
    dialog=Discover('FamilySearch.xml',family.PATH,'Default','1080i').configure_search(family,origin,params)
    if family.HOME.getProperty('Family.DebugUI'):
        from ui_trace import Trace
        dialog.trace=Trace(family.core.PROFILE)
    monitor=xbmc.Monitor()
    try:
        dialog.show()
        while not dialog.closed and not monitor.abortRequested():
            dialog.poll();monitor.waitForAbort(.05)
        monitor.waitForAbort(.25)
        if dialog.exit_requested and not dialog.started:xbmc.executebuiltin('ActivateWindow(Home)')
        return dialog.started
    finally:
        dialog.close()
        if dialog.trace:dialog.trace.close()
