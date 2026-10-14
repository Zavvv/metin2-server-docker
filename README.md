# Metin2 protected-update staging

Questo branch (`main-update`) contiene il tree Docker aggiornato per la linea
protetta Metin2 Singleplayer / Playerbots. Serve come staging prima del push su
GitHub: ogni nuovo archivio pubblicato dal creatore viene confrontato qui e
viene copiato solo il suo contesto Docker.

## Regola essenziale: file locali protetti

Non sovrascrivere mai questi file con quelli dell'archivio di update:

- `docker-compose.yml`
- `panel/Dockerfile`
- `docker-compose.updater.yml`
- `docker-compose.restore.yml`

Gli ultimi due sono i nomi realmente presenti nel branch remoto al momento
della configurazione. Sono le configurazioni locali di update e restore; il
pacchetto ufficiale non li include. Le diciture storiche
`docker-compose-update.yml` e `docker-compose-restore.yml` indicano questi
due file e non devono essere introdotte come sostituti senza una decisione
esplicita.

## Come importare un archivio protetto

1. L'archivio deve essere letto senza eseguire script inclusi.
2. Verificare `VERSION`, `PACZKA_INFO.txt`, `CHANGELOG.md` e
   `linux-port/PROTECTED`.
3. Gli archivi `protected-update` sono differenziali: partire sempre dal tree
   funzionante già presente nel branch e sovrapporre `linux-port/docker/` alla
   radice. Non svuotare il tree quando l'archivio non dichiara esplicitamente
   la rimozione di un file.
4. Conservare `game/share/`: è il payload runtime base (mappe, dati, locale e
   quest) e non è incluso negli update differenziali. Il Dockerfile di gioco
   richiede almeno `share/CMD`, `share/data`, `share/locale` e
   `share/locale/poland/quest/quest_functions`.
5. Estrarre anche `VERSION` e `CHANGELOG.md` dalla radice dell'archivio e
   copiarli rispettivamente in `panel/app/VERSION` e
   `panel/app/CHANGELOG.md`. Il pannello li incorpora nell'immagine e senza di
   essi mostra “Version unknown”.
6. Escludere sempre i quattro file protetti sopra; per `panel/`, copiare tutto
   tranne `panel/Dockerfile`.
7. Mantenere `mariadb/Dockerfile`: l'immagine MariaDB deve includere
   configurazione, `initdb.d/` e `playerbot/`, perché il servizio
   `playerbot-migrate` esegue `/opt/playerbot/apply.sh` dalla stessa immagine.
8. Confrontare gli hash SHA-256 dei file protetti prima e dopo la copia.
9. Controllare `git status`, stageare il risultato e rivedere il diff prima di
   qualsiasi commit o push.

## Deploy con Portainer

Questo progetto non usa `update.sh`. Dopo ogni importazione, eseguire il
commit e il push del branch `main-update`; quindi, nello Stack Portainer
collegato a quel branch, usare **Pull and redeploy**.

Il Compose conserva contesti di build relativi alla radice del repository:
`./mariadb`, `./game`, `./panel`, `./seban-panel` e `./itemshop`. Portainer
scarica il commit del branch e ricostruisce gli stessi servizi con i file
aggiornati. Le impostazioni, i volumi e il database restano fuori dal branch:
non eliminare i volumi durante il redeploy.

L'archivio è comunque della linea protetta 2.x. Non usare l'installer o
l'updater della vecchia linea 1.x: applicano un tree incompatibile alla
release protetta.

### Dati persistenti: regola non negoziabile

I dati di gioco non fanno parte di questo branch: MariaDB conserva account,
personaggi, inventari, ItemShop e progressi bot nel volume Docker `db-data`
montato in `/var/lib/mysql`. Gli stati del gioco e dei pannelli risiedono negli
altri volumi nominati (`game-var`, `panel-data`, `panel-conf`, `update-spool` e
`rates-spool`).

Per ogni aggiornamento usare soltanto **Pull and redeploy** sullo stesso Stack
Portainer e mantenere invariato `M2_COMPOSE_PROJECT_NAME`. Non usare mai
**Remove volumes**, `docker compose down -v`, `docker volume rm`, un cleanup
di volumi Docker, né eliminare lo Stack includendo i volumi. Il redeploy può
ricreare le immagini e i container, ma non deve mai rimuovere o rinominare i
volumi persistenti.

## Ultima importazione analizzata

- Archivio: `metin2-server-protected-update-2.2.96.zip`
- Versione: `2.2.96`
- Tipo: release protetta 2.x
- Mapping applicato: `linux-port/docker/` → radice del branch
