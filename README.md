# Cornetto Critico - Sito web

Quando parliamo di materia, non nominiamo soltanto ciò di cui le cose sono fatte. Nella sua radice si conserva un’idea di costruzione e di composizione che apre la parola ben oltre la sostanza, facendone un punto di accesso alle diverse dimensioni della ricerca e del progetto. È nella materia, infatti, che una pratica prende forma, che un sapere si traduce, che un’idea entra in relazione con il mondo.
È da questa soglia che prende avvio Cornetto Critico, come riflessione interdisciplinare sulla materia intesa come interfaccia sensibile attraverso la quale la vita si manifesta secondo un processo continuo di azione e reazione. Una trama complessa di legami chimici, culturali, ecologici e tecnologici attraversa così l’intera rassegna, disponendosi in una costellazione di campi di relazione che ne orientano la lettura: individuo–spazio pubblico, superficie–profondità, pratica–sapere, specie–ecosistema, vivente–risorsa, dispositivo–infrastruttura, percezione–automazione. 
In questo quadro, il dialogo collettivo si propone di interrogare non soltanto le relazioni tra soggetti, ma anche quelle che intratteniamo con gli elementi che manipoliamo, abitiamo e trasformiamo quotidianamente. Dalla scala più minuta a quella più ampia, queste relazioni caratterizzano le forme del vivere contemporaneo e incidono sul nostro modo di percepire, progettare e immaginare il mondo.
La rassegna si articola in sette incontri, intesi come sette declinazioni della materia, ciascuna attraversata da uno specifico asse di lettura: urbana, profonda, antica, di specie, alimentare, digitale, aerea. L’obiettivo è aprire uno spazio di confronto sperimentale, capace di generare domande, intrecciare saperi e oltrepassare i confini disciplinari. Un luogo di dialogo aperto tra conoscenze e pratiche eterogenee, pensato per stimolare consapevolezza, immaginazione e responsabilità progettuale. Non per offrire soluzioni definitive, ma per costruire insieme nuovi scenari di riflessione condivisa.

Website design [@Alice Mioni](https://alicemioni.ch/) & [@Alessandro Plantera](https://alessandroplantera.ch/)

Website implementation [@Alice Mioni](https://alicemioni.ch/) [@Alessandro Plantera](https://alessandroplantera.ch/) & [@Matteo Subet](https://zumat.ch/)

## Informazioni

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
