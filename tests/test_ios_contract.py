"""Registered Swift payload shape -> guard -> pinned Sygnal APNs construction.

Swift runtime/NSE restoration/tap are separate native acceptance. This test
executes the actual pinned Sygnal method and checks entry metadata against the
source-derived Swift credential-selection contract, not an APNs provider.
"""
import ast
import base64
import copy
import hashlib
import importlib.util
import json
import pathlib
from types import SimpleNamespace
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
KEY = 'pusher_notification_client_identifier'
spec = importlib.util.spec_from_file_location('ios_contract_bundle', ROOT / 'bundle.py')
bundle = importlib.util.module_from_spec(spec); spec.loader.exec_module(bundle)


def identifier(user_id):
    # ClientProxy.swift404-410: SHA256(userID UTF8), "%02x" joined.
    return hashlib.sha256(user_id.encode('utf-8')).hexdigest()


def registered_device(user_id='@fixture:soia.info', app='pl.gov.psp.civcom.ios.prod'):
    # NotificationManager -> APNSPayload/APSInfo/APSAlert Codable shape.
    return {'app_id': app, 'pushkey': base64.b64encode(bytes(range(1, 33))).decode('ascii'), 'data': {
        'format': 'event_id_only', 'default_payload': {
            'aps': {'mutable-content': 1, 'alert': {'title': 'CIVCOM', 'body': 'Nowa wiadomość', 'loc-args': []}},
            KEY: identifier(user_id)}}}


def notification(devices):
    return {'notification': {'event_id': '$synthetic-ios-contract', 'room_id': '!synthetic-ios-contract', 'devices': devices}}


def pinned_sygnal_payload(notification, device):
    # Execute the real v0.17.0 method without importing network dependencies.
    # Source/annotations remain tied to the byte-identical vendored official test source.
    path = ROOT / 'tests' / 'vendor' / 'sygnal-apns-v0.17.0.py'
    tree = ast.parse(path.read_text())
    method = copy.deepcopy(next(node for node in ast.walk(tree)
                               if isinstance(node, ast.FunctionDef) and node.name == '_get_payload_event_id_only'))
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), method], type_ignores=[])
    namespace = {}
    exec(compile(ast.fix_missing_locations(module), str(path), 'exec'), namespace)
    n = SimpleNamespace(event_id=notification['event_id'], room_id=notification['room_id'])
    return namespace['_get_payload_event_id_only'](None, n, device['data']['default_payload'], False)


class IOSContractTests(unittest.TestCase):
    def test_registered_payload_survives_sygnal_and_is_eligible_for_nse_credentials(self):
        user = '@fixture:soia.info'
        device = registered_device(user)
        payload = device['data']['default_payload']
        payload.update(receiver_id='untrusted-receiver', body='private body', sender='private sender',
                       room_name='private room', media_url='https://private.invalid/media')
        payload['aps'].update(category='message', thread_id='private room')
        safe = bundle.sanitize(notification([device]))['notification']
        apns = pinned_sygnal_payload(safe, safe['devices'][0])
        # These are the actual NSE gate values: roomID,eventID,clientID + exact
        # restoration-token match. receiverID is produced by the native builder
        # from the restored session, never accepted from the provider payload.
        self.assertEqual(apns.get(KEY), identifier(user))
        credentials = {identifier(user): {'user_id': user}}
        selected = credentials.get(apns.get(KEY))
        self.assertIsNotNone(selected, 'NSE must be able to select restoration credentials')
        self.assertEqual(selected['user_id'], user)
        self.assertEqual(apns['room_id'], '!synthetic-ios-contract')
        self.assertEqual(apns['event_id'], '$synthetic-ios-contract')
        self.assertEqual(set(apns), {'aps', KEY, 'room_id', 'event_id'})
        self.assertEqual(apns['aps']['alert'], {'title': 'CIVCOM', 'body': 'Nowa wiadomość'})
        self.assertEqual(apns['aps']['mutable-content'], 1)
        for preview in ('private body', 'private sender', 'private room', 'private.invalid', 'untrusted-receiver'):
            self.assertNotIn(preview, json.dumps(apns))

    def test_event_apns_rejects_missing_bad_and_nonstring_routing_before_dispatch(self):
        for bad in (None, '', 'not-a-hash', 'A'*64, 'a'*63, 'a'*65, 'g'*64, 123, [], {}):
            device = registered_device()
            device['data']['default_payload'][KEY] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError): bundle.sanitize(notification([device]))
        for data in (None, 'encoded-json-is-not-an-object', {}, {'default_payload': None}, {'default_payload': {'aps': {'alert': 'generic'}}}):
            device = registered_device(); device['data'] = data
            with self.subTest(data=data), self.assertRaises(ValueError): bundle.sanitize(notification([device]))

    def test_mixed_devices_keep_each_ios_identity_and_drop_all_android_metadata(self):
        devices = [registered_device('@one:soia.info'), registered_device('@two:soia.info', 'pl.gov.psp.civcom.dev.ios.dev'),
                   registered_device('@android:soia.info', 'pl.gov.psp.civcom')]
        safe = bundle.sanitize(notification(devices))['notification']
        self.assertEqual(safe['devices'][0]['data']['default_payload'].get(KEY), identifier('@one:soia.info'))
        self.assertEqual(safe['devices'][1]['data']['default_payload'].get(KEY), identifier('@two:soia.info'))
        self.assertEqual(safe['devices'][2]['data'], {})
        invalid = copy.deepcopy(devices); invalid[1]['data']['default_payload'][KEY] = {'body': 'private'}
        with self.assertRaises(ValueError): bundle.sanitize(notification(invalid))

    def test_count_only_does_not_require_or_forward_client_identity(self):
        request = {'notification': {'id': '', 'type': None, 'sender': '', 'counts': {'unread': 0},
                    'devices': [{'app_id': 'pl.gov.psp.civcom.ios.prod', 'pushkey': 'synthetic-token'}]}}
        self.assertIsNone(bundle.sanitize(request))
