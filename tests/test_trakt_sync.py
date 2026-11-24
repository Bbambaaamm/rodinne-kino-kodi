import ast
import json
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import Mock


SOURCE = Path(__file__).resolve().parents[1] / 'addons/plugin.video.webshare.available/trakt_sync.py'
MISSING_PROFILE = str(SOURCE.parent / '.test-missing-profile')


class TraktSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = types.ModuleType('tested_trakt_sync')
        exec(compile(ast.parse(SOURCE.read_text(encoding='utf8')), str(SOURCE), 'exec'),
             cls.module.__dict__)

    def test_snapshot_ignores_unrelated_rating_activity(self):
        value = {'movies': {'watched_at': 'a', 'rated_at': 'ignored'},
                 'episodes': {'paused_at': 'b'}}
        self.assertEqual(self.module.activity_snapshot(value)['movies']['watched_at'], 'a')
        self.assertNotIn('rated_at', self.module.activity_snapshot(value)['movies'])

    def test_changed_episode_is_detected(self):
        old = self.module.activity_snapshot({'episodes': {'watched_at': 'a'}})
        new = self.module.activity_snapshot({'episodes': {'watched_at': 'b'}})
        self.assertEqual(self.module.snapshot_changes(old, new), {'episodes'})

    def test_unchanged_activity_does_not_refresh(self):
        snapshot = self.module.activity_snapshot({'episodes': {'watched_at': 'a'}})
        self.assertEqual(self.module.snapshot_changes(snapshot, snapshot), set())

    def test_invalidation_refreshes_visible_rows_and_history_without_focus_action(self):
        home = Mock()
        stamp = self.module.invalidate_lists(home, MISSING_PROFILE, stamp='123',
                                              reason='test', changed={'episodes'})
        self.assertEqual(stamp, '123')
        home.setProperty.assert_any_call('Family.Paging.Revision', '123')
        home.setProperty.assert_any_call('Family.Paging.Count.personal_both_history', '20')
        home.setProperty.assert_any_call(
            'Family.Paging.Display.Wanted.list_episode_next', '20')
        self.assertFalse(any('Focus' in str(call) for call in home.method_calls))

    def family(self, profile, activities, saved=None):
        home = Mock()
        props = {}
        home.getProperty.side_effect = lambda key: props.get(key, '')
        home.setProperty.side_effect = lambda key, value: props.__setitem__(key, value)
        home.clearProperty.side_effect = lambda key: props.pop(key, None)
        activity_response = {'movies': {}, 'episodes': {}, **activities}
        core = types.SimpleNamespace(
            read_json=Mock(return_value=saved or {}),
            write_json=Mock(),
            trakt_request=Mock(return_value=activity_response),
        )
        return types.SimpleNamespace(
            PROFILE=profile, HOME=home, core=core,
            auth=Mock(return_value=('client', 'token')),
        ), props

    def test_first_cloud_check_repairs_stale_lists(self):
        family, props = self.family(MISSING_PROFILE, {'episodes': {'watched_at': 'new'}})
        sync = self.module.TraktActivitySync(family)
        sync.download()
        sync.pending = True
        sync.tick(True)
        self.assertIn('Family.Paging.Revision', props)
        self.assertEqual(json.loads(props[self.module.STATUS])['state'], 'ready')

    def test_cloud_change_repairs_existing_lists(self):
        old_activity = self.module.activity_snapshot({'episodes': {'watched_at': 'old'}})
        saved = {'owner': __import__('hashlib').sha256(b'token').hexdigest(),
                 'activities': old_activity}
        family, props = self.family(MISSING_PROFILE, {'episodes': {'watched_at': 'new'}}, saved)
        sync = self.module.TraktActivitySync(family)
        sync.download()
        sync.pending = True
        sync.tick(True)
        self.assertIn('Family.Paging.Revision', props)
        self.assertEqual(json.loads(props[self.module.STATUS])['changed'], ['episodes'])

    def test_network_failure_keeps_existing_revision(self):
        family, props = self.family(MISSING_PROFILE, {})
        family.core.trakt_request.side_effect = RuntimeError('offline')
        sync = self.module.TraktActivitySync(family)
        sync.download()
        sync.pending = True
        sync.tick(True)
        self.assertNotIn('Family.Paging.Revision', props)
        self.assertEqual(json.loads(props[self.module.STATUS])['state'], 'retry')

    def test_tick_starts_network_work_in_background(self):
        family, _ = self.family(MISSING_PROFILE, {})
        sync = self.module.TraktActivitySync(family)
        sync.next_sync = 0
        entered = threading.Event()
        release = threading.Event()
        def slow():
            entered.set()
            release.wait(1)
        sync.download = slow
        started = time.monotonic()
        sync.tick(True)
        elapsed = time.monotonic() - started
        self.assertTrue(entered.wait(1))
        self.assertLess(elapsed, .1)
        release.set()

    def test_local_completion_rechecks_until_delayed_trakt_write_arrives(self):
        family, props = self.family(MISSING_PROFILE, {})
        sync = self.module.TraktActivitySync(family)
        props[self.module.URGENT] = 'local-finish'
        sync.next_sync = time.monotonic() + 100
        sync.tick(False)
        self.assertGreater(sync.urgent_until, time.monotonic())
        self.assertLessEqual(sync.next_sync - time.monotonic(), 3.1)
        sync.pending = True
        sync.results.put(('ready', {'owner': 'x', 'activities': {}, 'updated': 1},
                          set(), False))
        sync.tick(False)
        self.assertLessEqual(sync.next_sync - time.monotonic(), 5.1)

    def test_kodi_playback_signal_queues_refresh_without_manual_action(self):
        family, props = self.family(MISSING_PROFILE, {})
        sync = self.module.TraktActivitySync(family)
        props['Family.LastPlayback'] = '{"completed": true}'
        sync.tick(False)
        revision = props['Family.Paging.Revision']
        self.assertEqual(props[self.module.URGENT], revision)
        self.assertEqual(props['Family.Paging.Display.Wanted.list_episode_next'], '20')
        sync.tick(False)
        self.assertEqual(props['Family.Paging.Revision'], revision)


if __name__ == '__main__':
    unittest.main()
