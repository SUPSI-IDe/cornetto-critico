# Cornetto Critico - Sito web

Sito statico che mostra informazioni sul Cornetto Critico e le iscrizioni per evento.

Il conteggio viene aggiornato da GitHub Actions usando le repository secrets `SUPABASE_URL` e `SUPABASE_KEY`, che generano il file `count.json` con il totale e il dettaglio per evento.

## Struttura di count.json

```json
{
  "total": 59,
  "updated_at": "2026-05-07T09:33:27Z",
  "events": {
    "1. materia urbana": 48,
    "2. materia profonda": 11
  }
}
```

## Avvio locale

Servire la cartella con un server statico (es. Five Server) oppure aprire il sito pubblicato su GitHub Pages.

In locale il sito legge `count.json` direttamente — nessuna chiave API esposta nel browser.

## Aggiornare count.json in locale

Assicurarsi di avere `curl` e `jq` installati, poi eseguire:

```sh
./fetch-count.sh
```

Lo script legge le credenziali da `.env` e sovrascrive `count.json` con i dati reali da Supabase, replicando esattamente il comportamento del workflow GitHub Actions.

## Variabili ambiente

Le secrets non vengono mai lette dal browser. Vengono usate solo dal workflow `update-count.yml` e dallo script locale `fetch-count.sh`.

Creare un file `.env` nella root del progetto:

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-secret-key
```

## GitHub Actions

Due workflow:

- **`update-count.yml`** — si esegue ogni 15 minuti, interroga Supabase, aggiorna `count.json` e fa commit su `main`
- **`deploy.yml`** — si esegue ad ogni push su `main`, pubblica il sito su GitHub Pages

Assicurarsi che in **Settings → Pages → Source** sia selezionato **"GitHub Actions"**.

## Creare fetch-count.sh in locale

Il file `fetch-count.sh` è gitignored e va creato manualmente. Creare il file nella root del progetto con questo contenuto:

```sh
#!/bin/sh
set -e

# Load variables from .env
export $(grep -v '^#' .env | xargs)

test -n "$SUPABASE_URL" || { echo "Missing SUPABASE_URL"; exit 1; }
test -n "$SUPABASE_KEY" || { echo "Missing SUPABASE_KEY"; exit 1; }

RESPONSE=$(curl -sS \
  -H "apikey: $SUPABASE_KEY" \
  -H "Authorization: Bearer $SUPABASE_KEY" \
  "$SUPABASE_URL/rest/v1/registrations?select=event_name")

echo "$RESPONSE" | jq --arg ts "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" '{
  total: length,
  updated_at: $ts,
  events: (group_by(.event_name) | map({key: (.[] | .event_name), value: length}) | from_entries)
}' > count.json

echo "count.json updated:"
cat count.json
```

Poi renderlo eseguibile:

```sh
chmod +x fetch-count.sh
```
