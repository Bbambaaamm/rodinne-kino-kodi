"""Pure matching and presentation rules for the family source picker."""
import re
import unicodedata
from difflib import SequenceMatcher

VIDEO = ('.mkv', '.mp4', '.avi', '.mov', '.m4v', '.ts', '.m2ts', '.webm')
EPISODES = (
    re.compile(r'(?i)s0*(\d{1,2})[\s._-]*e0*(\d{1,3})(?!\d)'),
    re.compile(r'(?i)(?<!\d)(\d{1,2})x0*(\d{1,3})(?!\d)'),
    re.compile(r'(?i)season[\s._-]*(\d{1,2})[\s._-]*episode[\s._-]*(\d{1,3})(?!\d)'),
)
BAD = re.compile(r'(?i)(?:^|[\W_])(trailer|teaser|sample|interview|soundtrack)(?:[\W_]|$)')
RELEASE = re.compile(r'(?i)\b(?:2160p|1080p|720p|480p|bluray|blu.ray|web.?dl|webrip|brrip|dvdrip|hdtv|remux|x26[45]|h26[45]|hevc|av1|uhd|hdr|czdab|cz.dab|czech|dabing)\b')

def normal(value):
    value = ''.join(c for c in unicodedata.normalize('NFKD', value or '') if not unicodedata.combining(c)).lower()
    return re.sub(r'[^a-z0-9]+', ' ', value).strip()

def episode_source_titles(titles):
    """Keep official identities and search distinctive canonical subtitles too."""
    def unique(values):
        result, seen = [], set()
        for value in values:
            key = normal(value) or value.casefold().strip()
            if key and key not in seen:
                result.append(value.strip())
                seen.add(key)
        return result

    full = unique(titles)
    shortened = []
    stopwords = {'the', 'a', 'an', 'of', 'and', 'or', 'to', 'for', 'in', 'on', 'at',
                 'by', 'with', 'from', 'i', 'v', 've', 'na', 'do', 'o', 'pro',
                 'z', 'ze', 's', 'se', 'u'}
    for title in full[:2]:
        prefix, separator, subtitle = title.partition(':')
        if not separator or not normal(prefix):
            continue
        words = normal(subtitle).split()
        distinctive = [word for word in words if word not in stopwords]
        # Single words, numbered parts and generic labels are not safe show
        # identities. Do not match arbitrary words from a filename.
        if (len(distinctive) < 2 or sum(map(len, distinctive)) < 8
                or any(character.isdigit() for character in subtitle)
                or normal(subtitle) in ('the series', 'tv series', 'limited series', 'new series')):
            continue
        shortened.append(subtitle.strip())
    aliases = unique(full + shortened)
    # Keep four requests: CZ/original names and their short forms take
    # precedence over less relevant translations.
    queries = unique(full[:2] + shortened + full[2:])[:4]
    return aliases, queries


def markers(name):
    result = []
    for regex in EPISODES:
        for match in regex.finditer(name or ''):
            result.append((int(match[1]), int(match[2]), match.start(), match.end()))
    return result

def strict_episode(name, season, episode):
    found = markers(name)
    if not found or {(s, e) for s, e, _, _ in found} != {(int(season), int(episode))}:
        return False
    for _, _, _, end in found:
        # Reject multi-episode ranges and concatenated episode packs.
        if re.match(r'(?i)(?:[ ._-]*e\d|[-–]\s*(?:e)?\d)', name[end:]):
            return False
    return True

def title_part(name, kind, year=0):
    base = re.sub(r'\.[A-Za-z0-9]{2,5}$', '', name or '')
    cuts = []
    if kind == 'episode':
        cuts.extend(start for _, _, start, _ in markers(base))
    elif year:
        match = re.search(r'(?<!\d)' + str(int(year)) + r'(?!\d)', base)
        if match:
            cuts.append(match.start())
    match = RELEASE.search(base)
    if match:
        cuts.append(match.start())
    return normal(base[:min(cuts)] if cuts else base)

def title_matches(name, aliases, kind, year=0):
    part = title_part(name, kind, year)
    if not part:
        return False
    compact = part.replace(' ', '')
    for alias in aliases:
        expected = normal(alias)
        if not expected:
            continue
        exp_numbers = set(re.findall(r'\b\d+\b', expected))
        numbers = set(re.findall(r'\b\d+\b', part))
        if numbers != exp_numbers and (numbers or exp_numbers):
            continue
        a, b = expected.replace(' ', ''), compact
        if a == b:
            return True
        if b.startswith(a) and len(a) >= 6:
            suffix = b[len(a):]
            if not suffix or suffix in ('cz', 'czdab', 'en', 'sk', 'multi', 'dab'):
                return True
        if SequenceMatcher(None, expected, part).ratio() >= 0.91:
            return True
    return False

def valid_source(candidate, aliases, kind, year=0, season=None, episode=None):
    name = candidate.get('name', '')
    if not candidate.get('ident') or not name.lower().endswith(VIDEO) or BAD.search(name):
        return False
    if kind == 'episode':
        if season is None or episode is None or not strict_episode(name, season, episode):
            return False
    else:
        if markers(name):
            return False
        years = {int(x) for x in re.findall(r'(?<!\d)((?:19|20)\d{2})(?!\d)', name)}
        if year and years and int(year) not in years:
            return False
    return title_matches(name, aliases, kind, year)

def attributes(name):
    text = normal(name)
    cz_subs = bool(re.search(r'\b(?:cz|czech|ceske) (?:sub|subs|tit|titulky)\b|\bczsub\b', text))
    cz_audio = bool(re.search(r'\b(?:czdab|cz dab|czech dub|cesky dabing)\b', text))
    if (re.search(r'(?i)(?:^|[\W_])(?:cz|cze|czech|cesk\w*|czdab)(?:[\W_]|$)', name) or 'cz dab' in text) and (not cz_subs or cz_audio):
        language, lang_rank = 'Česky', 0
    elif re.search(r'\b(?:sk|slovak|skdab)\b', text):
        language, lang_rank = 'Slovensky', 1
    elif re.search(r'\b(?:en|eng|english)\b', text):
        language, lang_rank = 'Anglicky', 2
    else:
        language, lang_rank = 'Zvuk v názvu neuveden', 3
    if cz_subs and not cz_audio:
        language += ' + české titulky'
    if re.search(r'\b(?:2160p|4k|uhd)\b', text):
        resolution = 2160
    elif re.search(r'\b(?:1080p|fhd)\b', text):
        resolution = 1080
    elif re.search(r'\b(?:720p)\b', text):
        resolution = 720
    elif '480p' in text:
        resolution = 480
    else:
        resolution = 0
    quality = '4K' if resolution == 2160 else (str(resolution) + 'p' if resolution else 'Kvalita neuvedena')
    return {'language': language, 'language_rank': lang_rank, 'resolution': resolution, 'quality': quality,
            'codec': 'HEVC' if any(x in text for x in ('x265', 'h265', 'hevc')) else ('AV1' if 'av1' in text else 'AVC' if any(x in text for x in ('x264', 'h264')) else '')}

def rank_source(candidate):
    data = source_attributes(candidate) if 'streams' in candidate else attributes(candidate.get('name', ''))
    res_rank = {1080: 0, 720: 1, 480: 2, 0: 3, 2160: 4}[data['resolution']]
    return (data['language_rank'], res_rank, 1 if data['codec'] == 'AV1' else 0, candidate.get('size') or 0)

def source_label(candidate):
    data = source_attributes(candidate)
    size = candidate.get('size')
    parts = [data['quality']]
    if data['codec']:
        parts.append(data['codec'])
    if size:
        parts.append(('{:.2f} GB'.format(size / 1000**3)).replace('.', ','))
    return '  •  '.join(parts)

LANGUAGES = {'cs':'CZ','sk':'SK','en':'EN','de':'DE','it':'IT','fr':'FR','es':'ES','pl':'PL','hu':'HU','pt':'PT','ru':'RU','uk':'UK','ja':'JA','und':'?','mul':'MULTI'}

def language_order(code):
    return ({'CZ':0,'SK':1,'EN':2,'?':9}.get(code,3),code)

def codec_label(value):
    return {'A_EAC3':'E-AC3','A_AC3':'AC3','A_AAC':'AAC','A_OPUS':'OPUS','A_DTS':'DTS','A_FLAC':'FLAC','A_VORBIS':'VORBIS','A_MPEG/L3':'MP3','mp4a':'MP4A','ac-3':'AC3','ec-3':'E-AC3','V_MPEGH/ISO/HEVC':'HEVC','V_MPEG4/ISO/AVC':'H.264','S_TEXT/UTF8':'SRT','S_TEXT/ASS':'ASS','S_TEXT/SSA':'SSA','S_HDMV/PGS':'PGS'}.get(value,value[2:] if value.startswith('A_') else value)

def source_summary(candidate):
    metadata=candidate.get('streams') or {}
    if metadata.get('state')!='verified':
        return 'Zvuk: ? • Titulky: ? (neověřeno)'
    groups={};subtitles=[]
    for track in metadata['tracks']:
        lang=LANGUAGES.get(track.get('language'),track.get('language','und').upper())
        if track['type']=='audio':
            key=(codec_label(track.get('codec','')),track.get('channels'))
            languages=groups.setdefault(key,{})
            languages[lang]=languages.get(lang,0)+1
        elif track['type']=='subtitle' and lang not in subtitles:
            subtitles.append(lang)
    audio=[]
    for (codec,channels),languages in sorted(groups.items(),key=lambda entry:min(language_order(code) for code in entry[1])):
        codes='/'.join(code+('×'+str(languages[code]) if languages[code]>1 else '') for code in sorted(languages,key=language_order))
        parts=[codes,codec]
        if channels:parts.append(str(channels)+'ch')
        audio.append(' '.join(p for p in parts if p))
    return 'Zvuk: '+('; '.join(audio) or '—')+' • Titulky: '+('/'.join(sorted(subtitles,key=language_order)) or '—')

def source_attributes(candidate):
    data = attributes(candidate.get('name',''))
    metadata = candidate.get('streams') or {}
    if metadata.get('state') != 'verified':
        return dict(data, language='Zvuk neověřen', language_rank=4, quality=data['quality'] + ' (název)')
    audio = [t for t in metadata['tracks'] if t['type']=='audio']
    languages = list(dict.fromkeys(t.get('language') or 'und' for t in audio))
    names = [LANGUAGES.get(lang,lang.upper()) for lang in languages]
    label = ' + '.join(names) if names else 'Bez zvukové stopy'
    ranks = {'cs':0,'sk':1,'en':2}
    data.update(language=label, language_rank=min((ranks.get(lang,3) for lang in languages), default=4))
    video = next((t for t in metadata['tracks'] if t['type']=='video'),{})
    width,height = int(video.get('width') or 0),int(video.get('height') or 0)
    if width and height:
        resolution = 2160 if width>=3840 or height>=2160 else 1080 if width>=1920 or height>=1080 else 720 if width>=1280 or height>=720 else 480
        data.update(resolution=resolution,quality='{}×{}'.format(width,height))
    codec = video.get('codec','').lower()
    data['codec'] = 'HEVC' if any(x in codec for x in ('hevc','hvc1','hev1')) else 'AVC' if any(x in codec for x in ('avc','avc1')) else 'AV1' if 'av1' in codec else ''
    return data

def track_lines(candidate):
    metadata=candidate.get('streams') or {}
    if metadata.get('state')!='verified':
        return ['Stopy se nepodařilo ověřit z hlavičky videa. Jazyk není odhadnutý z názvu souboru.']
    rows=[];counts={}
    for track in metadata['tracks']:
        kind={'audio':'Zvuk','video':'Obraz','subtitle':'Titulky'}[track['type']]
        counts[kind]=counts.get(kind,0)+1
        parts=[kind+' '+str(counts[kind])]
        if track['type']!='video':
            parts.append(LANGUAGES.get(track.get('language'),track.get('language','und').upper()))
            if track.get('language')=='und':parts.append('jazyk stopy neoznačen')
        parts.append(codec_label(track.get('codec','')))
        if track.get('channels'):parts.append(str(track['channels'])+'ch')
        if track.get('samplerate'):parts.append('{:g} kHz'.format(track['samplerate']/1000))
        if track.get('width'):parts.append('{}×{}'.format(track['width'],track['height']))
        language_names={'cs':('cs','cz','cze','ces','czech','cesky','cestina'),'en':('en','eng','english'),'sk':('sk','slk','slo','slovak'),'de':('de','deu','ger','german'),'it':('it','ita','italian')}
        name=track.get('name') or ''
        if name and normal(name) not in language_names.get(track.get('language'),(track.get('language'),)):
            parts.append(name)
        if track.get('default'):parts.append('výchozí')
        if track.get('forced'):parts.append('vynucené')
        rows.append(' • '.join(parts))
    return rows
