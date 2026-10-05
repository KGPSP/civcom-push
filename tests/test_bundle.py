"""Tests enforce protocol/privacy boundaries and fail-closed deployment inputs."""
import copy
import importlib.util
import json
import pathlib
import subprocess
import sys
try:
    from .test_ios_contract import KEY, identifier
except ImportError:
    from test_ios_contract import KEY, identifier
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class BundleBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = None
        if (ROOT / 'bundle.py').exists():
            spec = importlib.util.spec_from_file_location('bundle', ROOT / 'bundle.py')
            cls.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.module)

    def code(self):
        self.assertIsNotNone(self.module, 'Fail-closed bundle implementation is missing')
        return self.module

    def request(self):
        return {'notification': {'event_id': '$event:soia.info', 'room_id': '!room:soia.info',
                'devices': [{'app_id': 'pl.gov.psp.civcom.ios.prod', 'pushkey': 'token',
                'data': {'default_payload': {KEY: identifier('@fixture:soia.info'), 'aps': {'alert': 'secret preview'}}}}]}}

class BundleTests(BundleBase):
    def test_generic_apns_payload_overrides_untrusted_preview(self):
        safe = self.code().sanitize(self.request())
        payload = safe['notification']['devices'][0]['data']['default_payload']
        self.assertEqual(payload['aps']['alert'], {'title': 'CIVCOM', 'body': 'Nowa wiadomość'})
        self.assertNotIn('secret preview', json.dumps(safe))

    def test_fcm_retains_token_and_event_but_removes_default_payload(self):
        request = self.request()
        request['notification']['devices'][0]['app_id'] = 'pl.gov.psp.civcom.debug'
        result = self.code().sanitize(request)['notification']
        self.assertEqual(result['devices'][0]['pushkey'], 'token')
        self.assertEqual(result['devices'][0]['data'], {})
        self.assertEqual(result['event_id'], '$event:soia.info')

    def test_rejects_message_content_even_if_event_id_present(self):
        for key in ('sender', 'content', 'room_name', 'type', 'sender_display_name'):
            request = self.request(); request['notification'][key] = 'confidential'
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.code().sanitize(request)

    def test_rejects_unknown_pusher_and_missing_event(self):
        request = self.request(); request['notification']['devices'][0]['app_id'] = 'im.vector.app'
        with self.assertRaises(ValueError): self.code().sanitize(request)
        request = self.request(); del request['notification']['event_id']
        with self.assertRaises(ValueError): self.code().sanitize(request)

    def test_rejects_empty_devices_noninteger_counts_and_bad_priority(self):
        for mutation in ({'devices': []}, {'counts': {'unread': 'x'}}, {'prio': 'urgent'}):
            request = self.request(); request['notification'].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): self.code().sanitize(request)

    def test_never_mutates_caller_request(self):
        request = self.request(); original = copy.deepcopy(request)
        self.code().sanitize(request)
        self.assertEqual(request, original)

    def test_incomplete_template_cannot_generate_deployable_config(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(ROOT / 'bundle.py'), 'prepare',
                '--private-dir', directory, '--output', directory + '/out'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(pathlib.Path(directory, 'out', 'sygnal.yaml').exists())
            self.assertNotIn('Traceback', result.stderr)

    def test_identity_manifest_matches_pusher_apns_topics(self):
        apps = self.code().APPS
        self.assertEqual(apps['pl.gov.psp.civcom.ios.prod']['topic'], 'pl.gov.psp.civcom')
        self.assertEqual(apps['pl.gov.psp.civcom.dev.ios.dev']['topic'], 'pl.gov.psp.civcom.dev')
        self.assertEqual(apps['pl.gov.psp.civcom.dev.ios.dev']['platform'], 'sandbox')

    def test_associations_fail_without_signing_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(ROOT / 'bundle.py'), 'associations',
                '--identity', str(ROOT / 'associations' / 'signing.example.json'), '--output', directory],
                capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(pathlib.Path(directory, 'assetlinks.json').exists())
            self.assertFalse(pathlib.Path(directory, 'apple-app-site-association').exists())

    def test_incomplete_identity_removes_stale_association_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory)
            (output / 'assetlinks.json').write_text('stale')
            (output / 'apple-app-site-association').write_text('stale')
            with self.assertRaises(ValueError):
                self.code().associations(ROOT / 'associations' / 'signing.example.json', output)
            self.assertFalse((output / 'assetlinks.json').exists())
            self.assertFalse((output / 'apple-app-site-association').exists())

    def test_journal_capacity_blocks_before_new_dispatch_and_uncertainty_is_degraded(self):
        self.assertTrue(hasattr(self.code(), 'DeliveryJournal'), 'durable journal required')
        journal = self.code().DeliveryJournal()
        journal.max_records = 1
        journal.claim(['a' * 64])
        import sqlite3
        with self.assertRaises(sqlite3.Error): journal.claim(['b' * 64])
        self.assertEqual(journal.connection.execute('SELECT COUNT(*) FROM dispatch').fetchone()[0], 1)
        self.assertFalse(journal.ready())
        journal.connection.execute("UPDATE dispatch SET status='uncertain', created_at=0")
        journal.connection.commit()
        journal.max_records = 10
        self.assertTrue(journal.ready())
        self.assertTrue(journal.stats()['degraded'])

class CredentialsTests(BundleBase):
    def fixture(self, directory):
        from cryptography.hazmat.primitives.asymmetric import ec, rsa
        from cryptography.hazmat.primitives import serialization
        root = pathlib.Path(directory)
        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        ec_key = ec.generate_private_key(ec.SECP256R1())
        def pem(key):
            return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption()).decode()
        for name in ('fcm-prod.json', 'fcm-dev.json'):
            (root / name).write_text(json.dumps({'type': 'service_account', 'project_id': 'test-firebase',
                'token_uri': 'https://oauth2.googleapis.com/token', 'client_email': 'push@test-firebase.iam.gserviceaccount.com',
                'private_key_id': 'test-key', 'private_key': pem(rsa_key)}))
        (root / 'apns-prod.p8').write_text(pem(ec_key))
        (root / 'apns-dev.p8').write_text(pem(ec_key))
        (root / 'deploy.json').write_text(json.dumps({'apns_team_id': 'L643PDVV68', 'notify_cidrs': ['192.0.2.1/32'], 'apns': {
            'production': {'key_id': 'TESTKEY001', 'keyfile': 'apns-prod.p8', 'topics': ['pl.gov.psp.civcom']},
            'sandbox': {'key_id': 'TESTKEY002', 'keyfile': 'apns-dev.p8', 'topics': ['pl.gov.psp.civcom.dev']}}}))
        for name, packages in [('google-services-prod.json', ['pl.gov.psp.civcom']),
                               ('google-services-dev.json', ['pl.gov.psp.civcom.debug', 'pl.gov.psp.civcom.nightly'])]:
            (root / name).write_text(json.dumps({'project_info': {'project_id': 'test-firebase'},
                'client': [{'client_info': {'android_client_info': {'package_name': package}}} for package in packages]}))
        for path in root.iterdir(): path.chmod(0o600)
        return root

    def test_valid_crypto_fixture_generates_five_exact_pushers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            self.code().prepare(root, root / 'out', '192.0.2.1/32')
            config = json.loads((root / 'out' / 'sygnal.yaml').read_text())
            self.assertEqual(set(config['apps']), set(self.code().APPS))
            self.assertTrue(all(app.get('api_version') == 'v1' for app in config['apps'].values() if app['type'] == 'gcm'))
            self.assertNotIn('PRIVATE KEY', (root / 'out' / 'sygnal.yaml').read_text())

    def test_firebase_project_mismatch_blocks_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            data = json.loads((root / 'google-services-prod.json').read_text())
            data['project_info']['project_id'] = 'wrong-project'
            (root / 'google-services-prod.json').write_text(json.dumps(data))
            with self.assertRaises(ValueError): self.code().prepare(root, root / 'out', '192.0.2.1/32')
            self.assertFalse((root / 'out' / 'sygnal.yaml').exists())

    def test_bad_key_and_cidrs_cannot_reuse_previous_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            self.code().prepare(root, root / 'out', '192.0.2.1/32')
            with self.assertRaises(ValueError): self.code().prepare(root, root / 'out', '0.0.0.0/0')
            self.assertFalse((root / 'out' / 'sygnal.yaml').exists())
            (root / 'apns-prod.p8').write_text('not-a-valid-key')
            with self.assertRaises(ValueError): self.code().prepare(root, root / 'out', '192.0.2.1/32')
            self.assertFalse((root / 'out' / 'sygnal.yaml').exists())

    def test_environment_scoped_apns_keys_map_to_their_own_topics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            deployment = {'apns_team_id': 'L643PDVV68', 'notify_cidrs': ['192.0.2.1/32'], 'apns': {
                'production': {'key_id': 'TESTKEY001', 'keyfile': 'apns-prod.p8', 'topics': ['pl.gov.psp.civcom']},
                'sandbox': {'key_id': 'TESTKEY002', 'keyfile': 'apns-dev.p8', 'topics': ['pl.gov.psp.civcom.dev']}}}
            (root / 'deploy.json').write_text(json.dumps(deployment))
            try: self.code().prepare(root, root / 'out', '192.0.2.1/32')
            except ValueError: self.fail('Environment-scoped APNs key configuration rejected')
            apps = json.loads((root / 'out' / 'sygnal.yaml').read_text())['apps']
            self.assertEqual(apps['pl.gov.psp.civcom.ios.prod']['keyfile'], '/run/private/apns-prod.p8')
            self.assertEqual(apps['pl.gov.psp.civcom.dev.ios.dev']['keyfile'], '/run/private/apns-dev.p8')
            self.assertEqual(apps['pl.gov.psp.civcom.dev.ios.dev']['key_id'], 'TESTKEY002')

    def test_world_readable_credentials_and_symlinks_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            (root / 'fcm-prod.json').chmod(0o644)
            with self.assertRaises(ValueError): self.code().prepare(root, root / 'out', '192.0.2.1/32')
            (root / 'fcm-prod.json').unlink()
            (root / 'fcm-prod.json').symlink_to(root / 'fcm-dev.json')
            with self.assertRaises(ValueError): self.code().prepare(root, root / 'out', '192.0.2.1/32')

if __name__ == '__main__': unittest.main()
