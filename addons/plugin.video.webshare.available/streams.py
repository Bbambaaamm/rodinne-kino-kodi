"""Bounded MKV/MP4 header inspection. No Kodi player or media decoding."""
import re
import struct
import time
from urllib.request import Request, urlopen

class ProbeError(Exception):
    pass

class HTTPReader:
    def __init__(self, url, headers, size=0, timeout=12, cancel=None):
        self.url, self.headers, self.size = url, headers, int(size or 0)
        self.deadline = time.monotonic() + timeout
        self.cancel = cancel
        self.blocks, self.bytes, self.requests = {}, 0, 0
    def read(self, offset, length):
        if offset < 0 or length < 0 or length > 2 * 1024**2:
            raise ProbeError('metadata bounds')
        if not length:
            return b''
        output = bytearray()
        while len(output) < length:
            if (self.cancel and self.cancel.is_set()) or time.monotonic() >= self.deadline:
                raise ProbeError('inspection cancelled or timed out')
            current = offset + len(output)
            start = current // 65536 * 65536
            if start not in self.blocks:
                if self.requests >= 40 or self.bytes >= 3 * 1024**2:
                    raise ProbeError('metadata budget')
                end = min(start + 65535, self.size - 1) if self.size else start + 65535
                if end < start:
                    raise ProbeError('end of file')
                headers = dict(self.headers, Range='bytes={}-{}'.format(start, end), Connection='close')
                request = Request(self.url, headers=headers)
                with urlopen(request, timeout=max(.2, min(5, self.deadline-time.monotonic()))) as response:
                    status = response.getcode()
                    if status == 206:
                        match = re.match(r'bytes (\d+)-(\d+)/(\d+|\*)', response.headers.get('Content-Range',''))
                        if not match or int(match[1]) != start:
                            raise ProbeError('incorrect range')
                        if match[3] != '*':
                            self.size = int(match[3])
                    elif status != 200 or start:
                        raise ProbeError('range unavailable')
                    data = response.read(end-start+1)
                self.requests += 1
                self.bytes += len(data)
                self.blocks[start] = data
            block = self.blocks[start]
            part = block[current-start:current-start+length-len(output)]
            if not part:
                raise ProbeError('truncated metadata')
            output.extend(part)
        return bytes(output)

def vint(data, pos=0, element_id=False):
    if pos >= len(data) or not data[pos]:
        raise ProbeError('invalid EBML integer')
    width, mask = 1, 0x80
    while not data[pos] & mask:
        width += 1
        mask >>= 1
    if width > (4 if element_id else 8) or pos+width > len(data):
        raise ProbeError('truncated EBML integer')
    value = int.from_bytes(data[pos:pos+width], 'big')
    if not element_id:
        value &= (1 << (7*width))-1
        if value == (1 << (7*width))-1:
            value = None
    return value, width

def ebml_header(reader, offset):
    data = reader.read(offset, 12)
    ident, width = vint(data, element_id=True)
    size, extra = vint(data, width)
    return ident, size, offset+width+extra

def elements(data):
    pos, count = 0, 0
    while pos < len(data):
        ident, width = vint(data, pos, True)
        size, extra = vint(data, pos+width)
        begin = pos+width+extra
        if size is None or begin+size > len(data) or count > 10000:
            raise ProbeError('invalid EBML element')
        yield ident, data[begin:begin+size]
        pos, count = begin+size, count+1

def text(data):
    return data.decode('utf-8','replace').rstrip('\x00')[:240]

def number(data):
    return int.from_bytes(data,'big') if data else 0

def language(value):
    value=(value or '').lower().replace('_','-').split('-')[0]
    return {'cz':'cs','ces':'cs','cze':'cs','eng':'en','slk':'sk','slo':'sk','deu':'de','ger':'de','ita':'it','fra':'fr','fre':'fr','spa':'es','jpn':'ja','pol':'pl','hun':'hu','por':'pt','rus':'ru','ukr':'uk'}.get(value,value or 'und')

def mkv_tracks(data):
    result=[]
    for ident, entry in elements(data):
        if ident != 0xAE:
            continue
        values=dict(elements(entry))
        kind={1:'video',2:'audio',17:'subtitle'}.get(number(values.get(0x83,b'')))
        if not kind:
            continue
        # An absent language tag is reported as unlabelled, never guessed
        # from the release name or the container's implicit default.
        lang=text(values.get(0x22B59D,values.get(0x22B59C,b'')))
        row={'type':kind,'id':number(values.get(0xD7,b'')),'language':language(lang),
          'language_tag':lang,'name':text(values.get(0x536E,b'')),
          'codec':text(values.get(0x86,b'')),
          'default':bool(number(values.get(0x88,b'\x01'))),
          'forced':bool(number(values.get(0x55AA,b'\x00')))}
        if kind=='audio':
            audio=dict(elements(values.get(0xE1,b'')))
            row['channels']=number(audio.get(0x9F,b'\x01'))
            rate=audio.get(0xB5,b'')
            if len(rate) in (4,8):
                row['samplerate']=round(struct.unpack('>f' if len(rate)==4 else '>d',rate)[0])
        if kind=='video':
            video=dict(elements(values.get(0xE0,b'')))
            row.update(width=number(video.get(0xB0,b'')),height=number(video.get(0xBA,b'')))
        result.append(row)
    if not result:
        raise ProbeError('no tracks')
    return result

def inspect_mkv(reader):
    pos, segment = 0, None
    for _ in range(8):
        ident, size, begin = ebml_header(reader,pos)
        if ident==0x18538067:
            segment=begin
            break
        if size is None:
            raise ProbeError('missing segment')
        pos=begin+size
    if segment is None:
        raise ProbeError('missing segment')
    pos=segment
    for _ in range(64):
        ident,size,begin=ebml_header(reader,pos)
        if ident==0x1654AE6B:
            if size is None or size>1024**2:
                raise ProbeError('tracks bounds')
            return mkv_tracks(reader.read(begin,size))
        if ident==0x114D9B74 and size is not None and size<=256*1024:
            for seekid,seek in elements(reader.read(begin,size)):
                if seekid!=0x4DBB:
                    continue
                values=dict(elements(seek))
                if values.get(0x53AB)==b'\x16\x54\xae\x6b' and 0x53AC in values:
                    target=segment+number(values[0x53AC])
                    tid,tsize,tbegin=ebml_header(reader,target)
                    if tid==0x1654AE6B and tsize is not None and tsize<=1024**2:
                        return mkv_tracks(reader.read(tbegin,tsize))
        if ident==0x1F43B675 or size is None:
            break
        pos=begin+size
    raise ProbeError('tracks not in readable header')

def boxes(data):
    pos,count=0,0
    while pos+8<=len(data):
        size=int.from_bytes(data[pos:pos+4],'big');kind=data[pos+4:pos+8];header=8
        if size==1:
            if pos+16>len(data):raise ProbeError('truncated box')
            size=int.from_bytes(data[pos+8:pos+16],'big');header=16
        if size==0:size=len(data)-pos
        if size<header or pos+size>len(data) or count>10000:raise ProbeError('invalid box')
        yield kind,data[pos+header:pos+size]
        pos+=size;count+=1

def child(data,kind):
    return next((payload for tag,payload in boxes(data) if tag==kind),b'')

def packed_language(value):
    if value in (0,0x7fff) or value<0x400:return 'und'
    result=''.join(chr(((value>>shift)&31)+0x60) for shift in (10,5,0))
    return result if re.fullmatch('[a-z]{3}',result) else 'und'

def mp4_tracks(data):
    result=[]
    for kind,entry in boxes(data):
        if kind!=b'trak':continue
        media=child(entry,b'mdia');head=child(media,b'mdhd');handler=child(media,b'hdlr');track=child(entry,b'tkhd')
        if len(head)<24 or len(handler)<12:continue
        kind={b'soun':'audio',b'vide':'video',b'subt':'subtitle',b'sbtl':'subtitle',b'text':'subtitle',b'clcp':'subtitle'}.get(handler[8:12])
        if not kind:continue
        offset=32 if head[0]==1 else 20
        if len(head)<offset+2:raise ProbeError('truncated media header')
        lang=packed_language(number(head[offset:offset+2]))
        sample=child(child(child(media,b'minf'),b'stbl'),b'stsd')
        codec=text(sample[12:16]) if len(sample)>=16 else ''
        row={'type':kind,'id':len(result)+1,'language':language(lang),'language_tag':lang,
          'name':text(handler[24:]) if len(handler)>24 else '',
          'codec':codec,'default':bool(number(track[:4])&1),'forced':False}
        # Sample description starts with FullBox flags and entry_count.
        if kind=='audio' and len(sample)>=44:
            row['channels']=number(sample[32:34]);row['samplerate']=number(sample[40:44])>>16
        if kind=='video' and len(sample)>=44:
            row.update(width=number(sample[40:42]),height=number(sample[42:44]))
        result.append(row)
    if not result:raise ProbeError('no tracks')
    return result

def inspect_mp4(reader):
    pos=0
    for _ in range(40):
        header=reader.read(pos,16);size=number(header[:4]);kind=header[4:8];width=8
        if size==1:size=number(header[8:16]);width=16
        if size==0:size=reader.size-pos
        if size<width:raise ProbeError('invalid top-level box')
        if kind==b'moov':
            if size-width>2*1024**2:raise ProbeError('movie metadata bounds')
            return mp4_tracks(reader.read(pos+width,size-width))
        pos+=size
        if reader.size and pos>=reader.size:break
    raise ProbeError('missing movie metadata')

def inspect(reader):
    signature=reader.read(0,16)
    if signature[:4]==b'\x1aE\xdf\xa3':
        tracks=inspect_mkv(reader);container='mkv'
    elif signature[4:8] in (b'ftyp',b'moov',b'wide',b'free',b'mdat'):
        tracks=inspect_mp4(reader);container='mp4'
    else:
        raise ProbeError('unsupported container')
    return {'state':'verified','container':container,'tracks':tracks,'bytes_read':getattr(reader,'bytes',0)}
