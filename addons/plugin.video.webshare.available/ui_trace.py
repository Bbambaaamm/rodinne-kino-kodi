"""Optional bounded stack locations. Arguments, messages and URLs are never read."""
import json
import os
import sys
import threading
import time

ALLOWED={'discover_ui.py','browser.py','discovery.py','searching.py','family.py','default.py','tracking.py','maintenance.py'}

class Trace:
    def __init__(self,profile):
        self.path=os.path.join(profile,'family-ui-trace.json');self.stage='opening';self.samples=[];self.stop=threading.Event()
        self.worker=threading.Thread(target=self.run,daemon=True);self.worker.start()
    def mark(self,stage):self.stage=stage
    def run(self):
        while not self.stop.wait(.75):
            threads=[]
            for frame in sys._current_frames().values():
                stack=[]
                while frame and len(stack)<16:
                    name=os.path.basename(frame.f_code.co_filename)
                    if name in ALLOWED:stack.append({'file':name,'line':frame.f_lineno,'function':frame.f_code.co_name})
                    frame=frame.f_back
                if stack:threads.append(stack)
            self.samples=(self.samples+[{'time':round(time.time(),3),'stage':self.stage,'stacks':threads}])[-6:]
            try:
                with open(self.path+'.new','w',encoding='utf-8') as f:json.dump({'arguments_recorded':False,'samples':self.samples},f)
                os.replace(self.path+'.new',self.path)
            except OSError:pass
    def close(self):self.stage='closed';self.stop.set();self.worker.join(1)
