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
3. Il solo contenuto da usare per questa repository piatta è
   `linux-port/docker/`, copiato nella radice del branch.
4. Escludere sempre i quattro file protetti sopra; per `panel/`, copiare tutto
   tranne `panel/Dockerfile`.
5. Confrontare gli hash SHA-256 dei file protetti prima e dopo la copia.
6. Controllare `git status`, stageare il risultato e rivedere il diff prima di
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

## Ultima importazione analizzata

- Archivio: `metin2-server-protected-update-2.2.89.zip`
- Versione: `2.2.89`
- Tipo: release protetta 2.x
- Mapping applicato: `linux-port/docker/` → radice del branch
