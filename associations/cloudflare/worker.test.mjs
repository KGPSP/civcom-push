import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import worker from './worker.mjs';

const old = JSON.parse(readFileSync(new URL('./origin-baseline.json', import.meta.url)));
const dev = 'L643PDVV68.pl.gov.psp.civcom.dev';
const prod = 'L643PDVV68.pl.gov.psp.civcom';
const paths = ['/apple-app-site-association', '/.well-known/apple-app-site-association'];

test('both public endpoints serve identical additive JSON and retain all existing associations', async () => {
  const responses = paths.map(path => worker.fetch(new Request('https://civcom.soia.info' + path)));
  const bodies = await Promise.all(responses.map(r => r.text()));
  assert.equal(bodies[0], bodies[1]);
  for (const r of responses) {
    assert.equal(r.status, 200);
    assert.equal(r.headers.get('content-type'), 'application/json; charset=utf-8');
    assert.equal(r.headers.has('location'), false);
  }
  const merged = JSON.parse(bodies[0]);
  assert.deepEqual(merged.webcredentials.apps, [...old.webcredentials.apps, dev, prod]);
  assert.deepEqual(merged.applinks.details.slice(0, old.applinks.details.length), old.applinks.details);
  assert.deepEqual(merged.applinks.details.at(-2), { appIDs: [dev], components: [{ '/': '/oauth/ios/pl.gov.psp.civcom.dev' }] });
  assert.deepEqual(merged.applinks.details.at(-1), { appIDs: [prod], components: [{ '/': '/oauth/ios/pl.gov.psp.civcom' }] });
});

test('HEAD has the same headers and no body', async () => {
  for (const path of paths) {
    const r = worker.fetch(new Request('https://civcom.soia.info' + path, { method: 'HEAD' }));
    assert.equal(r.status, 200);
    assert.equal(await r.text(), '');
    assert.match(r.headers.get('content-type'), /^application\/json/);
  }
});

test('unrelated app URLs, hosts, schemes and queries are rejected by the handler', () => {
  for (const url of ['https://civcom.soia.info/', 'https://civcom.soia.info/config.json',
    'https://civcom.soia.info/oauth/ios/pl.gov.psp.civcom.dev', 'https://auth.soia.info/apple-app-site-association',
    'http://civcom.soia.info/apple-app-site-association', 'https://civcom.soia.info/apple-app-site-association?other=1']) {
    assert.equal(worker.fetch(new Request(url)).status, 404);
  }
});

test('mutating methods cannot alter the association', () => {
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
    const r = worker.fetch(new Request('https://civcom.soia.info/apple-app-site-association', { method }));
    assert.equal(r.status, 405);
    assert.equal(r.headers.get('allow'), 'GET, HEAD');
  }
});

test('deployment routes cover only the two exact HTTPS paths', () => {
  const config = JSON.parse(readFileSync(new URL('./wrangler.jsonc', import.meta.url)));
  assert.deepEqual(config.routes, paths.map(path => ({ pattern: 'https://civcom.soia.info' + path, zone_name: 'soia.info' })));
  assert.equal(config.workers_dev, false);
  assert.equal(config.preview_urls, false);
  assert.equal(config.compatibility_date, '2026-10-05');
  assert.equal(config.observability.head_sampling_rate, 0);
});
