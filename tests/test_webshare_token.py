"""An expired Webshare session can renew using the configured YAWSP account."""
import ast
import hashlib
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock
from xml.etree import ElementTree as ET


CORE = Path(__file__).resolve().parents[1] / 'addons/plugin.video.webshare.available/core.py'


class WebshareTokenTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parents[1] / '_testtmp')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'md5crypt.py').write_text(
            "def md5crypt(password, salt):\n    return password + b':' + salt\n")
        self.settings = {'wsuser': 'example', 'wspass': 'fixture-password', 'token': 'expired'}
        addon = types.SimpleNamespace(
            getSetting=lambda key: self.settings.get(key, ''),
            setSetting=lambda key, value: self.settings.__setitem__(key, value),
            getAddonInfo=lambda key: str(self.root))
        source = ast.parse(CORE.read_text(encoding='utf-8'))
        refresh = next(node for node in source.body
                       if isinstance(node, ast.FunctionDef) and node.name == 'refresh_webshare_token')
        self.post = Mock(side_effect=self.respond)
        scope = {'xbmcaddon': types.SimpleNamespace(Addon=lambda _: addon),
                 'YAWSP_ID': 'plugin.video.yawsp', 'WEBSHARE_API': 'https://webshare.cz/api',
                 'xml_post': self.post, 'os': os, 'hashlib': hashlib,
                 'RuntimeError': RuntimeError}
        exec(compile(ast.Module(body=[refresh], type_ignores=[]), str(CORE), 'exec'), scope)
        self.refresh = scope['refresh_webshare_token']

    def respond(self, endpoint, fields, timeout):
        if endpoint.endswith('/salt/'):
            return ET.fromstring('<response><status>OK</status><salt>fixture-salt</salt></response>')
        self.assertTrue(endpoint.endswith('/login/'))
        digest_part = hashlib.sha1(b'fixture-password:fixture-salt').hexdigest()
        self.assertEqual(fields['password'], digest_part)
        self.assertEqual(fields['digest'], hashlib.md5(
            ('example:Webshare:' + digest_part).encode('utf-8')).hexdigest())
        return ET.fromstring('<response><status>OK</status><token>renewed</token></response>')

    def test_renew_stores_token_in_yawsp(self):
        self.assertEqual(self.refresh(), 'renewed')
        self.assertEqual(self.settings['token'], 'renewed')
        self.assertEqual(self.post.call_count, 2)

    def test_missing_password_does_not_attempt_login(self):
        self.settings['wspass'] = ''
        with self.assertRaises(RuntimeError):
            self.refresh()
        self.post.assert_not_called()
        self.assertEqual(self.settings['token'], 'expired')


if __name__ == '__main__':
    unittest.main()
