"""One-window navigation, including selection and cancellable work identity."""
class Navigation:
    def __init__(self,record):
        self.stack=[]
        self.current={'page':'overview' if record['item']['kind']=='tv' else 'episode','record':record,'root_record':record,'selected':0,'focus':401}
        self.generation=0
    @property
    def root(self):return self.current['root_record']
    def push(self,page,**data):
        self.stack.append(self.current)
        self.current={'page':page,'record':self.current['record'],'root_record':self.root,'selected':0,'focus':510,**data}
    def back(self):
        if not self.stack:return False
        self.current=self.stack.pop();return True
    def begin(self):
        self.generation+=1;return self.generation
    def cancel(self):self.generation+=1
    def accepts(self,generation):return generation==self.generation
