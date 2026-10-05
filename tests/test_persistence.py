"""Real SQLite aborts and local I/O exercise write-failure cleanup/recovery."""
import http.client
import importlib.util
import json
import pathlib
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
try:
    from .test_http import ProviderBoundary, running
except ImportError:
    from test_http import ProviderBoundary, running

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('persistence_bundle', ROOT / 'bundle.py')
bundle = importlib.util.module_from_spec(spec); spec.loader.exec_module(bundle)

BODY = {'notification': {'event_id': '$write-fault', 'room_id': '!private',
        'devices': [{'app_id': 'pl.gov.psp.civcom', 'pushkey': 'synthetic-fault-token'}]}}

def abort_terminal_writes(journal):
    # A real SQLite transaction fails; simple reads/pruning remain available.
    journal.connection.execute("CREATE TRIGGER fail_terminal BEFORE UPDATE OF status ON dispatch WHEN NEW.status IN ('complete','rejected','uncertain') BEGIN SELECT RAISE(ABORT, 'injected terminal persistence failure'); END")
    journal.connection.commit()

def permits(server):
    acquired = 0
    while server.capacity.acquire(blocking=False): acquired += 1
    for _ in range(acquired): server.capacity.release()
    return acquired

def post(server, body):
    client = http.client.HTTPConnection(*server.server_address, timeout=2)
    client.request('POST', '/_matrix/push/v1/notify', json.dumps(body))
    response = client.getresponse(); status = response.status; response.read(); client.close()
    return status

class PersistenceTests(unittest.TestCase):
    def test_terminal_write_fault_releases_capacity_latches_health_and_restart_prevents_replay(self):
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), ProviderBoundary)
        upstream.received = []; upstream.health_status = 200; upstream.push_status = 200
        with tempfile.TemporaryDirectory() as directory, running(upstream):
            path = pathlib.Path(directory, 'delivery.sqlite3')
            with running(bundle.PushServer(('127.0.0.1', 0), upstream=upstream.server_address,
                         journal=path, response_budget=0.05)) as guard:
                abort_terminal_writes(guard.journal)
                self.assertEqual(post(guard, BODY), 503)
                with self.subTest(check='all worker permits restored'): self.assertEqual(permits(guard), 32)
                with self.subTest(check='unhealthy'): self.assertFalse(guard.journal.ready())
                with self.subTest(check='degraded status'): self.assertTrue(guard.journal.stats()['degraded'])
                self.assertEqual(len(upstream.received), 1)
                client = http.client.HTTPConnection(*guard.server_address, timeout=2)
                client.request('GET', '/health'); response = client.getresponse(); self.assertEqual(response.status, 503); response.read()
                client.request('GET', '/status'); response = client.getresponse(); status = json.loads(response.read())
                self.assertTrue(status['degraded']); self.assertTrue(status['persistence_failed']); client.close()
                # Removing transient fault restores SQLite reads/writes, but
                # must not silently clear unknown delivery results in memory.
                guard.journal.connection.execute('DROP TRIGGER fail_terminal'); guard.journal.connection.commit()
                with self.subTest(check='latch after disk write recovery'): self.assertFalse(guard.journal.ready())
                self.assertEqual(post(guard, BODY), 503)
                self.assertEqual(len(upstream.received), 1)
            guard.journal.connection.close()
            with running(bundle.PushServer(('127.0.0.1', 0), upstream=upstream.server_address, journal=path)) as recovered:
                self.assertTrue(recovered.journal.ready())
                self.assertEqual(post(recovered, BODY), 502)
                self.assertEqual(len(upstream.received), 1)
                other = json.loads(json.dumps(BODY)); other['notification']['event_id'] = '$after-safe-recovery'
                self.assertEqual(post(recovered, other), 200)
                self.assertEqual(len(upstream.received), 2)
            recovered.journal.connection.close()

    def test_watchdog_write_fault_still_interrupts_blocked_transport_and_frees_capacity(self):
        left, right = socket.socketpair()
        entered = threading.Event()
        class BlockingTransport:
            # Real blocking socket has no timeout; watchdog cleanup must end I/O.
            sock = left
            def request(self, *_): entered.set()
            def getresponse(self):
                left.recv(1)
                raise OSError('transport ended without a provider result')
            def close(self): left.close()
        guard = bundle.PushServer(('127.0.0.1', 0), upstream_timeout=0.05)
        key = guard.key(BODY['notification'], BODY['notification']['devices'][0])
        guard.journal.claim([key]); abort_terminal_writes(guard.journal)
        guard.capacity.acquire()
        try:
            with patch.object(bundle.http.client, 'HTTPConnection', return_value=BlockingTransport()):
                worker = threading.Thread(target=guard.send_once, args=(key, BODY), daemon=True)
                worker.start(); self.assertTrue(entered.wait(1)); worker.join(0.3)
                with self.subTest(check='watchdog interrupted actual blocking socket'): self.assertFalse(worker.is_alive())
                with self.subTest(check='latched health'): self.assertFalse(guard.journal.ready())
                if worker.is_alive():
                    left.shutdown(socket.SHUT_RDWR); left.close(); worker.join(1)
                with self.subTest(check='all permits released'): self.assertEqual(permits(guard), 32)
        finally:
            left.close(); right.close(); guard.server_close(); guard.journal.connection.close()
