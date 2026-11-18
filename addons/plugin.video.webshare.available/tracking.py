"""On-device resume tracking; cloud scrobbling remains with the existing Trakt add-on."""
import json
import os
import time
from urllib.parse import urlencode
import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs

HOME = xbmcgui.Window(10000)
PROFILE = xbmcvfs.translatePath(xbmcaddon.Addon('plugin.video.webshare.available').getAddonInfo('profile'))

def write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + '.new'
    with open(temp, 'w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False)
    os.replace(temp, path)

def read_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}

def restore_origin(origin):
    wid = origin.get('window', 10000)
    if wid not in (10000, 10025, 11101, 11102, 11103, 11104, 11105):
        wid = 10000
    snapshot = origin.get('search_snapshot')
    if snapshot:
        if HOME.getProperty('Family.Search.RestoredToken')==str(snapshot):return
        HOME.setProperty('Family.Search.Restore', str(snapshot))
        if HOME.getProperty('Family.Search.Active'):
            HOME.setProperty('Family.Search.RestoreRequest',str(snapshot))
            return
        xbmc.executebuiltin('ActivateWindow(11105)')
        xbmc.sleep(700)
        if not HOME.getProperty('Family.Search.Active'):
            try:opening=float(HOME.getProperty('Family.SearchOpening') or 0)
            except ValueError:opening=0
            if not opening or time.time()-opening>5:
                xbmc.executebuiltin('RunPlugin(plugin://plugin.video.webshare.available/?action=search&restore=' + str(snapshot) + ')')
        return
    path = origin.get('path', '')
    if wid == 10025 and path.startswith(('plugin://plugin.video.webshare.available/', 'plugin://plugin.video.themoviedb.helper/')):
        xbmc.executebuiltin('ActivateWindow(10025,"' + path.replace('"', '') + '",return)')
    else:
        xbmc.executebuiltin('ActivateWindow(' + str(wid) + ')')
    xbmc.sleep(450)
    control = int(origin.get('control') or 0)
    position = max(0, int(origin.get('position') or 0))
    if origin.get('row') is not None and wid in (10000, 11101, 11102, 11103, 11104):
        xbmc.executebuiltin('SetFocus(601,{},absolute)'.format(max(0, int(origin['row']))))
        xbmc.sleep(200)
    wanted = str(origin.get('tmdb_id') or '')
    if wanted and control:
        for index in range(30):
            base = 'Container({}).ListItemAbsolute({})'.format(control, index)
            if xbmc.getInfoLabel(base + '.Property(tmdb_id)') != wanted:
                continue
            season = str(origin.get('season') or '')
            episode = str(origin.get('episode') or '')
            if season and season != '-1' and xbmc.getInfoLabel(base + '.Season') != season:
                continue
            if episode and episode != '-1' and xbmc.getInfoLabel(base + '.Episode') != episode:
                continue
            position = index
            break
    if control:
        xbmc.executebuiltin('SetFocus({},{},absolute)'.format(control, position))
    if origin.get('search'):
        query = str(origin['search'])[:120]
        args = urlencode({'action': 'search', 'query': query, 'selected': max(0, int(origin.get('search_index') or 0)), 'filter': origin.get('search_filter','all'), 'person': int(origin.get('search_person') or 0)})
        xbmc.executebuiltin('RunPlugin(plugin://plugin.video.webshare.available/?' + args + ')')

class ResumePlayer:
    def __init__(self):
        self._active = []
        self._properties = {}
        self.context = None
        self.position = 0
        self.duration = 0
        self.finished = False
        self.restore_pending = None
        self.resume_due = None
        self.last_checkpoint = 0
        self.stable_since = None
        self.preferences_applied = False
    def rpc(self, method, params=None):
        request = {'jsonrpc': '2.0', 'id': 1, 'method': method}
        if params is not None:
            request['params'] = params
        response = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
        if 'error' in response:
            raise RuntimeError('Player API is not ready')
        return response.get('result')
    def refresh(self):
        self._active = self.rpc('Player.GetActivePlayers') or []
        self._properties = self.rpc('Player.GetProperties', {'playerid': 1, 'properties': ['time', 'totaltime', 'speed']}) if self.isPlayingVideo() else {}
    def isPlaying(self):
        return bool(self._active)
    def isPlayingVideo(self):
        return any(row.get('type') == 'video' for row in self._active)
    @staticmethod
    def seconds(value):
        return value.get('hours', 0) * 3600 + value.get('minutes', 0) * 60 + value.get('seconds', 0) + value.get('milliseconds', 0) / 1000
    def getTime(self):
        return self.seconds(self._properties.get('time') or {})
    def getTotalTime(self):
        return self.seconds(self._properties.get('totaltime') or {})
    def seekTime(self, target):
        milliseconds = max(0, int(round(target * 1000)))
        value = {'hours': milliseconds // 3600000, 'minutes': milliseconds // 60000 % 60, 'seconds': milliseconds // 1000 % 60, 'milliseconds': milliseconds % 1000}
        self.rpc('Player.Seek', {'playerid': 1, 'value': {'time': value}})
    def tick(self):
        try:
            self.refresh()
        except RuntimeError:
            return
        # Track playback through the player API without native Python player
        # callbacks, including during service shutdown and app restarts.
        pending = HOME.getProperty('Family.ManagedStartAt')
        if not self.context and pending and self.isPlayingVideo():
            try:
                candidate = json.loads(HOME.getProperty('Family.PlaybackContext'))
                if time.time() - float(pending) < 120 and time.time() - candidate.get('created', 0) < 120:
                    self.context = candidate
                    self.position = 0
                    self.duration = 0
                    self.resume_due = time.monotonic() + 1.2
                    self.last_checkpoint = time.monotonic()
                    self.stable_since = None
                    self.preferences_applied = False
                    HOME.setProperty('Family.Player.Managed', 'true')
                    HOME.clearProperty('Family.ManagedStartAt')
            except (ValueError, TypeError):
                pass
        if self.context and self.isPlayingVideo():
            try:
                previous_position = self.position
                self.position = self.getTime()
                self.duration = self.getTotalTime()
                if self.position > 1 and self.position > previous_position + .01:
                    self.stable_since = self.stable_since or time.monotonic()
                else:
                    self.stable_since = None
                ready = self.stable_since and time.monotonic() - self.stable_since >= .8
                if self.resume_due and ready and time.monotonic() >= self.resume_due and self.duration > 0:
                    if not self.preferences_applied:
                        changed = self.apply_stream_preferences()
                        self.preferences_applied = True
                        if changed:
                            self.stable_since = None
                            self.resume_due = time.monotonic() + 2
                            return
                    target = float(self.context.get('resume') or 0)
                    self.resume_due = None
                    if target >= 15:
                        target = min(target, max(0, self.duration - 5))
                        self.seekTime(target)
                        self.position = target
                        HOME.setProperty('Family.ResumeApplied', str(round(target, 2)))
                if self.position >= 15 and time.monotonic() - self.last_checkpoint >= 15:
                    self.save_progress(False)
                    self.last_checkpoint = time.monotonic()
            except RuntimeError:
                pass
        elif self.context and not self.isPlayingVideo():
            self.commit(False)
        if self.restore_pending and time.monotonic() >= self.restore_pending[0]:
            origin = self.restore_pending[1]
            self.restore_pending = None
            if not self.isPlaying():
                restore_origin(origin)
    def apply_stream_preferences(self):
        def rpc(method, params):
            value = json.loads(xbmc.executeJSONRPC(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})))
            if 'error' in value:
                raise RuntimeError('Stream preferences not ready')
            return value.get('result')
        data = rpc('Player.GetProperties', {'playerid': 1, 'properties': ['audiostreams', 'currentaudiostream', 'subtitles', 'subtitleenabled']}) or {}
        audio = data.get('audiostreams') or []
        language_rank = {'cs': 0, 'ces': 0, 'cze': 0, 'czech': 0, 'sk': 1, 'slk': 1, 'slo': 1, 'en': 2, 'eng': 2, 'english': 2}
        def language(stream):
            return str(stream.get('language') or '').lower().split('-')[0]
        known = [stream for stream in audio if language(stream) in language_rank]
        chosen = min(known, key=lambda stream: language_rank[language(stream)]) if known else data.get('currentaudiostream') or {}
        current = data.get('currentaudiostream') or {}
        changed = False
        if chosen and chosen.get('index') != current.get('index'):
            rpc('Player.SetAudioStream', {'playerid': 1, 'stream': chosen['index']})
            changed = True
        subtitle_language = ''
        if language_rank.get(language(chosen), 99) != 0:
            czech = [stream for stream in data.get('subtitles') or [] if language(stream) in ('cs', 'ces', 'cze', 'czech')]
            if czech:
                selected = min(czech, key=lambda stream: bool(stream.get('isforced')))
                rpc('Player.SetSubtitle', {'playerid': 1, 'subtitle': selected['index'], 'enable': True})
                subtitle_language = 'cze'
                changed = True
        HOME.setProperty('Family.StreamPreferences', json.dumps({'audio': language(chosen), 'subtitles': subtitle_language, 'changed': changed}))
        return changed
    def save_progress(self, ended):
        if not self.context:
            return
        record = self.context['record']
        item = record['item']
        key = ':'.join(str(v) for v in (item['kind'], item['tmdb_id'], item.get('season'), item.get('episode')))
        completed = bool(ended or (self.duration > 0 and self.position / self.duration >= 0.9))
        path = os.path.join(PROFILE, 'family-progress.json')
        saved = read_json(path)
        saved[key] = {'kind': item['kind'], 'item': item, 'position': 0 if completed else round(self.position, 2), 'duration': self.duration, 'completed': completed, 'updated': time.time()}
        write_json(path, saved)
        return key, completed

    def commit(self, ended):
        if not self.context:
            return
        if self.position < 2 and not ended:
            self.restore_pending = (time.monotonic() + .7, self.context.get('origin') or {})
            self.context = None
            self.resume_due = None
            HOME.clearProperty('Family.Player.Managed')
            return
        key, completed = self.save_progress(ended)
        revision=str(time.time())
        item=self.context['record']['item']
        if completed and item['kind']=='episode':
            HOME.setProperty('Family.Paging.ChangedShow',str(item['tmdb_id'])+':'+revision)
        HOME.setProperty('Family.Paging.Revision',revision)
        for category in ('source', 'list'):
            folder = os.path.join(PROFILE, 'cache', category)
            for name in ('movie_playback.json', 'episode_playback.json', 'episode_next.json', 'family_personal_both_history.json'):
                filename = os.path.join(folder, name)
                if os.path.isfile(filename):
                    os.remove(filename)
        HOME.setProperty('Family.LastPlayback', json.dumps({'identity': key, 'position': self.position, 'completed': completed, 'metadata': 'assigned', 'cloud_owner': 'script.trakt'}))
        self.restore_pending = (time.monotonic() + 0.7, self.context.get('origin') or {})
        self.context = None
        self.resume_due = None
        HOME.clearProperty('Family.Player.Managed')
