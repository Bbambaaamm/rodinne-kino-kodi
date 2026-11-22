"""Explicit, temporary software playback; no title or source-specific rules.

Only the service owns this transaction. The recovery journal contains the two
original decoder switches, never media paths, account details or playback URLs.
"""
import hashlib
import json
import os
import tempfile
import time


DECODER_SETTINGS = ('videoplayer.usemediacodec', 'videoplayer.usemediacodecsurface')


def seconds(value):
    return (value.get('hours', 0) * 3600 + value.get('minutes', 0) * 60
            + value.get('seconds', 0) + value.get('milliseconds', 0) / 1000)


def kodi_time(value):
    ms = max(0, round(value * 1000))
    return {'hours': ms // 3600000, 'minutes': ms // 60000 % 60,
            'seconds': ms // 1000 % 60, 'milliseconds': ms % 1000}


class CompatibilityPlayer:
    def __init__(self, rpc, journal, publish, now=time.monotonic):
        self.rpc, self.journal, self.publish, self.now = rpc, journal, publish, now
        self.active = None
        self.recovery_pending = os.path.exists(journal)
        self.next_recovery = 0
        if self.recovery_pending:
            self.recover()
        else:
            self.status('idle')

    def status(self, phase, **values):
        self.publish({'phase': phase, 'busy': bool(self.active),
                      'recovery_pending': self.recovery_pending, **values})

    def write_journal(self, settings):
        folder = os.path.dirname(self.journal)
        os.makedirs(folder, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=folder, delete=False) as stream:
                temporary = stream.name
                json.dump({'version': 1, 'settings': settings}, stream)
            os.replace(temporary, self.journal)
        finally:
            if temporary and os.path.exists(temporary):
                os.remove(temporary)

    def restore(self):
        if not os.path.exists(self.journal):
            self.recovery_pending = False
            return
        self.recovery_pending = True
        with open(self.journal, encoding='utf-8') as stream:
            saved = json.load(stream)
        settings = saved.get('settings', {})
        if (saved.get('version') != 1 or set(settings) != set(DECODER_SETTINGS)
                or any(type(value) is not bool for value in settings.values())):
            raise ValueError('Invalid decoder recovery journal')
        # Attempt both restorations even when one setting temporarily fails.
        errors = []
        for key, original in settings.items():
            try:
                value = self.rpc('Settings.GetSettingValue', {'setting': key})
                if not value or type(value.get('value')) is not bool:
                    raise RuntimeError('Decoder setting unavailable')
                if value['value'] != original:
                    if not self.rpc('Settings.SetSettingValue', {'setting': key, 'value': original}):
                        raise RuntimeError('Decoder restoration refused')
                if self.rpc('Settings.GetSettingValue', {'setting': key}) != {'value': original}:
                    raise RuntimeError('Decoder restoration not confirmed')
            except (RuntimeError, TypeError, KeyError) as error:
                errors.append(error)
        if errors:
            raise RuntimeError('Decoder restoration pending')
        os.remove(self.journal)
        self.recovery_pending = False

    def recover(self):
        try:
            self.restore()
        except (OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
            self.recovery_pending = True
            self.next_recovery = self.now() + 1
            self.status('recovery_pending', error=type(error).__name__, settings_restored=False)
            return False
        self.status('recovered', settings_restored=True)
        return True

    def current(self):
        players = self.rpc('Player.GetActivePlayers') or []
        if not any(row.get('playerid') == 1 and row.get('type') == 'video' for row in players):
            return None
        value = self.rpc('Player.GetItem', {'playerid': 1, 'properties': ['file']}) or {}
        path = (value.get('item') or {}).get('file')
        if not path:
            raise RuntimeError('Current playback identity unavailable')
        # Only an in-memory comparison. Neither the path nor its digest is exported.
        return path, hashlib.sha256(path.encode('utf-8')).digest()

    def start(self, play=True):
        if self.active or self.recovery_pending:
            self.status('opening' if self.active else 'recovery_pending')
            return False
        try:
            current = self.current()
            if current is None:
                self.status('no_video')
                return False
            labels = self.rpc('XBMC.GetInfoLabels', {'labels': ['Player.Process(videodecoder)']}) or {}
            booleans = self.rpc('XBMC.GetInfoBooleans', {'booleans': ['Player.Process(videohwdecoder)']}) or {}
            if (booleans.get('Player.Process(videohwdecoder)') is False
                    and labels.get('Player.Process(videodecoder)')):
                self.rpc('Player.PlayPause', {'playerid': 1, 'play': bool(play)})
                self.status('already_compatible', settings_restored=True,
                            decoder=labels['Player.Process(videodecoder)'])
                return False
            properties = self.rpc('Player.GetProperties', {'playerid': 1, 'properties': [
                'time', 'totaltime', 'playlistid', 'position', 'currentaudiostream',
                'currentsubtitle', 'subtitleenabled']})
            if not properties:
                raise RuntimeError('Playback state unavailable')
            original = {}
            for key in DECODER_SETTINGS:
                value = self.rpc('Settings.GetSettingValue', {'setting': key})
                if not value or type(value.get('value')) is not bool:
                    raise RuntimeError('Software mode unavailable on this platform')
                original[key] = value['value']
            self.write_journal(original)
            self.recovery_pending = True
            self.active = {'identity': current[1], 'target': seconds(properties['time']),
                           'audio': (properties.get('currentaudiostream') or {}).get('index'),
                           'subtitle': (properties.get('currentsubtitle') or {}).get('index'),
                           'subtitle_enabled': properties.get('subtitleenabled', False),
                           'play': bool(play), 'phase': 'opening', 'started': self.now(),
                           'deadline': self.now() + 30}
            self.status('opening', target_s=self.active['target'])
            still_current = self.current()
            if still_current is None or still_current[1] != current[1]:
                self.fail('cancelled')
                return False
            for key in DECODER_SETTINGS:
                if original[key] and not self.rpc('Settings.SetSettingValue', {'setting': key, 'value': False}):
                    raise RuntimeError('Software mode refused')
            playlist, position = properties.get('playlistid', -1), properties.get('position', -1)
            item = ({'playlistid': playlist, 'position': position} if playlist >= 0 and position >= 0
                    else {'file': current[0]})
            self.active['reopen_item'] = item  # RAM only; never in the recovery journal.
            self.active['original_hardware'] = any(original.values())
            # Reopening a playing playlist item can retain the old codec in
            # Kodi 21. Stop the decoder first; the service suspends tracking
            # throughout this transaction, preserving the viewing session.
            if self.rpc('Player.Stop', {'playerid': 1}) != 'OK':
                raise RuntimeError('Playback stop refused')
            # Explicit seeking after the decoder starts is required. Kodi may
            # ignore options.resume when reopening an existing playlist item.
            if self.rpc('Player.Open', {'item': item}) != 'OK':
                raise RuntimeError('Playback restart refused')
            self.status('opening', target_s=self.active['target'])
            return True
        except (OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
            self.fail('failed', error)
            return False

    def fail(self, phase, error=None):
        state = self.active
        target = state.get('target') if state else None
        self.active = None
        restored = self.recover() if os.path.exists(self.journal) else True
        # A failed switch must not leave the same video playing from zero.
        # User cancellation/change/Stop is deliberately left untouched.
        if phase == 'failed' and state and restored:
            try:
                current = self.current()
                if current and current[1] == state['identity']:
                    self.rpc('Player.Seek', {'playerid': 1, 'value': {'time': kodi_time(target)}})
                    self.rpc('Player.PlayPause', {'playerid': 1, 'play': state['play']})
            except (RuntimeError, TypeError, KeyError):
                pass
        self.status(phase, target_s=target, settings_restored=restored,
                    error=type(error).__name__ if error else '',
                    stage=state.get('phase') if state else '')

    def cancel(self):
        if self.active:
            # Open/Stop may already have reached Kodi. Roll back the decoder,
            # then restore the original position and streams before returning.
            self.active['cancel_requested'] = True
            self.status('cancelling', target_s=self.active['target'])

    def tick(self, tracker=None):
        if not self.active:
            if self.recovery_pending and self.now() >= self.next_recovery:
                self.recover()
            return False
        state = self.active
        try:
            if self.now() >= state['deadline']:
                raise RuntimeError('Playback restart timed out')
            current = self.current()
            if current is None:
                if state.get('seen_playback') or self.now() - state['started'] > 5:
                    self.fail('cancelled')
                return True
            state['seen_playback'] = True
            if current[1] != state['identity']:
                # A deliberate change of video must never be sought or paused.
                self.fail('cancelled')
                return True
            if state.get('cancel_requested') and not state.get('rollback'):
                self.restore()
                if self.rpc('Player.Stop', {'playerid': 1}) != 'OK':
                    raise RuntimeError('Rollback stop refused')
                if self.rpc('Player.Open', {'item': state['reopen_item']}) != 'OK':
                    raise RuntimeError('Rollback restart refused')
                state.update(rollback=True, phase='opening', seen_playback=False,
                             started=self.now(), deadline=self.now() + 30)
                self.status('cancelling', target_s=state['target'])
                return True
            labels = self.rpc('XBMC.GetInfoLabels', {'labels': ['Player.Process(videodecoder)']}) or {}
            hardware = self.rpc('XBMC.GetInfoBooleans', {'booleans': ['Player.Process(videohwdecoder)']}) or {}
            decoder = labels.get('Player.Process(videodecoder)', '')
            expected_hardware = state['original_hardware'] if state.get('rollback') else False
            if hardware.get('Player.Process(videohwdecoder)') is not expected_hardware or not decoder:
                return True
            properties = self.rpc('Player.GetProperties', {'playerid': 1, 'properties': [
                'time', 'totaltime', 'audiostreams', 'subtitles', 'currentaudiostream',
                'currentsubtitle', 'subtitleenabled', 'speed']}) or {}
            if seconds(properties.get('totaltime') or {}) <= 0:
                return True
            if state['phase'] == 'opening':
                self.rpc('Player.PlayPause', {'playerid': 1, 'play': False})
                audio = state['audio']
                if audio is not None:
                    if audio not in [row.get('index') for row in properties.get('audiostreams', [])]:
                        raise RuntimeError('Original audio stream unavailable')
                    if (properties.get('currentaudiostream') or {}).get('index') != audio:
                        self.rpc('Player.SetAudioStream', {'playerid': 1, 'stream': audio})
                subtitle = state['subtitle']
                if subtitle is not None and subtitle >= 0:
                    if subtitle not in [row.get('index') for row in properties.get('subtitles', [])]:
                        raise RuntimeError('Original subtitle stream unavailable')
                    self.rpc('Player.SetSubtitle', {'playerid': 1, 'subtitle': subtitle,
                                                   'enable': state['subtitle_enabled']})
                    # Kodi's enable=False means "do not force on", rather
                    # than "turn off". Off needs a separate explicit action.
                    if not state['subtitle_enabled']:
                        self.rpc('Player.SetSubtitle', {'playerid': 1, 'subtitle': 'off'})
                state['phase'], state['streams_ready'] = 'streams', self.now() + .5
                self.status('restoring_position', target_s=state['target'])
                return True
            if state['phase'] == 'streams':
                if self.now() < state['streams_ready']:
                    return True
                target = min(state['target'], max(0, seconds(properties['totaltime']) - 1))
                self.rpc('Player.Seek', {'playerid': 1, 'value': {'time': kodi_time(target)}})
                state['target'], state['phase'] = target, 'checking'
                state['check_after'] = self.now() + .8
                return True
            observed = seconds(properties.get('time') or {})
            if self.now() < state['check_after']:
                return True
            previous = state.get('last_position')
            state['last_position'] = observed
            if previous is None or abs(observed - previous) > .05:
                return True
            if abs(observed - state['target']) > 1:
                return True
            if (state['audio'] is not None
                    and (properties.get('currentaudiostream') or {}).get('index') != state['audio']):
                raise RuntimeError('Audio selection not preserved')
            if state['subtitle'] is not None and state['subtitle'] >= 0:
                if ((properties.get('currentsubtitle') or {}).get('index') != state['subtitle']
                        or properties.get('subtitleenabled') != state['subtitle_enabled']):
                    raise RuntimeError('Subtitle selection not preserved')
            self.restore()
            self.rpc('Player.PlayPause', {'playerid': 1, 'play': state['play']})
            if tracker is not None:
                # The restart belongs to the same viewing session: no commit,
                # return to the catalogue, or application of an old resume point.
                tracker.resume_due = None
                tracker.restore_pending = None
                tracker.preferences_applied = True
                tracker.position = observed
                tracker.stable_since = None
            self.active = None
            self.status('cancelled' if state.get('cancel_requested') else 'ready',
                        target_s=state['target'], observed_s=observed,
                        decoder=decoder, play=state['play'], audio=state['audio'],
                        subtitle=state['subtitle'], subtitle_enabled=state['subtitle_enabled'],
                        settings_restored=True, elapsed_s=round(self.now() - state['started'], 3))
        except (OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
            try:
                current = self.current()
                cancelled = current is None or current[1] != state['identity']
            except (RuntimeError, TypeError, KeyError):
                cancelled = False
            self.fail('cancelled' if cancelled else 'failed', None if cancelled else error)
        return True

    def close(self):
        self.active = None
        if os.path.exists(self.journal):
            self.recover()
