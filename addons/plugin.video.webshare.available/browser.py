"""Series, episodes, details and source choices inside one stable Kodi window."""
import queue
import threading
import time
import xbmc
import xbmcgui
from navigation import Navigation

# ČSFD percentages published by Filmtoro and Najdi Film, checked 2026-11-17.
# Keyed by TMDb media type and ID so remakes and individual episodes stay distinct.
CSFD_PERCENTAGES = {
    ('movie', 841): 68,       # Duna (1984)
    ('movie', 438631): 82,    # Duna (2021)
    ('tv', 117648): 95,       # Clarksonova farma
}

class Browser(xbmcgui.WindowXMLDialog):
    def configure(self,family,record,origin):
        self.f=family;self.nav=Navigation(record);self.origin=origin
        self.started=False;self.closed=False;self.active=False;self.ready=False;self.art_initialized=False
        self.busy=False;self.cancel_event=None;self.results=queue.Queue()
        self.pending=None;self.last_job=None;self.progress={};self.actions={}
        self.row_actions=[];self.seasons=None;self.episodes={};self.sources={}
        return self
    def onInit(self):
        if not self.active:
            self.active=True
            self.f.HOME.setProperty('Family.Card.Active','true')
            self.f.HOME.setProperty('Family.Card.Depth','1')
        self.art_initialized=False;self.ready=True;self.render()
    def remember(self):
        try:self.nav.current['focus']=self.getFocusId()
        except RuntimeError:pass
        if self.nav.current.get('focus')==510:
            self.nav.current['selected']=self.getControl(510).getSelectedPosition()
    def push(self,page,remember=True,**data):
        if remember:self.remember()
        self.nav.push(page,**data);self.render()
    def back(self):
        if self.busy:
            self.nav.cancel();self.cancel_event.set();self.busy=False;self.pending=None
            self.render();return
        if self.nav.back():self.render()
        else:self.close()
    def onAction(self,action):
        if action.getId() in (9,10,92):self.back()
        elif action.getId() in (1,2,3,4,5,6) and not self.busy:self.remember()
    def onClick(self,control):
        if self.closed:return
        if control==404:self.back();return
        if self.busy:return
        if control==510:
            position=self.getControl(510).getSelectedPosition()
            self.nav.current['selected']=position
            if 0<=position<len(self.row_actions):self.select(self.row_actions[position])
        elif control in self.actions:self.actions[control]()
    def close(self):
        if self.closed:return
        self.closed=True;self.nav.cancel()
        if self.cancel_event:self.cancel_event.set()
        # Release bound callbacks before Kodi disposes the native XML window.
        self.actions.clear();self.pending=None;self.last_job=None
        if self.active:
            self.active=False
            self.f.HOME.clearProperty('Family.Card.Active')
            self.f.HOME.setProperty('Family.Card.Depth','0')
            self.f.HOME.clearProperty('Family.UI.State')
        super(Browser,self).close()
    def begin(self,function,done,message,remember=True):
        if remember:self.remember()
        token=self.nav.begin();self.cancel_event=threading.Event()
        cancel=self.cancel_event;self.progress={};progress=self.progress
        self.pending=(token,done);self.last_job=(function,done,message)
        self.busy=True;self.message=message;self.render()
        def run():
            try:self.results.put((token,True,function(cancel,progress)))
            except Exception as exc:self.results.put((token,False,exc))
        threading.Thread(target=run,daemon=True).start()
    def retry(self):
        job=self.last_job;self.nav.back()
        if job:self.begin(*job,remember=False)
        else:self.render()
    def poll(self):
        if not self.ready or self.closed:return
        if self.busy:
            done=self.progress.get('done',0);total=self.progress.get('total',0)
            message=self.progress.get('message') or self.message
            self.getControl(4).setLabel(message+('  {} / {}'.format(done,total) if total else ''))
            self.getControl(520).setPercent(int(done*100/total) if total else 0)
        while not self.closed:
            try:token,ok,value=self.results.get_nowait()
            except queue.Empty:break
            if not self.nav.accepts(token) or not self.pending or token!=self.pending[0]:continue
            callback=self.pending[1];self.pending=None;self.busy=False
            if ok:
                try:callback(value)
                except Exception as exc:self.error(exc)
            else:self.error(value)
    def error(self,exc):
        title,message=self.f.classify_error(exc)
        self.push('error',remember=False,title=title,text=message,focus=401)
    def root_title(self):
        root=self.nav.root
        return root['meta'].get('show_title') or root['item'].get('show_title') or self.f.record_title(root)
    def episode_title(self,record):
        item=record['item'];meta=record['meta']
        if item['kind']=='episode':
            return '{}. řada · {}. díl  —  {}'.format(item['season'],item['episode'],meta.get('title') or item.get('episode_title',''))
        return str(meta.get('year') or item.get('year') or '')
    def source_summary(self,source):
        summary=self.f.source_summary(source)
        prefix,separator,languages=summary.partition('Titulky: ')
        if separator:
            codes=languages.split('/')
            if len(codes)>3:return prefix+separator+'/'.join(codes[:2])+' +{}'.format(len(codes)-2)
        return summary
    def set_actions(self,entries):
        self.actions={}
        for cid in (401,402,403,405):self.getControl(cid).setVisible(False)
        for index,(label,callback) in enumerate(entries[:3]):
            cid=401+index;c=self.getControl(cid)
            c.setLabel(label);c.setPosition(660,500+index*78);c.setWidth(900);c.setVisible(True)
            self.actions[cid]=callback
        controls=[self.getControl(cid) for cid in self.actions]+[self.getControl(404)]
        for index,c in enumerate(controls):
            c.controlUp(controls[index-1]);c.controlDown(controls[(index+1)%len(controls)])
    def render(self):
        if not self.ready or self.closed:return
        frame=self.nav.current;page=frame['page'];record=frame['record']
        self.f.HOME.setProperty('Family.UI.State','loading' if self.busy else page)
        self.setProperty('family.view','loading' if self.busy else page)
        self.getControl(1).setLabel(self.root_title())
        item = record['item']
        subtitle = self.episode_title(record) if item['kind'] != 'tv' else 'Seriál'
        if page in ('overview', 'episode'):
            percentage = CSFD_PERCENTAGES.get((item['kind'], item.get('tmdb_id')))
            if percentage is not None:
                subtitle = ' · '.join(part for part in (subtitle, f'ČSFD {percentage} %') if part)
        watch_catalog = self.origin.get('watch_catalog')
        if watch_catalog and page in ('overview', 'episode'):
            subtitle = ' · '.join(part for part in (subtitle, 'Katalog ČR podle JustWatch', 'Přehrávání přes Webshare') if part)
        self.getControl(2).setLabel(subtitle)
        self.getControl(4).setLabel('')
        art_key=(self.nav.root['item']['kind'],self.nav.root['item'].get('tmdb_id'))
        if self.art_initialized!=art_key:
            art=self.f.core.artwork(self.nav.root['meta'])
            self.getControl(100).setImage(art.get('poster') or 'DefaultVideo.png')
            self.art_initialized=art_key
        self.getControl(6).setText(str(self.nav.root['meta'].get('year') or self.nav.root['item'].get('year') or '')+'\n'+('Seriál' if self.nav.root['item']['kind'] in ('tv','episode') else 'Film'))
        for cid in (3,13,510,520,406,407,408,409):self.getControl(cid).setVisible(False)
        self.getControl(404).setLabel('Zrušit načítání' if self.busy else 'Zpět')
        self.row_actions=[];self.set_actions([])
        if self.busy:
            self.getControl(13).setText(self.message+'\n\nZpět načítání zruší.')
            self.getControl(13).setVisible(True);self.getControl(520).setVisible(True)
            self.setFocusId(404);return
        if page in ('overview','episode'):
            self.getControl(3).setText(record['meta'].get('plot') or 'Popis zatím není k dispozici.')
            self.getControl(3).setVisible(True)
            if page=='overview':entries=[('Řady a díly',self.open_seasons),('Informace',self.open_info)]
            else:
                position=self.f.resume_position(record)
                label='Pokračovat od {:02d}:{:02d}'.format(int(position)//60,int(position)%60) if position>=15 else ('Přehrát z Webshare' if watch_catalog else 'Přehrát')
                entries=[(label,lambda:self.play(True)),('Jazyk a kvalita',lambda:self.load_sources(False,True)),('Informace',self.open_info)]
            self.set_actions(entries)
            if page=='episode' and self.f.resume_position(record)>=15:
                self.getControl(401).setWidth(440)
                c=self.getControl(405);c.setPosition(1120,500);c.setWidth(440);c.setLabel('Od začátku');c.setVisible(True)
                self.actions[405]=lambda:self.play(False)
                self.getControl(401).controlRight(c);c.controlLeft(self.getControl(401));c.controlDown(self.getControl(402));c.controlUp(self.getControl(404))
            else:self.getControl(401).controlRight(self.getControl(401))
        elif page=='info':
            self.getControl(2).setLabel(frame.get('title') or self.episode_title(record) or 'Informace')
            self.getControl(13).setText(frame.get('text') or record['meta'].get('plot') or 'Popis zatím není k dispozici.')
            self.getControl(13).setVisible(True)
        elif page=='error':
            self.getControl(2).setLabel(frame['title']);self.getControl(3).setText(frame['text']);self.getControl(3).setVisible(True)
            self.set_actions([('Zkusit znovu',self.retry)])
        else:
            rows=[]
            if page=='seasons':
                self.getControl(2).setLabel('Řady a díly')
                for season in self.seasons:
                    rows.append((season.get('name') or '{}. řada'.format(season['season_number']),'{} dílů'.format(season.get('episode_count',0)),{'kind':'season','value':season}))
            elif page=='episodes':
                season=frame['season'];self.getControl(2).setLabel(season.get('name') or '{}. řada'.format(season['season_number']))
                for episode in self.episodes[season['season_number']]:
                    number=episode['episode_number']
                    rows.append(('{}. {}'.format(number,episode.get('name') or 'Epizoda'),'S{:02d}E{:02d}  ·  {}'.format(season['season_number'],number,episode.get('air_date') or ''),{'kind':'episode','value':episode,'season':season['season_number']}))
            elif page in ('sources','files'):
                ultra=frame.get('ultra',False);all_sources=frame['sources']
                regular=[s for s in all_sources if self.f.source_attributes(s)['resolution']!=2160]
                high=[s for s in all_sources if self.f.source_attributes(s)['resolution']==2160]
                shown=all_sources if page=='files' else (high if ultra else regular)
                self.getControl(2).setLabel(self.episode_title(record)+'  ·  '+('Podrobnosti souborů' if page=='files' else '4K' if ultra else 'Jazyk a kvalita'))
                for source in shown:
                    rows.append((source.get('name') or 'Soubor bez názvu',self.f.source_label(source),{'kind':'file_info' if page=='files' else 'source','value':source}))
                if page=='sources':
                    if high and not ultra:rows.append(('4K varianty ({})'.format(len(high)),'Vyšší rozlišení',{'kind':'ultra'}))
                    rows.append(('Podrobnosti zvukových stop a titulků','',{'kind':'file_details'}))
                if frame.get('only_4k'):self.getControl(4).setLabel('Pro tento díl jsou nyní ověřené jen 4K varianty.')
            control=self.getControl(510);control.reset();items=[]
            for label,label2,action in rows:
                item=xbmcgui.ListItem(label=label,label2=label2)
                if action['kind'] in ('source','file_info'):
                    item.setProperty('family.source.tracks',self.source_summary(action['value']))
                items.append(item);self.row_actions.append(action)
            control.addItems(items);control.setVisible(True)
            if items:control.selectItem(min(max(0,frame.get('selected',0)),len(items)-1))
            else:
                control.setVisible(False);self.getControl(13).setText('Zatím tu nejsou dostupné žádné položky.');self.getControl(13).setVisible(True)
            self.getControl(404).controlUp(control);self.getControl(404).controlDown(control)
        focus=frame.get('focus',401)
        if page in ('seasons','episodes','sources','files'):focus=510 if self.row_actions else 404
        elif page in ('info',):focus=404
        elif focus not in self.actions and focus!=404:focus=401 if self.actions else 404
        self.setFocusId(focus)
    def open_info(self):
        self.push('info',focus=404)
    def open_seasons(self):
        if self.seasons is not None:self.push('seasons');return
        ident=self.nav.root['item']['tmdb_id']
        def done(payload):
            self.seasons=[s for s in payload.get('seasons',[]) if s.get('episode_count',0)>0]
            if not self.seasons:
                self.push('info',remember=False,title='Řady a díly',text='Pro tento seriál zatím nejsou dostupné žádné řady.',focus=404);return
            self.push('seasons',remember=False)
        self.begin(lambda c,p:self.f.core.tmdb_request('/tv/'+str(ident)),done,'Načítám řady seriálu…')
    def select(self,action):
        kind=action['kind'];self.remember()
        if kind=='season':
            season=action['value'];number=season['season_number'];ident=self.nav.root['item']['tmdb_id']
            if number in self.episodes:self.push('episodes',season=season);return
            def done(data):
                self.episodes[number]=[e for e in data.get('episodes',[]) if e.get('episode_number',0)>0 and (not e.get('air_date') or e['air_date']<=time.strftime('%Y-%m-%d'))]
                self.push('episodes',remember=False,season=season)
            self.begin(lambda c,p:self.f.core.tmdb_request('/tv/{}/season/{}'.format(ident,number)),done,'Načítám díly…')
        elif kind=='episode':
            item={'kind':'episode','tmdb_id':self.nav.root['item']['tmdb_id'],'show_title':self.root_title(),'season':action['season'],'episode':action['value']['episode_number']}
            self.begin(lambda c,p:self.f.record_for(item),lambda record:self.push('episode',remember=False,record=record,focus=401),'Načítám informace o dílu…')
        elif kind=='ultra':self.push('sources',sources=self.nav.current['sources'],ultra=True,resume=self.nav.current.get('resume',True))
        elif kind=='file_details':self.push('files',sources=self.nav.current['sources'])
        elif kind=='file_info':
            source=action['value'];self.push('info',title='Zvuk a titulky',text=(source.get('name') or 'Soubor bez názvu')+'\n\n'+self.f.source_label(source)+'\n\n'+'\n\n'.join(self.f.track_lines(source)),focus=404)
        elif kind=='source':self.prepare(action['value'],self.nav.current.get('resume',True))
    def play(self,resume):self.load_sources(True,resume)
    def load_sources(self,auto,resume):
        self.remember()
        record=self.nav.current['record'];item=record['item'];key=self.f.media_key(item['kind'],item['tmdb_id'],item.get('season'),item.get('episode'))
        def done(sources):
            if not sources:raise RuntimeError('SOURCE_UNAVAILABLE')
            self.sources[key]=sources
            regular=[s for s in sources if self.f.source_attributes(s)['resolution']!=2160]
            if auto and regular:self.prepare(regular[0],resume,remember=False)
            else:self.push('sources',remember=False,sources=sources,ultra=not bool(regular),only_4k=not bool(regular),resume=resume)
        if key in self.sources:done(self.sources[key]);return
        def work(cancel,progress):
            sources=self.f.find_sources(record)
            if cancel.is_set():return []
            progress.update(message='Čtu zvukové stopy a titulky…',total=len(sources),done=0)
            return self.f.inspect_sources(sources,cancel,progress)
        self.begin(work,done,'Hledám ověřené zdroje…')
    def prepare(self,source,resume,remember=True):
        record=self.nav.current['record']
        def done(link):
            self.f.PENDING_PLAYBACK=(record,(source,link),self.origin,resume)
            self.started=True;self.close()
        self.begin(lambda c,p:self.f.file_link(source),done,'Připravuji přehrávání…',remember=remember)

def show(family,record,origin):
    dialog=Browser('FamilyBrowser.xml',family.PATH,'Default','1080i').configure(family,record,origin)
    monitor=xbmc.Monitor()
    try:
        dialog.show()
        while not dialog.closed and not monitor.abortRequested():
            dialog.poll();monitor.waitForAbort(.05)
        monitor.waitForAbort(.25)
        return dialog.started
    finally:
        dialog.close()
