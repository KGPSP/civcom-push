// Copyright 2026 KG PSP. SPDX-License-Identifier: AGPL-3.0-only
import association from './association.json' with { type: 'json' };

const body = JSON.stringify(association) + '\n';
const paths = new Set(['/apple-app-site-association', '/.well-known/apple-app-site-association']);

export default {
  fetch(request) {
    const url = new URL(request.url);
    if (url.protocol !== 'https:' || url.hostname !== 'civcom.soia.info' || !paths.has(url.pathname) || url.search) {
      return new Response('Not found\n', { status: 404 });
    }
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return new Response('Method not allowed\n', { status: 405, headers: { Allow: 'GET, HEAD' } });
    }
    return new Response(request.method === 'HEAD' ? null : body, {
      headers: {
        'Content-Type': 'application/json; charset=utf-8',
        'Cache-Control': 'public, max-age=300',
        'X-Content-Type-Options': 'nosniff',
      },
    });
  },
};
