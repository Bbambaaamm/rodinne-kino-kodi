"""Search and title details share the same cancellable family window."""
import os
import time
import xbmc
import xbmcgui
from browser import Browser
import searching as s


class Search(Browser):
    def configure_search(self,family,origin,params):
        root={'item':{'kind':'search','title':'Hledání'},'meta':{'title':'Hledání'}}
        self.configure(family,root,origin)
        self.params=params;self.initialized=False;self.initial_job=False;self.prompt=False
        self.nav.current.update(page='search',focus=406,query='',kind='all',rows=[],more=False,person=0,selected=0)
        return self
    def onInit(self):
        super(Search,self).onInit()
        self.f.HOME.setProperty('Family.Search.Active','true')
        if not self.initialized:
            self.initialized=True
            saved=self.f.core.read_json(os.path.join(self.f.core.PROFILE,'search-last.json'),{}) or {}
            query=self.params.get('query') or saved.get('query','')
            if query:
                self.initial_job=(query,self.params.get('filter') or saved.get('kind','all'),int(self.params.get('selected') or saved.get('selected') or 0),int(self.params.get('person') or 0))
            else:self.prompt=self.params.get('prompt')=='1' and not s.history(self.f.core)
    def poll(self):
        if self.initial_job:
            query,kind,selected,person=self.initial_job;self.initial_job=False
            self.run_query(query,kind,selected,person)
        elif self.prompt and self.ready:
            self.prompt=False;self.edit_query()
        super(Search,self).poll()
        if self.nav.current['page']=='search' and not self.busy and self.getFocusId()==510:
            self.nav.current['selected']=self.getControl(510).getSelectedPosition()
    def close(self):
        if not self.closed:
            frame=next((f for f in [self.nav.current]+list(reversed(self.nav.stack)) if f['page']=='search' and not f.get('person')),None)
            if frame:
                self.f.core.write_json(os.path.join(self.f.core.PROFILE,'search-last.json'),{k:frame[k] for k in ('query','kind','selected')})
            self.f.HOME.clearProperty('Family.Search.Active');self.f.HOME.clearProperty('Family.SearchOpening')
        super(Search,self).close()
    def edit_query(self):
        keyboard=xbmc.Keyboard(self.nav.current.get('query',''),'Název filmu, seriálu nebo jméno herce')
        keyboard.doModal()
        if keyboard.isConfirmed():
            query=keyboard.getText().strip()
            if query:self.run_query(query,'all')
            else:
                self.nav.current.update(query='',kind='all',rows=[],more=False,similar=False,person=0,selected=0,focus=406)
                self.render()
        # Cancelling the keyboard leaves results and selection untouched.
    def change_kind(self,kind):
        frame=self.nav.current
        if kind!=frame.get('kind') and frame.get('query'):self.run_query(frame['query'],kind,person=frame.get('person',0))
    def run_query(self,query,kind='all',selected=0,person=0,more=False):
        old=self.nav.current
        page=old.get('next',2) if more else 1
        existing=list(old.get('rows',[])) if more else []
        spec=s.parse(query,kind);kind=spec['kind']
        def done(payload):
            if person and old.get('person')!=person:
                self.nav.push('search',query=query,kind=kind,person=person,rows=[],focus=510)
            frame=self.nav.current
            rows=s.rank(existing+payload['rows'],payload['spec'],person=bool(person)) if more else payload['rows']
            frame.update(query=query,kind=kind,person=person,rows=rows,more=payload['more'],next=payload['next'],similar=payload['similar'],selected=selected,focus=510 if rows else 406)
            if not person:s.remember(self.f.core,query)
            self.render()
        self.begin(lambda c,p:s.fetch(self.f.core,query,kind,page,person,c),done,'Hledám filmy a seriály…')
    def render(self):
        super(Search,self).render()
        if not self.ready or self.closed:return
        frame=self.nav.current;search=frame['page']=='search' and not self.busy
        for cid in (406,407,408,409):self.getControl(cid).setVisible(search)
        control=self.getControl(510)
        control.setPosition(660,420 if search else 340)
        control.setHeight(340 if search else 425)
        self.getControl(2).setVisible(not search)
        self.getControl(13).setPosition(660,440 if search else 340)
        if not search:return
        self.getControl(1).setLabel('Hledání')
        self.getControl(2).setVisible(False)
        self.getControl(6).setText('Český i původní název\nVolitelně přidej rok')
        self.getControl(100).setImage('special://skin/extras/icons/search.png')
        self.art_initialized=False
        self.getControl(13).setVisible(False)
        query=frame.get('query','');kind=frame.get('kind','all')
        self.getControl(406).setLabel(query or 'Název nebo jméno…')
        self.actions={406:self.edit_query}
        for cid,k,label in ((407,'all','Vše'),(408,'movie','Filmy'),(409,'tv','Seriály')):
            self.getControl(cid).setLabel(('●  ' if kind==k else '')+label)
            self.actions[cid]=lambda k=k:self.change_kind(k)
        rows=frame.get('rows',[]);items=[];self.row_actions=[]
        if not query:
            for q in s.history(self.f.core):
                items.append(xbmcgui.ListItem(label=q,label2='Poslední hledání',offscreen=True));self.row_actions.append({'kind':'history','query':q})
            if items:
                items.append(xbmcgui.ListItem(label='Vymazat historii hledání',label2='',offscreen=True));self.row_actions.append({'kind':'clear_history'})
        else:
            for row in rows:
                items.append(xbmcgui.ListItem(label=s.title(row),label2=s.label2(row),offscreen=True));self.row_actions.append({'kind':'result','value':row})
            if frame.get('more'):
                items.append(xbmcgui.ListItem(label='Další výsledky',label2='',offscreen=True));self.row_actions.append({'kind':'more'})
        control.reset();control.addItems(items);control.setVisible(bool(items))
        if items:control.selectItem(min(frame.get('selected',0),len(items)-1))
        elif query:
            self.getControl(13).setText('Žádná shoda. Zkus kratší název nebo zkontroluj rok.');self.getControl(13).setPosition(660,440);self.getControl(13).setVisible(True)
        else:
            self.getControl(13).setText('Zkus třeba „Duna 2021“, „Lupin“ nebo „Tom Hanks“.');self.getControl(13).setPosition(660,440);self.getControl(13).setVisible(True)
        self.getControl(4).setLabel('Podobné názvy' if frame.get('similar') else 'Filmy a seriály s účastí: '+query if frame.get('person') else 'Poslední hledání' if not query and items else 'Výsledky: {}'.format(len(rows)) if rows else '')
        self.getControl(404).controlUp(control if items else self.getControl(406));self.getControl(404).controlDown(self.getControl(406))
        self.setFocusId(frame.get('focus',406) if frame.get('focus')!=510 or items else 406)
    def select(self,action):
        kind=action['kind']
        if kind=='clear_history':
            self.f.core.write_json(os.path.join(self.f.core.PROFILE,'search-history.json'),[])
            self.f.core.write_json(os.path.join(self.f.core.PROFILE,'search-last.json'),{})
            self.nav.current.update(selected=0,focus=406);self.render();return
        if kind not in ('result','history','more'):return super(Search,self).select(action)
        self.remember()
        if kind=='history':self.run_query(action['query']);return
        frame=self.nav.current
        if kind=='more':self.run_query(frame['query'],frame['kind'],frame['selected'],frame.get('person',0),True);return
        row=action['value']
        if row['media_type']=='person':self.run_query(s.title(row),frame['kind'],person=row['id']);return
        item={'kind':row['media_type'],'tmdb_id':row['id'],'title':s.title(row)}
        def done(record):
            self.seasons=None;self.episodes={}
            self.push('overview' if item['kind']=='tv' else 'episode',remember=False,record=record,root_record=record,focus=401)
        self.begin(lambda c,p:self.f.record_for(item),done,'Načítám informace o titulu…')
    def prepare(self,source,resume,remember=True):
        frame=next((f for f in reversed(self.nav.stack) if f['page']=='search'),None)
        if frame:self.origin=dict(self.origin,search=frame['query'],search_index=frame['selected'],search_filter=frame['kind'],search_person=frame.get('person',0))
        super(Search,self).prepare(source,resume,remember)


def show(family,origin,params):
    if family.HOME.getProperty('Family.Search.Active'):return False
    dialog=Search('FamilyBrowser.xml',family.PATH,'Default','1080i').configure_search(family,origin,params)
    monitor=xbmc.Monitor()
    try:
        dialog.show()
        while not dialog.closed and not monitor.abortRequested():
            dialog.poll();monitor.waitForAbort(.05)
        monitor.waitForAbort(.25)
        return dialog.started
    finally:dialog.close()
