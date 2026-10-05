#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""CIVCOM config preparation and preview-free Matrix push ingress.

No credential or request contents are written to logs. Crypto validation uses
cryptography already provided by the pinned Sygnal image; local tests need only
stdlib unless testing private key loading.
"""
import argparse
import copy
import http.client
import hashlib
import socket
import sqlite3
import threading
import time
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APPS = {
    'pl.gov.psp.civcom': {'type': 'gcm', 'credential': 'fcm-prod.json'},
    'pl.gov.psp.civcom.debug': {'type': 'gcm', 'credential': 'fcm-dev.json'},
    'pl.gov.psp.civcom.nightly': {'type': 'gcm', 'credential': 'fcm-dev.json'},
    'pl.gov.psp.civcom.ios.prod': {'type': 'apns', 'topic': 'pl.gov.psp.civcom', 'platform': 'production'},
    'pl.gov.psp.civcom.dev.ios.dev': {'type': 'apns', 'topic': 'pl.gov.psp.civcom.dev', 'platform': 'sandbox'},
}
ALERT = 'CIVCOM — Nowa wiadomość'
IOS_CLIENT_ID = 'pusher_notification_client_identifier'
MAX_BODY = 64 * 1024
APPLE_TEAM_ID = 'L643PDVV68'
RESPONSE_BUDGET = 25
UPSTREAM_BUDGET = 900
TERMINAL_RETENTION = 48 * 60 * 60
MAX_RECORDS = 100000
MAX_DATABASE_PAGES = 8192 # 32MiB database, plus bounded SQLite rollback journal


def require(condition, label):
    if not condition:
        raise ValueError(label)


def string(value, label, max_length=1024):
    require(isinstance(value, str) and 0 < len(value) <= max_length, label)
    return value


def sanitize(body):
    require(isinstance(body, dict) and set(body) == {'notification'}, 'invalid envelope')
    notification = body['notification']
    require(isinstance(notification, dict), 'invalid notification')
    count_only = notification.get('event_id', '') == ''
    allowed = {'event_id', 'room_id', 'counts', 'devices', 'prio'}
    if count_only:
        allowed |= {'id', 'type', 'sender'}
        require('counts' in notification and notification.get('room_id', '') == '', 'invalid count-only notification')
        require(all(notification.get(key, '') == '' for key in ('id', 'sender')), 'nonempty legacy field forbidden')
        require(notification.get('type', '') in ('', None), 'nonempty legacy type forbidden')
    else:
        string(notification.get('event_id'), 'event_id required')
        string(notification.get('room_id'), 'room_id required')
    require(set(notification) <= allowed, 'preview fields forbidden')
    require(notification.get('prio', 'high') in ('high', 'low'), 'invalid priority')
    counts = notification.get('counts', {})
    require(isinstance(counts, dict) and set(counts) <= {'unread', 'missed_calls'}, 'invalid counts')
    require(all(type(v) is int and 0 <= v <= 2**31 - 1 for v in counts.values()), 'invalid count')
    devices = notification.get('devices')
    require(isinstance(devices, list) and 1 <= len(devices) <= 100, 'invalid devices')
    result = copy.deepcopy(body)
    for device in result['notification']['devices']:
        require(isinstance(device, dict), 'invalid device')
        require(set(device) <= {'app_id', 'pushkey', 'pushkey_ts', 'data', 'tweaks'}, 'invalid device fields')
        app = device.get('app_id')
        require(isinstance(app, str) and app in APPS, 'unknown app')
        string(device.get('pushkey'), 'invalid token', 4096)
        if 'pushkey_ts' in device:
            require(type(device['pushkey_ts']) is int and device['pushkey_ts'] >= 0, 'invalid timestamp')
        # Caller payload/tweaks may contain content or custom provider options.
        # Only the canonical generic payload reaches Apple, no caller data Google.
        device.pop('tweaks', None)
        if APPS[app]['type'] == 'apns' and not count_only:
            data = device.get('data')
            require(isinstance(data, dict), 'APNs routing data required')
            payload = data.get('default_payload')
            require(isinstance(payload, dict), 'APNs default payload required')
            client_id = payload.get(IOS_CLIENT_ID)
            # ClientProxy SHA256(userID UTF8) -> lower-case %02x, not a UUID.
            require(isinstance(client_id, str) and re.fullmatch(r'[0-9a-f]{64}', client_id), 'valid iOS routing client identity required')
            device['data'] = {'default_payload': {IOS_CLIENT_ID: client_id,
                'aps': {'alert': {'title': 'CIVCOM', 'body': 'Nowa wiadomość'}, 'sound': 'default', 'mutable-content': 1}}}
        else:
            device['data'] = {}
    return None if count_only else result


def private_file(root, name):
    path = root / name
    require(path.is_file() and not path.is_symlink(), 'private file missing or symlink')
    require(path.stat().st_mode & 0o077 == 0, 'private file permissions must be 0600 or 0400')
    require(path.stat().st_size <= 64 * 1024, 'private file oversized')
    return path


def read_json(path):
    with path.open(encoding='utf-8') as stream:
        return json.load(stream)


def load_deployment(root, expected_cidrs):
    data = read_json(private_file(root, 'deploy.json'))
    require(set(data) == {'apns_team_id', 'apns', 'notify_cidrs'}, 'invalid deployment fields')
    require(isinstance(data['apns_team_id'], str) and re.fullmatch(r'[A-Z0-9]{10}', data['apns_team_id']), 'APNs identity required')
    require(data['apns_team_id'] == APPLE_TEAM_ID, 'APNs TeamID must match KG PSP signing identity')
    apns = data['apns']
    require(isinstance(apns, dict) and set(apns) == {'production', 'sandbox'}, 'APNs environments required')
    for environment, topic in [('production', 'pl.gov.psp.civcom'), ('sandbox', 'pl.gov.psp.civcom.dev')]:
        credential = apns[environment]
        require(isinstance(credential, dict) and set(credential) == {'key_id', 'keyfile', 'topics'}, 'invalid APNs key capability descriptor')
        require(isinstance(credential['key_id'], str) and re.fullmatch(r'[A-Z0-9]{10}', credential['key_id']), 'APNs KeyID required')
        require(isinstance(credential['keyfile'], str) and re.fullmatch(r'[A-Za-z0-9_-]+\.p8', credential['keyfile']), 'APNs key filename required')
        require(credential['topics'] == [topic], 'APNs topic capability must match environment')
    cidrs = data['notify_cidrs']
    require(isinstance(cidrs, list) and bool(cidrs), 'source CIDRs required')
    normalized = []
    for cidr in cidrs:
        require(isinstance(cidr, str), 'invalid source CIDR')
        network = ipaddress.ip_network(cidr, strict=True)
        require(network.prefixlen > 0, 'unrestricted CIDR forbidden')
        normalized.append(str(network))
    require(','.join(normalized) == expected_cidrs, 'proxy CIDRs must match private deployment')
    data['notify_cidrs'] = normalized
    return data


def load_fcm(path):
    data = read_json(path)
    require(data.get('type') == 'service_account', 'FCM service_account required')
    project = data.get('project_id')
    require(isinstance(project, str) and re.fullmatch(r'[a-z][a-z0-9-]{4,28}[a-z0-9]', project), 'FCM project required')
    require(data.get('token_uri') == 'https://oauth2.googleapis.com/token', 'invalid Google token endpoint')
    require(isinstance(data.get('client_email'), str) and data['client_email'].endswith('.iam.gserviceaccount.com'), 'invalid FCM service account')
    string(data.get('private_key_id'), 'FCM private key ID required')
    string(data.get('private_key'), 'FCM private key required', 16384)
    return data


def check_firebase(path, project, packages):
    data = read_json(path)
    require(data.get('project_info', {}).get('project_id') == project, 'Firebase project mismatch')
    clients = data.get('client')
    require(isinstance(clients, list), 'Firebase clients required')
    found = {client.get('client_info', {}).get('android_client_info', {}).get('package_name')
             for client in clients if isinstance(client, dict)}
    require(set(packages) <= found, 'Firebase Android package mismatch')


def check_keys(fcm_accounts, apns_paths):
    # Credential syntax is insufficient: reject malformed RSA/P-256 keys before
    # any listener starts. This cannot prove IAM permissions/APNs topic ownership.
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.hazmat.primitives.asymmetric import ec, rsa
    for account in fcm_accounts:
        key = load_pem_private_key(account['private_key'].encode(), password=None)
        require(isinstance(key, rsa.RSAPrivateKey) and key.key_size >= 2048, 'FCM RSA key required')
    for apns_path in set(apns_paths):
        key = load_pem_private_key(apns_path.read_bytes(), password=None)
        require(isinstance(key, ec.EllipticCurvePrivateKey) and isinstance(key.curve, ec.SECP256R1), 'APNs P-256 key required')


def prepare(root, output, expected_cidrs, state_dir=None):
    # Clear previous readiness artifact before validation so failure cannot reuse it.
    output.mkdir(parents=True, exist_ok=True)
    for name in ('sygnal.yaml', 'Caddyfile'):
        (output / name).unlink(missing_ok=True)
    if state_dir is not None:
        state_dir.mkdir(parents=True, exist_ok=True)
        require(not state_dir.is_symlink(), 'private state directory required')
        if os.geteuid() == 0: os.chown(state_dir, 0, 0)
        state_dir.chmod(0o700)
        if os.geteuid() == 0: os.chown(state_dir, 65534, 65534)
    deployment = load_deployment(root, expected_cidrs)
    fcm = {name: load_fcm(private_file(root, name)) for name in ('fcm-prod.json', 'fcm-dev.json')}
    check_firebase(private_file(root, 'google-services-prod.json'), fcm['fcm-prod.json']['project_id'], ['pl.gov.psp.civcom'])
    check_firebase(private_file(root, 'google-services-dev.json'), fcm['fcm-dev.json']['project_id'], ['pl.gov.psp.civcom.debug', 'pl.gov.psp.civcom.nightly'])
    check_keys(list(fcm.values()), [private_file(root, credential['keyfile']) for credential in deployment['apns'].values()])
    apps = {}
    for app, identity in APPS.items():
        settings = {'type': identity['type'], 'send_badge_counts': False, 'inflight_request_limit': 64}
        if identity['type'] == 'gcm':
            credential = identity['credential']
            settings.update(api_version='v1', project_id=fcm[credential]['project_id'],
                            service_account_file='/run/private/' + credential)
        else:
            credential = deployment['apns'][identity['platform']]
            settings.update(topic=identity['topic'], platform=identity['platform'],
                            keyfile='/run/private/' + credential['keyfile'], team_id=deployment['apns_team_id'],
                            key_id=credential['key_id'], push_type='alert', convert_device_token_to_hex=True)
        apps[app] = settings
    config = {
        'http': {'bind_addresses': ['0.0.0.0'], 'port': 5000},
        'log': {'setup': {'version': 1, 'disable_existing_loggers': False,
                         'handlers': {'discard': {'class': 'logging.NullHandler'}},
                         'root': {'handlers': ['discard'], 'level': 'CRITICAL'},
                         'loggers': {'sygnal': {'handlers': ['discard'], 'propagate': False},
                                     'sygnal.access': {'handlers': ['discard'], 'propagate': False}}},
                'access': {'x_forwarded_for': False}},
        'metrics': {'prometheus': {'enabled': False}, 'opentracing': {'enabled': False}, 'sentry': {'enabled': False}},
        'apps': apps,
    }
    # JSON is a valid YAML subset; no YAML dependency needed for generation.
    (output / 'sygnal.yaml').write_text(json.dumps(config, indent=2) + '\n')
    caddy = '''{\n    admin off\n}\npush.soia.info {\n    @notify {\n        method POST\n        path /_matrix/push/v1/notify\n        remote_ip CIDRS\n    }\n    handle @notify {\n        request_body {\n            max_size 64KB\n        }\n        reverse_proxy guard:8080 {\n            transport http {\n                response_header_timeout 30s\n            }\n        }\n    }\n    handle {\n        respond 404\n    }\n}\n'''
    (output / 'Caddyfile').write_text(caddy.replace('CIDRS', ' '.join(deployment['notify_cidrs'])))


def associations(identity_path, output):
    for name in ('assetlinks.json', 'apple-app-site-association'):
        (output / name).unlink(missing_ok=True)
    identity = read_json(identity_path)
    team = identity.get('apple_team_id')
    require(isinstance(team, str) and re.fullmatch(r'[A-Z0-9]{10}', team), 'genuine Apple TeamID required')
    require(team == APPLE_TEAM_ID, 'Apple TeamID must match KG PSP signing identity')
    android = identity.get('android_sha256')
    require(isinstance(android, dict) and set(android) == {'pl.gov.psp.civcom', 'pl.gov.psp.civcom.debug', 'pl.gov.psp.civcom.nightly'}, 'Android signing identity required')
    assetlinks = []
    for app, fingerprints in android.items():
        require(isinstance(fingerprints, list) and len(fingerprints) > 0, 'signing fingerprint required')
        require(all(isinstance(f, str) and re.fullmatch(r'(?:[A-F0-9]{2}:){31}[A-F0-9]{2}', f) for f in fingerprints), 'invalid SHA256 fingerprint')
        assetlinks.append({'relation': ['delegate_permission/common.handle_all_urls'],
                           'target': {'namespace': 'android_app', 'package_name': app, 'sha256_cert_fingerprints': fingerprints}})
    ios = ['pl.gov.psp.civcom', 'pl.gov.psp.civcom.dev']
    aasa = {'applinks': {'details': [{'appIDs': [team + '.' + app], 'components': [{'/': '/oauth/ios/' + app}]} for app in ios]},
            'webcredentials': {'apps': [team + '.' + app for app in ios]}}
    # Writes only after ALL identities validate; templates never become public JSON.
    output.mkdir(parents=True, exist_ok=True)
    (output / 'assetlinks.json').write_text(json.dumps(assetlinks, indent=2) + '\n')
    (output / 'apple-app-site-association').write_text(json.dumps(aasa, indent=2) + '\n')


class Guard(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'
    server_version = 'CIVCOM'

    def log_message(self, *_):
        pass

    def reply(self, code, payload=b''):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == '/status':
            try: return self.reply(200, json.dumps(self.server.journal.stats()).encode())
            except sqlite3.Error: return self.reply(503)
        if self.path != '/health':
            return self.reply(404)
        if not self.server.journal.ready(): return self.reply(503)
        try:
            connection = http.client.HTTPConnection(*self.server.upstream, timeout=2)
            connection.request('GET', '/health')
            response = connection.getresponse(); response.read()
            self.reply(200 if response.status == 200 else 503)
        except (OSError, http.client.HTTPException):
            self.reply(503)
        finally:
            if 'connection' in locals(): connection.close()

    def do_POST(self):
        if self.path != '/_matrix/push/v1/notify': return self.reply(404)
        # Fixed length, no chunked uploads or ambiguous duplicate Content-Length.
        lengths = self.headers.get_all('Content-Length', [])
        if len(lengths) != 1 or self.headers.get('Transfer-Encoding'): return self.reply(400)
        try:
            size = int(lengths[0])
            require(0 < size <= MAX_BODY, 'body size')
            self.connection.settimeout(5)
            data = self.rfile.read(size)
            require(len(data) == size, 'incomplete body')
            safe = sanitize(json.loads(data))
        except (ValueError, TypeError, OSError, RecursionError):
            return self.reply(400, b'{"error":"invalid event_id_only notification"}')
        if safe is None:
            return self.reply(200, b'{"rejected":[]}')
        try:
            status, rejected = self.server.dispatch(safe)
            payload = (json.dumps({'rejected': rejected}).encode() if status == 200 else
                       b'{"error":"push dispatch pending or uncertain; retry is suppressed"}')
            self.reply(status, payload)
        except sqlite3.Error:
            self.reply(503, b'{"error":"durable dispatch state unavailable"}')


class DeliveryJournal:
    """Durable per-event/device deduplication, storing hashes and state only.

    A pending entry surviving a process restart is uncertain, not eligible for
    another submission. SQLite FULL commits precede any provider-side request.
    Terminal results expire after the bounded homeserver retry horizon.
    Uncertain keys are never replayed or silently deleted; private status and
    evidence-backed operator reconciliation resolve each one separately.
    """
    def __init__(self, path=None, recover_pending=True):
        if path is not None:
            path = Path(path)
            require(not path.is_symlink(), 'journal must not be a symlink')
            if not path.exists():
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(descriptor)
            require(path.stat().st_mode & 0o077 == 0, 'journal permissions required')
        self.persistence_failed = False
        self.max_records = MAX_RECORDS
        self.retention_seconds = TERMINAL_RETENTION
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.connection = sqlite3.connect(str(path) if path is not None else ':memory:',
                                         check_same_thread=False, timeout=5)
        self.connection.execute('PRAGMA page_size=4096')
        self.connection.execute('PRAGMA max_page_count=' + str(MAX_DATABASE_PAGES))
        require(self.connection.execute('PRAGMA page_count').fetchone()[0] <= MAX_DATABASE_PAGES, 'journal capacity exceeded')
        self.connection.execute('PRAGMA secure_delete=ON')
        self.connection.execute('PRAGMA synchronous=FULL')
        self.connection.execute('PRAGMA journal_mode=DELETE')
        self.connection.execute('CREATE TABLE IF NOT EXISTS dispatch (digest TEXT PRIMARY KEY, status TEXT NOT NULL, created_at INTEGER NOT NULL)')
        self.connection.execute('CREATE INDEX IF NOT EXISTS dispatch_retention ON dispatch(status, created_at)')
        self.connection.execute('CREATE TABLE IF NOT EXISTS reconciliation (digest TEXT, action TEXT, evidence_sha256 TEXT, timestamp INTEGER)')
        # Recovery only at guard startup; CLI inspection must not alter live work.
        if recover_pending:
            self.connection.execute("UPDATE dispatch SET status='uncertain' WHERE status='pending'")
        self.connection.commit()

    def claim(self, keys):
        fresh = []
        with self.changed, self.connection:
            if self.persistence_failed: raise sqlite3.OperationalError('journal requires safe restart')
            self.prune_terminal()
            existing = self.connection.execute('SELECT COUNT(*) FROM dispatch').fetchone()[0]
            for key in dict.fromkeys(keys):
                row = self.connection.execute('SELECT status FROM dispatch WHERE digest=?', (key,)).fetchone()
                if row is None:
                    if existing >= self.max_records: raise sqlite3.DatabaseError('journal resource limit')
                    existing += 1
                    self.connection.execute("INSERT INTO dispatch VALUES (?, 'pending', ?)", (key, int(time.time())))
                    fresh.append(key)
                elif row[0] == 'not_submitted':
                    self.connection.execute("UPDATE dispatch SET status='pending', created_at=? WHERE digest=?", (int(time.time()), key))
                    fresh.append(key)
        return fresh

    def mark_unavailable(self):
        # Durable state cannot record the failure it just failed to write. Latch
        # locally until restart recovers all surviving pending as uncertain.
        with self.changed:
            self.persistence_failed = True
            self.changed.notify_all()

    def finish(self, key, status):
        with self.changed, self.connection:
            self.connection.execute("UPDATE dispatch SET status=? WHERE digest=? AND status='pending'", (status, key))
            self.changed.notify_all()

    def prune_terminal(self):
        # Called while holding the journal lock and a transaction. Unsure work
        # is excluded; unsent overload entries can safely age out.
        cutoff = int(time.time() - self.retention_seconds)
        self.connection.execute("DELETE FROM dispatch WHERE status IN ('complete','rejected','not_submitted') AND created_at < ?", (cutoff,))
        self.connection.execute('DELETE FROM reconciliation WHERE timestamp < ?', (cutoff,))

    def stats(self):
        with self.lock:
            states = dict(self.connection.execute('SELECT status, COUNT(*) FROM dispatch GROUP BY status').fetchall())
            oldest = self.connection.execute("SELECT MIN(created_at) FROM dispatch WHERE status='uncertain'").fetchone()[0]
            return {'states': states, 'degraded': self.persistence_failed or bool(states.get('uncertain')),
                    'persistence_failed': self.persistence_failed,
                    'oldest_uncertain_seconds': max(0, int(time.time() - oldest)) if oldest is not None else 0,
                    'records_limit': self.max_records, 'terminal_retention_seconds': self.retention_seconds}

    def ready(self):
        # Ambiguous network outcomes affect only their own keys. Health becomes
        # globally unavailable only for journal integrity/storage capacity.
        try:
            with self.lock, self.connection:
                if self.persistence_failed: return False
                self.prune_terminal()
                count = self.connection.execute('SELECT COUNT(*) FROM dispatch').fetchone()[0]
            return count < self.max_records
        except sqlite3.Error:
            return False

    def reconcile(self, key, action, evidence_sha256, upstream_stopped=False):
        require(upstream_stopped, 'stop old upstream dispatch before reconciliation')
        require(re.fullmatch(r'[a-f0-9]{64}', key) and re.fullmatch(r'[a-f0-9]{64}', evidence_sha256), 'evidence digest required')
        require(action in ('retry', 'suppress', 'reject'), 'explicit reconciliation action required')
        with self.changed, self.connection:
            row = self.connection.execute('SELECT status FROM dispatch WHERE digest=?', (key,)).fetchone()
            require(row is not None and row[0] == 'uncertain', 'only uncertain keys can be reconciled')
            status = {'retry': 'not_submitted', 'suppress': 'complete', 'reject': 'rejected'}[action]
            self.connection.execute('UPDATE dispatch SET status=?, created_at=? WHERE digest=?', (status, int(time.time()), key))
            self.connection.execute('INSERT INTO reconciliation VALUES (?,?,?,?)', (key, action, evidence_sha256, int(time.time())))
            self.changed.notify_all()

    def states(self, keys):
        with self.lock:
            return {key: self.connection.execute('SELECT status FROM dispatch WHERE digest=?', (key,)).fetchone()[0] for key in keys}


class PushServer(ThreadingHTTPServer):
    def __init__(self, address, upstream=('sygnal', 5000), journal=None,
                 response_budget=RESPONSE_BUDGET, upstream_timeout=UPSTREAM_BUDGET):
        self.upstream = upstream
        self.response_budget = response_budget
        self.upstream_timeout = upstream_timeout
        require(response_budget > 0 and upstream_timeout > 0, 'positive retry budgets required')
        self.journal = DeliveryJournal(journal)
        self.capacity = threading.BoundedSemaphore(32)
        super().__init__(address, Guard)

    def handle_error(self, request, client_address):
        # Disconnect traces from stdlib can contain peer identifiers; discard.
        pass

    @staticmethod
    def key(notification, device):
        identity = [notification['event_id'], notification['room_id'], device['app_id'], device['pushkey']]
        return hashlib.sha256(json.dumps(identity, separators=(',', ':')).encode()).hexdigest()

    def dispatch(self, body):
        notification = body['notification']
        devices = {self.key(notification, device): device for device in notification['devices']}
        fresh = self.journal.claim(devices)
        for key in fresh:
            if self.journal.persistence_failed: break
            if not self.capacity.acquire(blocking=False):
                # No transport was started; a later request can safely claim it.
                self.record_result(key, 'not_submitted')
                continue
            single = copy.deepcopy(body)
            single['notification']['devices'] = [devices[key]]
            threading.Thread(target=self.send_once, args=(key, single), daemon=True).start()
        deadline = time.monotonic() + self.response_budget
        with self.journal.changed:
            while True:
                if self.journal.persistence_failed: return 503, []
                states = self.journal.states(devices)
                if 'uncertain' in states.values():
                    return 502, []
                if 'not_submitted' in states.values():
                    return 503, []
                if 'pending' not in states.values():
                    return 200, list(dict.fromkeys(device['pushkey'] for key, device in devices.items() if states[key] == 'rejected'))
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return 503, []
                self.journal.changed.wait(remaining)

    def record_result(self, key, status):
        try:
            self.journal.finish(key, status)
        except sqlite3.Error:
            # Do not retry an unrecorded provider outcome or hide the fault.
            self.journal.mark_unavailable()

    def send_once(self, key, body):
        # Each device has an independent budget; upstream multi-device dispatch
        # is sequential and cannot multiply our socket wait by device count.
        connection = http.client.HTTPConnection(*self.upstream, timeout=self.upstream_timeout)
        def expire():
            try:
                self.record_result(key, 'uncertain')
            finally:
                try:
                    if connection.sock is not None:
                        try: connection.sock.shutdown(socket.SHUT_RDWR)
                        except OSError: pass
                finally:
                    connection.close()
        timer = threading.Timer(self.upstream_timeout, expire)
        timer.daemon = True
        timer.start()
        status = 'uncertain'
        try:
            if self.journal.states([key])[key] != 'pending':
                return
            connection.request('POST', '/_matrix/push/v1/notify', json.dumps(body).encode(), {'Content-Type': 'application/json'})
            response = connection.getresponse()
            payload = response.read(MAX_BODY + 1)
            require(response.status == 200 and len(payload) <= MAX_BODY, 'uncertain upstream response')
            result = json.loads(payload)
            require(isinstance(result, dict) and set(result) == {'rejected'} and isinstance(result['rejected'], list), 'upstream response')
            token = body['notification']['devices'][0]['pushkey']
            require(all(isinstance(item, str) and item == token for item in result['rejected']), 'unexpected rejected token')
            status = 'rejected' if result['rejected'] else 'complete'
        except (OSError, ValueError, TypeError, http.client.HTTPException):
            pass
        finally:
            timer.cancel()
            try:
                try:
                    connection.close()
                finally:
                    self.record_result(key, status)
            finally:
                self.capacity.release()



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare'); prep.add_argument('--private-dir', type=Path, required=True); prep.add_argument('--output', type=Path, required=True)
    prep.add_argument('--state-dir', type=Path)
    prep.add_argument('--notify-cidrs', default=os.environ.get('NOTIFY_CIDRS', ''))
    assoc = sub.add_parser('associations'); assoc.add_argument('--identity', type=Path, required=True); assoc.add_argument('--output', type=Path, required=True)
    serve = sub.add_parser('serve'); serve.add_argument('--journal', type=Path, required=True)
    status = sub.add_parser('journal-status'); status.add_argument('--journal', type=Path, required=True)
    key = sub.add_parser('journal-key'); key.add_argument('--notification-file', type=Path, required=True)
    reconcile = sub.add_parser('journal-reconcile'); reconcile.add_argument('--journal', type=Path, required=True)
    reconcile.add_argument('--digest', required=True); reconcile.add_argument('--action', choices=['retry', 'suppress', 'reject'], required=True)
    reconcile.add_argument('--evidence-file', type=Path, required=True); reconcile.add_argument('--confirm-upstream-stopped', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'prepare': prepare(args.private_dir, args.output, args.notify_cidrs, args.state_dir)
        elif args.command == 'associations': associations(args.identity, args.output)
        elif args.command == 'journal-status':
            require(args.journal.is_file(), 'actual journal required')
            print(json.dumps(DeliveryJournal(args.journal, recover_pending=False).stats()))
        elif args.command == 'journal-key':
            body = sanitize(read_json(args.notification_file)); require(body is not None, 'event required')
            print(json.dumps([PushServer.key(body['notification'], device) for device in body['notification']['devices']]))
        elif args.command == 'journal-reconcile':
            require(args.journal.is_file(), 'actual journal required')
            require(args.evidence_file.is_file() and args.evidence_file.stat().st_size <= 1024 * 1024, 'bounded private evidence file required')
            journal = DeliveryJournal(args.journal, recover_pending=False)
            journal.reconcile(args.digest, args.action, hashlib.sha256(args.evidence_file.read_bytes()).hexdigest(), args.confirm_upstream_stopped)
        else:
            server = PushServer(('0.0.0.0', 8080), journal=args.journal)
            server.serve_forever()
    except (OSError, ValueError, TypeError, KeyError, ImportError, sqlite3.Error):
        # Never print exception contents: provider errors can embed private data.
        print('BLOCKED: invalid/incomplete private configuration; no credentials logged', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__': sys.exit(main())
