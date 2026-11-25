# Print Monitor (macOS)
Controlla la tabella `registrations` su Supabase e avvisa quando gli scontrini
non vengono stampati. Gira in locale sul Mac dello staff e mostra una dashboard
nel browser su `http://127.0.0.1:8765`.

## Cosa mostra

- **Stampe in coda**: righe con `print_status` diverso da `printed`.
- **Stampe bloccate**: in coda da più di 3 minuti, evidenziate in rosso.
- **Ultima iscrizione** della tabella, con data e stato: conferma che il database risponde.
- **Stato del monitor**: ora dell'ultima lettura riuscita e countdown alla prossima (ogni 15 s).

## Notifiche macOS

- Una sola notifica riassuntiva quando compaiono nuove stampe bloccate.
- Una notifica "URGENT", ripetuta, quando le stampe bloccate diventano 3 o più.

Le notifiche usano `osascript`: l'app che avvia lo script (Terminale o altro)
deve avere le notifiche attive in *Impostazioni di Sistema → Notifiche*.

## Installazione (una volta)

```bash
cd check-printer
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

Crea `check-printer/.env`, che non va committato perché è già in `.gitignore`.
Usa gli stessi URL e chiave anon di `printScontrino/secrets.h`:

```
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=chiave-anon

# facoltativi, questi sono i valori predefiniti:
STALE_MINUTES=3
POLL_SECONDS=15
FAILURE_ESCALATION_THRESHOLD=3
PRINTED_STATUS=printed
PRINT_MONITOR_PORT=8765
```

## Avvio

| Script | Cosa fa |
|---|---|
| `./run_print_monitor.sh` | Avvia il monitor; si chiude con Ctrl+C |
| `./run_print_monitor_background.sh` | Avvia il monitor senza venv attivato; per l'avvio automatico al login |
| `./open_print_monitor_window.sh` | Apre la dashboard in una finestra Chrome dedicata (altrimenti nel browser predefinito) |

Il monitor e la finestra sono due cose separate: prima si avvia il monitor,
poi si apre la dashboard. Chiudere la finestra non ferma il monitor.

Se la porta 8765 è occupata, metti `PRINT_MONITOR_PORT=8766` nel `.env`.
