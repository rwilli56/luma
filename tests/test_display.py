import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin.video.luma'))
from resources.lib.display import REFRESH, SYNC_CLOCK, configure


class DisplayTests(unittest.TestCase):
    def rpc(self, values, reject=False):
        self.calls = []
        def call(raw):
            batch = json.loads(raw)
            self.calls.extend(batch)
            responses = []
            for request in batch:
                params = request['params']
                if request['method'] == 'Settings.GetSettingValue':
                    result = {'value': values[params['setting']]}
                else:
                    if not reject:
                        values[params['setting']] = params['value']
                    result = not reject
                responses.append({'id': request['id'], 'result': result})
            return json.dumps(responses)
        return call

    def test_enables_native_refresh_and_disables_speed_adjustment(self):
        values = {REFRESH: 0, SYNC_CLOCK: True}
        ready, text = configure(rpc=self.rpc(values))
        self.assertTrue(ready)
        self.assertEqual(values, {REFRESH: 2, SYNC_CLOCK: False})
        self.assertIn('On start/stop', text)

    def test_no_writes_when_already_configured(self):
        configure(rpc=self.rpc({REFRESH: 2, SYNC_CLOCK: False}))
        self.assertEqual(len(self.calls), 2)

    def test_opt_out_only_reads_user_settings(self):
        ready, _ = configure(False, rpc=self.rpc({REFRESH: 0, SYNC_CLOCK: True}))
        self.assertFalse(ready)
        self.assertTrue(all(r['method'] == 'Settings.GetSettingValue' for r in self.calls))

    def test_rejected_setting_is_reported(self):
        ready, text = configure(rpc=self.rpc({REFRESH: 0, SYNC_CLOCK: False}, reject=True))
        self.assertFalse(ready)
        self.assertIn('incomplete', text)

    def test_unsupported_rpc_fails_gracefully(self):
        ready, text = configure(rpc=lambda _: '{"error": {"code": -32601}}')
        self.assertFalse(ready)
        self.assertIn('Unable to read', text)
