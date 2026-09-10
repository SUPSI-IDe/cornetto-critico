# Cornetto Critico - Progetto

Quando parliamo di materia, non nominiamo soltanto ciò di cui le cose sono fatte. Nella sua radice si conserva un’idea di costruzione e di composizione che apre la parola ben oltre la sostanza, facendone un punto di accesso alle diverse dimensioni della ricerca e del progetto. È nella materia, infatti, che una pratica prende forma, che un sapere si traduce, che un’idea entra in relazione con il mondo.
È da questa soglia che prende avvio Cornetto Critico, come riflessione interdisciplinare sulla materia intesa come interfaccia sensibile attraverso la quale la vita si manifesta secondo un processo continuo di azione e reazione. Una trama complessa di legami chimici, culturali, ecologici e tecnologici attraversa così l’intera rassegna, disponendosi in una costellazione di campi di relazione che ne orientano la lettura: individuo–spazio pubblico, superficie–profondità, pratica–sapere, specie–ecosistema, vivente–risorsa, dispositivo–infrastruttura, percezione–automazione. 
In questo quadro, il dialogo collettivo si propone di interrogare non soltanto le relazioni tra soggetti, ma anche quelle che intratteniamo con gli elementi che manipoliamo, abitiamo e trasformiamo quotidianamente. Dalla scala più minuta a quella più ampia, queste relazioni caratterizzano le forme del vivere contemporaneo e incidono sul nostro modo di percepire, progettare e immaginare il mondo.
La rassegna si articola in sette incontri, intesi come sette declinazioni della materia, ciascuna attraversata da uno specifico asse di lettura: urbana, profonda, antica, di specie, alimentare, digitale, aerea. L’obiettivo è aprire uno spazio di confronto sperimentale, capace di generare domande, intrecciare saperi e oltrepassare i confini disciplinari. Un luogo di dialogo aperto tra conoscenze e pratiche eterogenee, pensato per stimolare consapevolezza, immaginazione e responsabilità progettuale. Non per offrire soluzioni definitive, ma per costruire insieme nuovi scenari di riflessione condivisa.

Website design [@Alice Mioni](https://alicemioni.ch/) & [@Alessandro Plantera](https://alessandroplantera.ch/)

Website and hardware implementation [@Alice Mioni](https://alicemioni.ch/) [@Alessandro Plantera](https://alessandroplantera.ch/) & [@Matteo Subet](https://zumat.ch/)

## Informazioni

Questa repository raccoglie l'intero progetto Cornetto Critico: il sito informativo, la pagina iscrizioni, i flussi di sincronizzazione dati e il codice per la stampante termica.

## Componenti

- **Sito principale** — presenta il progetto, gli eventi e il conteggio delle iscrizioni
- **Pagina Iscrizioni** — gestisce la registrazione dei partecipanti e l'inserimento dei dati su Supabase
- **Dashboard pending** — mostra le registrazioni in attesa di stampa e legge `check-printer/pending.json`
- **Codice per stampante termica** — sketch Arduino/ESP32 in `printScontrino/` per la gestione della stampante e dello stato di stampa

## Dati

Il conteggio iscrizioni viene aggiornato da GitHub Actions usando le repository secrets `SUPABASE_URL` e `SUPABASE_KEY`, che generano `count.json` con il totale e il dettaglio per evento.

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

In locale il sito legge `count.json` direttamente, senza esporre chiavi API nel browser.

## Aggiornare count.json in locale

Assicurarsi di avere `curl` e `jq` installati, poi eseguire:

```sh
./fetch-count.sh
```

Lo script legge le credenziali da `.env` e sovrascrive `count.json` con i dati reali da Supabase, replicando il comportamento del workflow GitHub Actions.

## Variabili ambiente

Le secrets non vengono mai lette dal browser. Vengono usate solo dai workflow `update-count.yml`, `update-pending-dashboard.yml`, `register.yml` e dallo script locale `fetch-count.sh`.

Creare un file `.env` nella root del progetto:

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-secret-key
```

## GitHub Actions

I workflow principali sono:

- **`update-count.yml`** — si esegue su schedulazione, interroga Supabase, aggiorna `count.json` e fa commit su `main`
- **`update-pending-dashboard.yml`** — si esegue ogni 15 minuti (ai minuti 7, 22, 37 e 52), aggiorna `check-printer/pending.json` con le registrazioni ancora in stato pending
- **`register.yml`** — inserisce una nuova registrazione in Supabase tramite `repository_dispatch` o `workflow_dispatch`
- **`deploy.yml`** — si esegue ad ogni push su `main`, pubblica il sito su GitHub Pages

Assicurarsi che in **Settings → Pages → Source** sia selezionato **"GitHub Actions"**.

## Stampante termica

Il codice Arduino per la stampante termica si trova in `printScontrino/`.

- il progetto è pensato per ESP32 con connessione Wi-Fi
- la stampa legge le registrazioni pending da Supabase
- il flusso aggiorna lo stato della registrazione dopo la stampa e associa il `printer_id`

## Dashboard pending

La dashboard di controllo si trova in `check-printer/` e usa `pending.json` come snapshot delle registrazioni ancora da stampare. Il file viene generato dal workflow `update-pending-dashboard.yml` e la pagina lo legge direttamente dal branch `main` tramite GitHub API, quindi non richiede un nuovo deploy di Pages per i soli aggiornamenti dati.

## Registrazioni

La pagina iscrizioni si trova in `iscrizioni/` e invia i dati al flusso di registrazione automatizzato. Il workflow `register.yml` crea il record su Supabase con i dati dell'evento e del partecipante.

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
