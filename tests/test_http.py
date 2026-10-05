"""Real local HTTP sockets; synthetic upstream, no provider traffic."""
import contextlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import inspect
import pathlib
import threading
import tempfile
import time
import unittest
try:
    from .test_ios_contract import KEY, identifier, registered_device, notification
except ImportError:
    from test_ios_contract import KEY, identifier, registered_device, notification

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bundle', ROOT / 'bundle.py')
bundle = importlib.util.module_from_spec(spec); spec.loader.exec_module(bundle)

class ProviderBoundary(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self):
        self.send_response(self.server.health_status); self.end_headers()
    def do_POST(self):
        self.server.received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
        time.sleep(getattr(self.server, 'delay', 0))
        if self.server.push_status == 200 and not getattr(self.server, 'reject', False):
            self.server.delivered = getattr(self.server, 'delivered', 0) + 1
        try:
            self.send_response(self.server.push_status); self.end_headers()
            rejected = [self.server.received[-1]['notification']['devices'][0]['pushkey']] if getattr(self.server, 'reject', False) else []
            self.wfile.write(json.dumps({'rejected': rejected}).encode())
        except (BrokenPipeError, ConnectionResetError):
            pass

@contextlib.contextmanager
def running(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield server
    finally: server.shutdown(); server.server_close(); thread.join()

class HttpTests(unittest.TestCase):
    def test_real_http_forwarding_is_generic_and_readiness_follows_upstream(self):
        self.assertTrue(hasattr(bundle, 'PushServer'), 'configurable push server required')
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), ProviderBoundary)
        upstream.received = []; upstream.health_status = 200; upstream.push_status = 200
        with running(upstream), running(bundle.PushServer(('127.0.0.1', 0), upstream=upstream.server_address)) as guard:
            client = http.client.HTTPConnection(*guard.server_address, timeout=2)
            body = {'notification': {'event_id': '$test', 'room_id': '!test',
                'devices': [{'app_id': 'pl.gov.psp.civcom.ios.prod', 'pushkey': 'synthetic-token',
                            'data': {'default_payload': {KEY: identifier('@fixture:soia.info'), 'aps': {'alert': 'private preview'}}}}]}}
            client.request('POST', '/_matrix/push/v1/notify', json.dumps(body), {'Content-Type': 'application/json'})
            response = client.getresponse(); self.assertEqual(response.status, 200); self.assertEqual(json.loads(response.read()), {'rejected': []})
            self.assertNotIn('private preview', json.dumps(upstream.received))
            self.assertEqual(upstream.received[0]['notification']['devices'][0]['data']['default_payload']['aps']['alert'], {'title': 'CIVCOM', 'body': 'Nowa wiadomość'})
            upstream.health_status = 503
            client.request('GET', '/health'); response = client.getresponse(); self.assertEqual(response.status, 503); response.read()
            upstream.push_status = 500
            body['notification']['event_id'] = '$new-upstream-failure'
            client.request('POST', '/_matrix/push/v1/notify', json.dumps(body)); response = client.getresponse(); self.assertEqual(response.status, 502); response.read()
            client.close()

    def test_invalid_http_never_reaches_upstream(self):
        self.assertTrue(hasattr(bundle, 'PushServer'), 'configurable push server required')
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), ProviderBoundary)
        upstream.received = []; upstream.health_status = 200; upstream.push_status = 200
        with running(upstream), running(bundle.PushServer(('127.0.0.1', 0), upstream=upstream.server_address)) as guard:
            client = http.client.HTTPConnection(*guard.server_address, timeout=2)
            for path, body in [('/_matrix/push/v1/notify', '{"notification":{"content":"secret"}}'),
                               ('/_matrix/push/v1/notify', '{invalid JSON'), ('/unrelated', '{}')]:
                client.request('POST', path, body)
                response = client.getresponse(); self.assertIn(response.status, (400,404)); response.read()
            self.assertEqual(upstream.received, [])
            client.close()

    def test_standard_and_synapse_count_only_ack_without_provider_alert(self):
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), ProviderBoundary)
        upstream.received = []; upstream.health_status = 200; upstream.push_status = 200
        with running(upstream), running(bundle.PushServer(('127.0.0.1', 0), upstream=upstream.server_address)) as guard:
            client = http.client.HTTPConnection(*guard.server_address, timeout=3)
            base = {'counts': {'unread': 0}, 'devices': [{'app_id': 'pl.gov.psp.civcom.ios.prod', 'pushkey': 'test-token'}]}
            for fields in ({}, {'id': '', 'type': '', 'sender': ''}, {'id': '', 'type': None, 'sender': ''}):
                with self.subTest(fields=fields):
                    client.request('POST', '/_matrix/push/v1/notify', json.dumps({'notification': dict(base, **fields)}))
                    response = client.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.loads(response.read()), {'rejected': []})
            for fields in ({'sender': '@secret:soia.info'}, {'sender': None}, {'id': None}, {'type': 'm.room.message'}, {'content': {'body': 'secret'}}, {'counts': {'unread': 'bad'}}):
                client.request('POST', '/_matrix/push/v1/notify', json.dumps({'notification': dict(base, **fields)}))
                response = client.getresponse(); self.assertEqual(response.status, 400); response.read()
            self.assertEqual(upstream.received, [])
            client.close()

    def test_provider_success_after_old_fifteen_second_timeout_is_not_retried(self):
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), ProviderBoundary)
        upstream.received = []; upstream.health_status = 200; upstream.push_status = 200; upstream.delay = 16
        with running(upstream), running(bundle.PushServer(('127.0.0.1', 0), upstream=upstream.server_address)) as guard:
            body = {'notification': {'event_id': '$delayed', 'room_id': '!test',
                     'devices': [{'app_id': 'pl.gov.psp.civcom.ios.prod', 'pushkey': 'retry-token', 'data': {'default_payload': {KEY: identifier('@fixture:soia.info')}}}]}}
            client = http.client.HTTPConnection(*guard.server_address, timeout=20)
            client.request('POST', '/_matrix/push/v1/notify', json.dumps(body))
            response = client.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read()), {'rejected': []})
            # Same event retry must reuse the known result, not alert again.
            client.request('POST', '/_matrix/push/v1/notify', json.dumps(body))
            response = client.getresponse(); self.assertEqual(response.status, 200); response.read()
            self.assertEqual(len(upstream.received), 1)
            client.close()

    def test_pending_retry_reuses_inflight_dispatch_and_restart_keeps_result(self):
        self.assertIn('journal', inspect.signature(bundle.PushServer).parameters, 'durable duplicate suppression required')
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), ProviderBoundary)
        upstream.received = []; upstream.health_status = 200; upstream.push_status = 200; upstream.delay = 0.2
        body = {'notification': {'event_id': '$pending', 'room_id': '!retry',
                 'devices': [{'app_id': 'pl.gov.psp.civcom.ios.prod', 'pushkey': 'durable-token', 'data': {'default_payload': {KEY: identifier('@fixture:soia.info')}}}]}}
        def post(server):
            client = http.client.HTTPConnection(*server.server_address, timeout=3)
            client.request('POST', '/_matrix/push/v1/notify', json.dumps(body))
            response = client.getresponse(); status = response.status; response.read(); client.close(); return status
        with tempfile.TemporaryDirectory() as directory, running(upstream):
            journal = pathlib.Path(directory, 'delivery.sqlite3')
            with running(bundle.PushServer(('127.0.0.1', 0), upstream=upstream.server_address, journal=journal,
                         response_budget=0.03, upstream_timeout=1)) as guard:
                self.assertEqual(post(guard), 503)
                self.assertEqual(post(guard), 503)
                time.sleep(0.25)
                self.assertEqual(post(guard), 200)
                self.assertEqual(len(upstream.received), 1)
            with running(bundle.PushServer(('127.0.0.1', 0), upstream=upstream.server_address, journal=journal)) as restarted:
                self.assertEqual(post(restarted), 200)
                self.assertEqual(len(upstream.received), 1)
            data = journal.read_bytes()
            self.assertNotIn(b'durable-token', data)
            self.assertNotIn(b'$pending', data)
            self.assertEqual(journal.stat().st_mode & 0o077, 0)

    def test_uncertain_timeout_does_not_replay_after_late_provider_delivery(self):
        self.assertIn('journal', inspect.signature(bundle.PushServer).parameters, 'durable duplicate suppression required')
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), ProviderBoundary)
        upstream.received = []; upstream.health_status = 200; upstream.push_status = 200; upstream.delay = 0.15
        body = {'notification': {'event_id': '$uncertain', 'room_id': '!test',
                 'devices': [{'app_id': 'pl.gov.psp.civcom', 'pushkey': 'late-token'}]}}
        with running(upstream), running(bundle.PushServer(('127.0.0.1', 0), upstream=upstream.server_address,
                     response_budget=0.1, upstream_timeout=0.03)) as guard:
            for attempt in range(2):
                client = http.client.HTTPConnection(*guard.server_address, timeout=3)
                client.request('POST', '/_matrix/push/v1/notify', json.dumps(body))
                response = client.getresponse(); self.assertEqual(response.status, 502); response.read(); client.close()
                time.sleep(0.2)
            self.assertEqual(len(upstream.received), 1)
            self.assertEqual(upstream.delivered, 1)

    def test_restart_uncertain_is_visible_and_operator_reconciliation_can_resume(self):
        self.assertTrue(hasattr(bundle, 'DeliveryJournal'), 'durable journal required')
        self.assertTrue(hasattr(bundle.DeliveryJournal, 'reconcile'), 'uncertain operator path required')
        body = {'notification': {'event_id': '$restart', 'room_id': '!test',
                 'devices': [{'app_id': 'pl.gov.psp.civcom', 'pushkey': 'restart-token'}]}}
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), ProviderBoundary)
        upstream.received = []; upstream.health_status = 200; upstream.push_status = 200
        with tempfile.TemporaryDirectory() as directory, running(upstream):
            path = pathlib.Path(directory, 'delivery.sqlite3')
            abandoned = bundle.DeliveryJournal(path)
            key = bundle.PushServer.key(body['notification'], body['notification']['devices'][0])
            abandoned.claim([key]); abandoned.connection.close() # process lost before recording result
            with running(bundle.PushServer(('127.0.0.1', 0), upstream=upstream.server_address, journal=path)) as guard:
                client = http.client.HTTPConnection(*guard.server_address, timeout=3)
                client.request('POST', '/_matrix/push/v1/notify', json.dumps(body))
                response = client.getresponse(); self.assertEqual(response.status, 502); response.read()
                self.assertEqual(upstream.received, [])
                self.assertEqual(guard.journal.stats()['states']['uncertain'], 1)
                with self.assertRaises(ValueError): guard.journal.reconcile(key, 'retry', 'a' * 64, upstream_stopped=False)
                guard.journal.reconcile(key, 'retry', 'a' * 64, upstream_stopped=True)
                client.request('POST', '/_matrix/push/v1/notify', json.dumps(body))
                response = client.getresponse(); self.assertEqual(response.status, 200); response.read()
                self.assertEqual(len(upstream.received), 1)
                client.close()

    def test_uncertain_key_does_not_block_unrelated_event_or_health(self):
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), ProviderBoundary)
        upstream.received = []; upstream.health_status = 200; upstream.push_status = 200; upstream.delay = 0.15
        body = {'notification': {'event_id': '$ambiguous', 'room_id': '!test',
                 'devices': [{'app_id': 'pl.gov.psp.civcom', 'pushkey': 'individual-token'}]}}
        with running(upstream), running(bundle.PushServer(('127.0.0.1', 0), upstream=upstream.server_address,
                     response_budget=0.1, upstream_timeout=0.03)) as guard:
            client = http.client.HTTPConnection(*guard.server_address, timeout=3)
            client.request('POST', '/_matrix/push/v1/notify', json.dumps(body))
            response = client.getresponse(); self.assertEqual(response.status, 502); response.read()
            guard.journal.connection.execute("UPDATE dispatch SET created_at=0 WHERE status='uncertain'"); guard.journal.connection.commit()
            upstream.delay = 0; body['notification']['event_id'] = '$different-message'
            client.request('POST', '/_matrix/push/v1/notify', json.dumps(body))
            response = client.getresponse(); self.assertEqual(response.status, 200); response.read()
            client.request('GET', '/health'); response = client.getresponse(); self.assertEqual(response.status, 200); response.read()
            client.request('GET', '/status'); response = client.getresponse(); self.assertTrue(json.loads(response.read())['degraded'])
            self.assertEqual(len(upstream.received), 2)
            client.close()

    def test_cached_invalid_token_returns_exact_rejected_list_without_resending(self):
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), ProviderBoundary)
        upstream.received = []; upstream.health_status = 200; upstream.push_status = 200; upstream.reject = True
        body = {'notification': {'event_id': '$rejected', 'room_id': '!test',
                 'devices': [{'app_id': 'pl.gov.psp.civcom.ios.prod', 'pushkey': 'expired-fixture-token', 'data': {'default_payload': {KEY: identifier('@fixture:soia.info')}}}]}}
        with running(upstream), running(bundle.PushServer(('127.0.0.1', 0), upstream=upstream.server_address)) as guard:
            client = http.client.HTTPConnection(*guard.server_address, timeout=3)
            for attempt in range(2):
                client.request('POST', '/_matrix/push/v1/notify', json.dumps(body))
                response = client.getresponse(); self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read()), {'rejected': ['expired-fixture-token']})
            self.assertEqual(len(upstream.received), 1)
            self.assertEqual(getattr(upstream, 'delivered', 0), 0)
            client.close()

    def test_mixed_bad_ios_routing_rejects_whole_request_before_any_dispatch(self):
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), ProviderBoundary)
        upstream.received = []; upstream.health_status = 200; upstream.push_status = 200
        devices = [registered_device('@one:soia.info'), registered_device('@android:soia.info', 'pl.gov.psp.civcom'),
                   registered_device('@two:soia.info', 'pl.gov.psp.civcom.dev.ios.dev')]
        del devices[-1]['data']['default_payload'][KEY]
        with running(upstream), running(bundle.PushServer(('127.0.0.1', 0), upstream=upstream.server_address)) as guard:
            client = http.client.HTTPConnection(*guard.server_address, timeout=3)
            client.request('POST', '/_matrix/push/v1/notify', json.dumps(notification(devices)))
            response = client.getresponse(); self.assertEqual(response.status, 400); response.read()
            self.assertEqual(upstream.received, [])
            self.assertEqual(guard.journal.stats()['states'], {})
            client.close()
