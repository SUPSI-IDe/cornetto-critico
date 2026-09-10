import test from 'node:test';
import assert from 'node:assert/strict';

import { decodeBase64Utf8, fetchSnapshot, getSnapshotRows } from './snapshot-loader.mjs';

test('decodeBase64Utf8 decodes UTF-8 safely', function() {
  const encoded = Buffer.from('{"name":"Città"}', 'utf8').toString('base64');
  assert.equal(decodeBase64Utf8(encoded), '{"name":"Città"}');
});

test('getSnapshotRows accepts supported shapes', function() {
  assert.deepEqual(getSnapshotRows([{ id: 1 }]), [{ id: 1 }]);
  assert.deepEqual(getSnapshotRows({ pending: [{ id: 2 }] }), [{ id: 2 }]);
  assert.deepEqual(getSnapshotRows({ registrations: [{ id: 3 }] }), [{ id: 3 }]);
  assert.deepEqual(getSnapshotRows({}), []);
  assert.equal(getSnapshotRows({ invalid: true }), null);
});

test('fetchSnapshot reads GitHub contents API payload', async function() {
  const payload = {
    type: 'file',
    encoding: 'base64',
    truncated: false,
    content: Buffer.from('{"updated_at":"2026-09-10T08:00:00Z","pending":[{"id":1,"print_status":"pending"}]}', 'utf8').toString('base64')
  };

  const fetchCalls = [];
  const fetchImpl = async function(url) {
    fetchCalls.push(url);
    return {
      ok: true,
      async json() {
        return payload;
      }
    };
  };

  const result = await fetchSnapshot(fetchImpl, [
    { url: 'https://api.github.com/test', type: 'github-contents', label: 'github-contents' }
  ]);

  assert.equal(fetchCalls.length, 1);
  assert.equal(result.updated_at, '2026-09-10T08:00:00Z');
  assert.deepEqual(result.pending, [{ id: 1, print_status: 'pending' }]);
});

test('fetchSnapshot falls back when GitHub payload is invalid', async function() {
  const fetchImpl = async function(url) {
    if (url === 'https://api.github.com/test') {
      return {
        ok: true,
        async json() {
          return { message: 'API rate limit exceeded' };
        }
      };
    }

    return {
      ok: true,
      async text() {
        return '{"updated_at":"2026-09-10T08:05:00Z","pending":[{"id":2,"print_status":"pending"}]}';
      }
    };
  };

  const result = await fetchSnapshot(fetchImpl, [
    { url: 'https://api.github.com/test', type: 'github-contents', label: 'github-contents' },
    { url: './pending.json', type: 'plain-json', label: 'local snapshot' }
  ]);

  assert.equal(result.updated_at, '2026-09-10T08:05:00Z');
  assert.deepEqual(result.pending, [{ id: 2, print_status: 'pending' }]);
});

test('fetchSnapshot uses download_url when content is omitted', async function() {
  const payload = {
    type: 'file',
    encoding: 'base64',
    truncated: false,
    content: '',
    download_url: 'https://example.test/pending.json'
  };

  const fetchImpl = async function(url) {
    if (url === 'https://api.github.com/test') {
      return {
        ok: true,
        async json() {
          return payload;
        }
      };
    }

    assert.equal(url, 'https://example.test/pending.json');
    return {
      ok: true,
      async text() {
        return '{"updated_at":"2026-09-10T08:10:00Z","pending":[]}';
      }
    };
  };

  const result = await fetchSnapshot(fetchImpl, [
    { url: 'https://api.github.com/test', type: 'github-contents', label: 'github-contents' }
  ]);

  assert.equal(result.updated_at, '2026-09-10T08:10:00Z');
  assert.deepEqual(result.pending, []);
});

test('fetchSnapshot uses download_url when base64 content is invalid', async function() {
  const payload = {
    type: 'file',
    encoding: 'base64',
    truncated: false,
    content: '***not-base64***',
    download_url: 'https://example.test/pending-invalid-base64.json'
  };

  const fetchImpl = async function(url) {
    if (url === 'https://api.github.com/test') {
      return {
        ok: true,
        async json() {
          return payload;
        }
      };
    }

    assert.equal(url, 'https://example.test/pending-invalid-base64.json');
    return {
      ok: true,
      async text() {
        return '{"updated_at":"2026-09-10T08:15:00Z","pending":[{"id":4,"print_status":"pending"}]}';
      }
    };
  };

  const result = await fetchSnapshot(fetchImpl, [
    { url: 'https://api.github.com/test', type: 'github-contents', label: 'github-contents' }
  ]);

  assert.equal(result.updated_at, '2026-09-10T08:15:00Z');
  assert.deepEqual(result.pending, [{ id: 4, print_status: 'pending' }]);
});
