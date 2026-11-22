"""A decoder switch is a recoverable playback transaction, not a global profile."""
import ast
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'addons/plugin.video.webshare.available/playback_compat.py'
spec = importlib.util.spec_from_file_location('tested_playback_compat', SOURCE)
compat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compat)


class Kodi:
    def __init__(self):
        self.settings = dict.fromkeys(compat.DECODER_SETTINGS, True)
        self.path = 'https://private.invalid/video.avi?secret=do-not-export'
        self.playing, self.speed, self.position = True, 0, 37.625
        self.decoder, self.hardware = 'amc-h264(S)', True
        self.audio, self.subtitle, self.subtitles_on = 1, 1, True
        self.fail_method, self.fail_setting = None, None
        self.calls = []
        self.open_count = 0
        self.seeking_disabled = False

    def rpc(self, method, params=None):
        self.calls.append((method, params))
        if method == self.fail_method:
            raise RuntimeError('Controlled failure')
        if method == 'Settings.GetSettingValue':
            return {'value': self.settings[params['setting']]}
        if method == 'Settings.SetSettingValue':
            if params['setting'] == self.fail_setting:
                return False
            self.settings[params['setting']] = params['value']
            return True
        if method == 'Player.GetActivePlayers':
            return [{'playerid': 1, 'type': 'video'}] if self.playing else []
        if method == 'Player.GetItem':
            return {'item': {'file': self.path}}
        if method == 'XBMC.GetInfoLabels':
            return {'Player.Process(videodecoder)': self.decoder}
        if method == 'XBMC.GetInfoBooleans':
            return {'Player.Process(videohwdecoder)': self.hardware}
        if method == 'Player.GetProperties':
            data = {'time': compat.kodi_time(self.position), 'totaltime': compat.kodi_time(90),
                    'playlistid': 1, 'position': 0, 'speed': self.speed,
                    'audiostreams': [{'index': 0}, {'index': 1}],
                    'subtitles': [{'index': 0}, {'index': 1}],
                    'currentaudiostream': {'index': self.audio},
                    'currentsubtitle': {'index': self.subtitle}, 'subtitleenabled': self.subtitles_on}
            return {key: data[key] for key in params['properties']}
        if method == 'Player.Open':
            self.open_count += 1
            self.playing = True
            self.position, self.speed = 0, 1
            self.audio, self.subtitle, self.subtitles_on = 0, 0, True
            self.hardware = any(self.settings.values())
            self.decoder = 'amc-h264(S)' if self.hardware else 'ff-h264'
            return 'OK'
        if method == 'Player.Stop':
            self.playing = False
            return 'OK'
        if method == 'Player.PlayPause':
            self.speed = int(params['play'])
            return {'speed': self.speed}
        if method == 'Player.SetAudioStream':
            self.audio = params['stream']
            return 'OK'
        if method == 'Player.SetSubtitle':
            if params['subtitle'] == 'off':
                self.subtitles_on = False
            else:
                self.subtitle = params['subtitle']
                if params.get('enable'):
                    self.subtitles_on = True
            return 'OK'
        if method == 'Player.Seek':
            if not self.seeking_disabled:
                self.position = compat.seconds(params['value']['time'])
            return {'time': compat.kodi_time(self.position)}
        raise AssertionError(method)


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal = Path(self.temp.name) / 'decoder-recovery.json'
        self.kodi, self.events, self.clock = Kodi(), [], 100.
        self.player = self.make_player()
        self.tracker = types.SimpleNamespace(resume_due=42, restore_pending='old-return',
            preferences_applied=False, position=0, stable_since=1, context={'kept': True})

    def make_player(self):
        return compat.CompatibilityPlayer(self.kodi.rpc, str(self.journal), self.events.append, lambda: self.clock)

    def finish(self):
        for _ in range(12):
            self.clock += .25
            self.player.tick(self.tracker)
            if self.player.active is None:
                break

    def test_every_container_uses_same_transaction_and_preserves_streams_and_position(self):
        for extension in ('avi', 'mkv', 'mp4', 'webm', 'ts'):
            with self.subTest(extension=extension):
                self.setUp()
                self.kodi.path = 'https://private.invalid/arbitrary.' + extension
                self.assertTrue(self.player.start(True))
                self.finish()
                self.assertEqual(self.events[-1]['phase'], 'ready')
                self.assertEqual(self.kodi.position, 37.625)
                self.assertEqual((self.kodi.audio, self.kodi.subtitle, self.kodi.subtitles_on), (1, 1, True))
                self.assertEqual(self.kodi.speed, 1)
                self.assertEqual(self.kodi.settings, dict.fromkeys(compat.DECODER_SETTINGS, True))
                self.assertEqual(self.kodi.decoder, 'ff-h264')
                self.assertFalse(self.journal.exists())
                self.assertIsNone(self.tracker.resume_due)
                self.assertIsNone(self.tracker.restore_pending)
                self.assertEqual(self.tracker.context, {'kept': True})

    def test_previously_paused_playback_stays_paused(self):
        self.player.start(False)
        self.finish()
        self.assertEqual((self.events[-1]['phase'], self.kodi.speed), ('ready', 0))

    def test_disabled_subtitles_remain_disabled(self):
        self.kodi.subtitles_on = False
        self.player.start(True)
        self.finish()
        self.assertFalse(self.kodi.subtitles_on)

    def test_mixed_original_decoder_settings_are_restored_exactly(self):
        original = dict(zip(compat.DECODER_SETTINGS, (False, True)))
        self.kodi.settings = original.copy()
        self.player.start()
        self.finish()
        self.assertEqual(self.kodi.settings, original)

    def test_next_video_returns_to_hardware(self):
        self.player.start()
        self.finish()
        self.kodi.rpc('Player.Open', {'item': {'file': 'another.mp4'}})
        self.assertTrue(self.kodi.hardware)

    def test_old_decoder_is_stopped_before_reopen(self):
        self.player.start()
        names = [name for name, _ in self.kodi.calls]
        self.assertLess(names.index('Player.Stop'), names.index('Player.Open'))

    def test_journal_exists_before_first_decoder_mutation_and_contains_no_media_address(self):
        rpc = self.player.rpc
        def check(method, params=None):
            if method == 'Settings.SetSettingValue' and params['value'] is False:
                self.assertTrue(self.journal.exists())
                saved = self.journal.read_text()
                self.assertNotIn('private', saved)
                self.assertNotIn('secret', saved)
                self.assertEqual(set(json.loads(saved)), {'version', 'settings'})
            return rpc(method, params)
        self.player.rpc = check
        self.player.start()
        self.finish()
        self.assertNotIn('private', json.dumps(self.events))

    def test_failed_open_restores_both_switches(self):
        self.kodi.fail_method = 'Player.Open'
        self.assertFalse(self.player.start())
        self.assertEqual(self.events[-1]['phase'], 'failed')
        self.assertTrue(all(self.kodi.settings.values()))
        self.assertFalse(self.journal.exists())

    def test_partial_setting_failure_restores_first_switch(self):
        self.kodi.fail_setting = compat.DECODER_SETTINGS[1]
        self.assertFalse(self.player.start())
        self.assertTrue(all(self.kodi.settings.values()))
        self.assertEqual(self.kodi.open_count, 0)

    def test_seek_failure_restores_settings(self):
        self.player.start()
        self.kodi.fail_method = 'Player.Seek'
        self.finish()
        self.assertEqual(self.events[-1]['phase'], 'failed')
        self.assertTrue(all(self.kodi.settings.values()))

    def test_ignored_seek_times_out_and_restores_settings(self):
        self.player.start()
        self.kodi.seeking_disabled = True
        self.finish()
        self.clock += 31
        self.player.tick()
        self.assertEqual(self.events[-1]['phase'], 'failed')
        self.assertTrue(all(self.kodi.settings.values()))

    def test_user_changes_video_without_new_video_being_sought(self):
        self.player.start()
        self.kodi.path = 'another-movie.mkv'
        before = len(self.kodi.calls)
        self.player.tick()
        self.assertEqual(self.events[-1]['phase'], 'cancelled')
        self.assertFalse(any(name in ('Player.Seek', 'Player.PlayPause') for name, _ in self.kodi.calls[before:]))
        self.assertTrue(all(self.kodi.settings.values()))

    def test_user_stops_and_settings_are_restored(self):
        self.player.start()
        self.kodi.playing = False
        self.clock += 6
        self.player.tick()
        self.assertEqual(self.events[-1]['phase'], 'cancelled')
        self.assertTrue(all(self.kodi.settings.values()))

    def test_stop_while_progress_dialog_opens_does_not_restart_video(self):
        publish = self.player.publish
        def stopped(value):
            publish(value)
            if value['phase'] == 'opening':
                self.kodi.playing = False
        self.player.publish = stopped
        self.assertFalse(self.player.start())
        self.assertEqual(self.events[-1]['phase'], 'cancelled')
        self.assertEqual(self.kodi.open_count, 0)
        self.assertTrue(all(self.kodi.settings.values()))

    def test_stop_between_player_snapshot_requests_is_cancellation(self):
        self.player.start()
        rpc = self.player.rpc
        def stopped(method, params=None):
            if method == 'Player.GetProperties':
                self.kodi.playing = False
                raise RuntimeError('Player disappeared')
            return rpc(method, params)
        self.player.rpc = stopped
        self.player.tick()
        self.assertEqual(self.events[-1]['phase'], 'cancelled')
        self.assertTrue(all(self.kodi.settings.values()))

    def test_explicit_cancel_restores_settings(self):
        self.player.start()
        self.player.cancel()
        self.assertEqual(self.events[-1]['phase'], 'cancelling')
        self.finish()
        self.assertEqual(self.events[-1]['phase'], 'cancelled')
        self.assertTrue(all(self.kodi.settings.values()))
        self.assertEqual(self.kodi.position, 37.625)
        self.assertEqual((self.kodi.audio, self.kodi.subtitle), (1, 1))
        self.assertTrue(self.kodi.hardware)

    def test_cancel_during_opening_gap_still_restores_original_position(self):
        self.player.start(False)
        self.kodi.playing = False
        self.player.cancel()
        self.clock += .5
        self.player.tick()
        self.assertIsNotNone(self.player.active)
        self.kodi.playing = True
        self.finish()
        self.assertEqual(self.events[-1]['phase'], 'cancelled')
        self.assertEqual((self.kodi.position, self.kodi.speed), (37.625, 0))
        self.assertTrue(self.kodi.hardware)

    def test_duplicate_request_does_not_overwrite_original_snapshot(self):
        self.player.start()
        original = self.journal.read_bytes()
        self.assertFalse(self.player.start())
        self.assertEqual(self.journal.read_bytes(), original)
        self.assertEqual(self.kodi.open_count, 1)

    def test_service_restart_restores_orphaned_journal(self):
        self.player.start()
        self.assertFalse(any(self.kodi.settings.values()))
        restarted = self.make_player()
        self.assertFalse(restarted.recovery_pending)
        self.assertTrue(all(self.kodi.settings.values()))
        self.assertFalse(self.journal.exists())

    def test_shutdown_restores_original_settings(self):
        self.player.start()
        self.player.close()
        self.assertTrue(all(self.kodi.settings.values()))

    def test_failed_restoration_keeps_journal_and_retries(self):
        self.player.start()
        self.kodi.fail_setting = compat.DECODER_SETTINGS[0]
        self.player.close()
        self.assertTrue(self.journal.exists())
        self.assertTrue(self.kodi.settings[compat.DECODER_SETTINGS[1]])
        self.assertTrue(self.player.recovery_pending)
        self.assertFalse(self.player.start())
        self.kodi.fail_setting = None
        self.clock += 2
        self.player.tick()
        self.assertFalse(self.journal.exists())
        self.assertTrue(all(self.kodi.settings.values()))

    def test_corrupt_journal_cannot_change_unrelated_setting(self):
        self.journal.write_text(json.dumps({'version': 1, 'settings': {'audiooutput.passthrough': False}}))
        restored = self.make_player()
        self.assertTrue(restored.recovery_pending)
        self.assertFalse(any(name == 'Settings.SetSettingValue' for name, _ in self.kodi.calls))

    def test_already_software_needs_no_restart_or_journal(self):
        self.kodi.hardware, self.kodi.decoder = False, 'ff-h264'
        self.assertFalse(self.player.start(False))
        self.assertEqual(self.events[-1]['phase'], 'already_compatible')
        self.assertEqual(self.kodi.open_count, 0)
        self.assertFalse(self.journal.exists())

    def test_no_video_changes_no_settings(self):
        self.kodi.playing = False
        self.assertFalse(self.player.start())
        self.assertEqual(self.events[-1]['phase'], 'no_video')
        self.assertTrue(all(self.kodi.settings.values()))


class CompatibilityMenuTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import Mock
        self.values = {'Family.Service.Heartbeat': '100'}
        self.home = types.SimpleNamespace(getProperty=lambda key: self.values.get(key, ''),
            setProperty=lambda key, value: self.values.__setitem__(key, value))
        self.dialog = Mock()
        self.dialog.yesno.return_value = False
        self.rpc = Mock(return_value={'currentvideostream': {'width': 3840, 'height': 2160}})
        self.namespace = {'HOME': self.home, 'time': types.SimpleNamespace(time=lambda: 101),
            'json': json, 'rpc': self.rpc, 'xbmcgui': types.SimpleNamespace(Dialog=lambda: self.dialog, DLG_YESNO_NO_BTN=10)}
        source = SOURCE.parent.parent / 'script.michal.family.repair/maintenance.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'request_compatibility')
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), self.namespace)

    def test_cancelling_high_resolution_warning_does_not_queue_or_change_settings(self):
        self.assertFalse(self.namespace['request_compatibility']())
        self.assertNotIn('Family.Compat.Request', self.values)
        self.assertEqual([call.args[0] for call in self.rpc.call_args_list], ['Player.GetProperties'])

    def test_unavailable_service_does_not_queue_request(self):
        self.values.clear()
        self.assertFalse(self.namespace['request_compatibility']())
        self.assertNotIn('Family.Compat.Request', self.values)
        self.rpc.assert_not_called()

    def test_regular_video_queues_original_paused_state_without_settings_changes(self):
        self.rpc.return_value = {'currentvideostream': {'width': 1920, 'height': 1080}}
        self.assertTrue(self.namespace['request_compatibility'](False))
        self.assertFalse(json.loads(self.values['Family.Compat.Request'])['play'])
        self.dialog.yesno.assert_not_called()
        self.assertEqual([call.args[0] for call in self.rpc.call_args_list], ['Player.GetProperties'])


if __name__ == '__main__':
    unittest.main()
