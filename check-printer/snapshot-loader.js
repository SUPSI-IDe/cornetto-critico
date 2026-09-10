(function() {
  const DEFAULT_PENDING_JSON_SOURCES = [
    {
      url: 'https://api.github.com/repos/SUPSI-IDe/cornetto-critico/contents/check-printer/pending.json?ref=main',
      type: 'github-contents',
      label: 'github-contents'
    },
    {
      url: './pending.json',
      type: 'plain-json',
      label: 'local snapshot'
    },
    {
      url: '/check-printer/pending.json',
      type: 'plain-json',
      label: 'pages snapshot'
    }
  ];

  function getSnapshotRows(payload) {
    if (Array.isArray(payload)) {
      return payload;
    }

    if (payload == null) {
      return [];
    }

    if (payload && Array.isArray(payload.pending)) {
      return payload.pending;
    }

    if (payload && Array.isArray(payload.registrations)) {
      return payload.registrations;
    }

    if (payload && typeof payload === 'object' && Object.keys(payload).length === 0) {
      return [];
    }

    return null;
  }

  function decodeBase64Utf8(value) {
    const binary = atob(value);
    const bytes = Uint8Array.from(binary, function(char) {
      return char.charCodeAt(0);
    });
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  }

  function buildRequestUrl(source) {
    if (source.type === 'github-contents') {
      return source.url;
    }

    const url = new URL(source.url, window.location.href);
    url.searchParams.set('t', String(Date.now()));
    return url.toString();
  }

  async function fetchPlainJsonText(fetchImpl, url) {
    const response = await fetchImpl(url, {
      cache: 'no-store',
      headers: {
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        Pragma: 'no-cache'
      }
    });

    if (!response.ok) {
      throw new Error(`Snapshot ${response.status}`);
    }

    return response.text();
  }

  async function fetchGithubContentsText(fetchImpl, source) {
    const response = await fetchImpl(source.url, {
      cache: 'no-store',
      headers: {
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        Pragma: 'no-cache'
      }
    });

    if (!response.ok) {
      throw new Error(`Snapshot ${response.status}`);
    }

    const payloadResponse = await response.json();

    if (!payloadResponse || typeof payloadResponse !== 'object' || Array.isArray(payloadResponse)) {
      throw new Error(`GitHub API payload non valido: responseType=${Array.isArray(payloadResponse) ? 'array' : typeof payloadResponse}`);
    }

    const isValidFilePayload =
      payloadResponse.type === 'file' &&
      payloadResponse.encoding === 'base64' &&
      !payloadResponse.truncated;

    if (!isValidFilePayload && payloadResponse.message) {
      throw new Error(`GitHub API errore: ${payloadResponse.message}`);
    }

    if (typeof payloadResponse.content === 'string' && payloadResponse.content.trim()) {
      try {
        return decodeBase64Utf8(payloadResponse.content.replace(/\s+/g, ''));
      } catch (error) {
        if (isValidFilePayload && typeof payloadResponse.download_url === 'string' && payloadResponse.download_url) {
          return fetchPlainJsonText(fetchImpl, payloadResponse.download_url);
        }
        throw new Error(`Errore decodifica snapshot: ${error instanceof Error && error.message ? error.message : 'contenuto base64 non valido'}`);
      }
    }

    if (isValidFilePayload && typeof payloadResponse.download_url === 'string' && payloadResponse.download_url) {
      return fetchPlainJsonText(fetchImpl, payloadResponse.download_url);
    }

    throw new Error(
      `GitHub API payload non valido: type=${payloadResponse.type || 'n/d'}, encoding=${payloadResponse.encoding || 'n/d'}, truncated=${String(Boolean(payloadResponse.truncated))}, hasContent=${String(typeof payloadResponse.content === 'string' && payloadResponse.content.trim().length > 0)}, hasDownloadUrl=${String(typeof payloadResponse.download_url === 'string' && payloadResponse.download_url.length > 0)}`
    );
  }

  function parseSnapshotPayload(rawText, source) {
    const trimmedText = rawText.trim();
    const payload = trimmedText ? JSON.parse(trimmedText) : [];
    const rows = getSnapshotRows(payload);
    if (!rows) {
      const payloadType = Array.isArray(payload) ? 'array' : typeof payload;
      throw new Error(`Formato pending.json non valido (${source.label}): payloadType=${payloadType}, hasPendingArray=${String(Boolean(payload && Array.isArray(payload.pending)))}, hasRegistrationsArray=${String(Boolean(payload && Array.isArray(payload.registrations)))}`);
    }

    return {
      updated_at: payload && Object.prototype.hasOwnProperty.call(payload, 'updated_at') ? payload.updated_at : null,
      pending: rows
    };
  }

  async function fetchSnapshot(fetchImpl, sources) {
    const resolvedFetch = fetchImpl ?? fetch;
    const resolvedSources = sources ?? DEFAULT_PENDING_JSON_SOURCES;
    let lastError = null;

    for (const source of resolvedSources) {
      try {
        const rawText = source.type === 'github-contents'
          ? await fetchGithubContentsText(resolvedFetch, source)
          : await fetchPlainJsonText(resolvedFetch, buildRequestUrl(source));

        return parseSnapshotPayload(rawText, source);
      } catch (error) {
        const message = error instanceof Error && error.message ? error.message : 'errore sconosciuto';
        lastError = new Error(`${message} (${source.label})`);
      }
    }

    throw lastError || new Error('Impossibile leggere pending.json');
  }

  window.CornettoSnapshotLoader = {
    DEFAULT_PENDING_JSON_SOURCES,
    fetchSnapshot
  };
})();
