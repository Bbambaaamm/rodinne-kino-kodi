"""Keep Trakt-backed rows current without doing network work on Kodi's UI thread."""
import hashlib
import json
import os
import queue
import threading
import time


STATE_FILE = 'trakt-activities.json'
STATUS = 'Family.TraktSync.Status'
URGENT = 'Family.TraktSync.Urgent'
POLL_SECONDS = 45
RETRY_SECONDS = 30

ACTIVITY_FIELDS = {
    'movies': ('watched_at', 'paused_at'),
    'episodes': ('watched_at', 'paused_at'),
}

DISPLAY_LISTS = (
    ('movie', 'playback'),
    ('episode', 'playback'),
    ('episode', 'next'),
)

RESET_KEYS = (
    'list_movie_playback',
    'list_episode_playback',
    'list_episode_next',
    'personal_both_history',
    'personal_movie_history',
    'personal_tv_history',
)


def activity_snapshot(value):
    """Return only timestamps that can change content or watch decoration."""
    value = value if isinstance(value, dict) else {}
    return {
        section: {field: (value.get(section) or {}).get(field) or '' for field in fields}
        for section, fields in ACTIVITY_FIELDS.items()
    }


def snapshot_changes(previous, current):
    changed = set()
    previous = previous if isinstance(previous, dict) else {}
    for section, fields in current.items():
        before = previous.get(section) or {}
        if any(before.get(field, '') != stamp for field, stamp in fields.items()):
            changed.add(section)
    return changed


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def invalidate_lists(home, profile, stamp=None, reason='trakt', changed=()):
    """Invalidate every watch-state view and request visible home rows again."""
    stamp = stamp or str(time.time())
    home.setProperty('Family.Paging.Revision', stamp)
    home.setProperty('Family.TraktSync.LastChange', json.dumps({
        'stamp': stamp, 'reason': reason, 'sections': sorted(changed)
    }))
    for key in RESET_KEYS:
        home.setProperty('Family.Paging.Count.' + key, '20')
    for kind, source in DISPLAY_LISTS:
        key = 'list_' + kind + '_' + source
        base = 'Family.Paging.Display.'
        home.clearProperty(base + 'Error.' + key)
        home.setProperty(base + 'Wanted.' + key, '20')
        # Change the native content URL immediately. The background pager
        # changes it once more after verified cards for the new revision exist.
        home.setProperty(base + 'Version.' + key, stamp)
    for category in ('source', 'list'):
        folder = os.path.join(profile, 'cache', category)
        for name in ('movie_playback.json', 'episode_playback.json',
                     'episode_next.json', 'family_personal_both_history.json',
                     'family_personal_movie_history.json',
                     'family_personal_tv_history.json'):
            _remove(os.path.join(folder, name))
    return stamp


class TraktActivitySync:
    def __init__(self, family):
        self.family = family
        self.path = os.path.join(family.PROFILE, STATE_FILE)
        self.saved = family.core.read_json(self.path, {}) or {}
        self.results = queue.Queue(maxsize=1)
        self.pending = False
        self.closed = threading.Event()
        self.next_sync = time.monotonic() + 2
        self.urgent_seen = ''
        self.urgent_until = 0
        self.last_playback = family.HOME.getProperty('Family.LastPlayback')

    def download(self):
        f = self.family
        try:
            _, token = f.auth()
            owner = hashlib.sha256(token.encode('utf-8')).hexdigest()
            response = f.core.trakt_request('/sync/last_activities')
            if not isinstance(response, dict) or any(
                    not isinstance(response.get(section), dict) for section in ACTIVITY_FIELDS):
                raise ValueError('Incomplete Trakt activity response')
            current = activity_snapshot(response)
            old = self.saved if self.saved.get('owner') == owner else {}
            changed = snapshot_changes(old.get('activities'), current)
            first = not old.get('activities')
            data = {'owner': owner, 'activities': current, 'updated': time.time()}
            if not self.closed.is_set():
                self.results.put(('ready', data, changed, first))
        except (OSError, RuntimeError, ValueError, AttributeError, TypeError, KeyError) as error:
            if not self.closed.is_set():
                self.results.put(('retry', type(error).__name__, set(), False))

    def tick(self, browsing):
        now = time.monotonic()
        f = self.family
        last_playback = f.HOME.getProperty('Family.LastPlayback')
        if last_playback and last_playback != self.last_playback:
            self.last_playback = last_playback
            stamp = invalidate_lists(f.HOME, f.PROFILE, reason='local_playback')
            f.HOME.setProperty(URGENT, stamp)
        if self.pending:
            try:
                state, payload, changed, first = self.results.get_nowait()
            except queue.Empty:
                pass
            else:
                self.pending = False
                if state == 'ready':
                    restart = not f.HOME.getProperty('Family.Paging.Revision')
                    if first or changed or restart:
                        invalidate_lists(f.HOME, f.PROFILE, reason='trakt_activity',
                                         changed=changed or set(ACTIVITY_FIELDS))
                    if first or changed:
                        self.urgent_until = 0
                        try:
                            f.core.write_json(self.path, payload)
                        except OSError:
                            pass
                    self.saved = payload
                    f.HOME.setProperty(STATUS, json.dumps({
                        'state': 'ready', 'changed': sorted(changed),
                        'first': first, 'checked': time.time()
                    }))
                    self.next_sync = now + (5 if now < self.urgent_until else POLL_SECONDS)
                else:
                    f.HOME.setProperty(STATUS, json.dumps({
                        'state': 'retry', 'reason': payload, 'checked': time.time()
                    }))
                    self.next_sync = now + (5 if now < self.urgent_until else RETRY_SECONDS)
        urgent = f.HOME.getProperty(URGENT)
        if urgent and urgent != self.urgent_seen:
            self.urgent_seen = urgent
            self.urgent_until = now + 60
            self.next_sync = min(self.next_sync, now + 3)
        if browsing and not self.pending and now >= self.next_sync:
            self.pending = True
            threading.Thread(target=self.download, daemon=True).start()

    def close(self):
        self.closed.set()
