# LoxBerry Plugin Development & Release Guidelines for smtp2mqtt

Tento dokument kodifikuje závazná pravidla pro vývoj, balení, AutoUpdate a správu pluginu `smtp2mqtt` pro platformu LoxBerry.

---

## 1. Pravidla pro LoxBerry AutoUpdate (`release.cfg` vs `prerelease.cfg`)

LoxBerry Plugin Manager rozlišuje aktualizační kanály na základě uživatelské volby v administraci:
- **Kanál Releases (Stabilní verze):** LoxBerry načítá soubor `release.cfg`.
- **Kanál Pre- and Releases (Testovací/Vývojové verze):** LoxBerry načítá soubor `prerelease.cfg`.

### ⚠️ Zásadní pravidlo pro vydávání nových verzí:
* **Prerelease verze:**
  - `release.cfg` **MUSÍ ZŮSTAT** na poslední oficiální stabilní verzi (např. `VERSION=1.8.18`).
  - `prerelease.cfg` **SE NAVÝŠÍ** na novou prerelease verzi (např. `VERSION=1.8.19`).
  - Tím se zajistí, že běžní uživatelé zůstanou na stabilní verzi 1.8.18, zatímco vývojáři/testery uvidí v LoxBerry nabídku **"New Pre-Release 1.8.19"**.
* **Plná Release verze:**
  - Obe verze `release.cfg` i `prerelease.cfg` se nastaví na stejnou stabilní verzi.

---

## 2. Zákaz natvrdo zadaných cest (`/opt/loxberry`)

LoxBerry balíčkovací systém provádí při instalaci statickou analýzu všech skriptů.
- **Pravidlo:** V balíčkovacích skriptech (`daemon/daemon`, `uninstall/uninstall`, `postinstall.sh`, `postupgrade.sh`) **nikdy nepoužívej natvrdo zadanou cestu `/opt/loxberry`**.
- **Správné řešení:** Vždy používej systémové proměnné s fallbackem: `${LBHOMEDIR:-$HOME}`, `$LBPLOG`, `$LBPDATA`, `$LBPCONFIG`, `$LBPBIN`.

---

## 3. Bezpečné spouštění skriptů a daemona (`su` vs `runuser`)

V neinteraktivním prostředí instalačních a systémových skriptů LoxBerry způsobuje příkaz `su - loxberry -c "..."` chybu `su: Authentication failure`.
- **Pravidlo pro spouštění daemona pod uživatelem `loxberry`:**
  ```bash
  if [ "$(id -un 2>/dev/null)" = "loxberry" ]; then
      nohup python3 "$DAEMON" > /dev/null 2>&1 &
  elif command -v runuser >/dev/null 2>&1; then
      runuser -u loxberry -- nohup python3 "$DAEMON" > /dev/null 2>&1 &
  elif id -u loxberry >/dev/null 2>&1; then
      su -s /bin/bash loxberry -c "nohup python3 '$DAEMON' > /dev/null 2>&1 &"
  else
      nohup python3 "$DAEMON" > /dev/null 2>&1 &
  fi
  ```

---

## 4. Detekce LoxBerry MQTT Gateway V2 Přihlašovacích Údajů

LoxBerry MQTT Gateway V2 ukládá konfiguraci do `/opt/loxberry/config/system/mqttgateway.json`.
- **Struktura JSONu:**
  - Sekce `Main`: obsahuje `brokeraddress` a `brokerport`.
  - Sekce `Credentials`: obsahuje `brokeruser` a `brokerpass`.
- **Pravidlo:** PHP UI (`index.php`) i Python daemon (`smtp2mqtt.py`) **musí číst obě sekce**. Nikdy nepředpokládej, že jsou `brokeruser` a `brokerpass` v kořenu nebo v sekci `Main`.

---

## 5. Správa stavového souboru (`status.json`) a oprávnění

Stavový soubor `status.json` slouží jako komunikační můstek mezi Python daemonem a PHP Web UI.
- **Vytvoření adresáře:** Před zápisem `status.json` v Pythonu vždy volej `os.makedirs(data_dir, exist_ok=True)`.
- **Oprávnění:** Nastavuj `os.chmod(status_file, 0o666)` pro zajištění čitelnosti i zápisového přístupu pro webový server (`www-data` / `loxberry`).
- **Kandidátní cesty v PHP:** V `index.php` vždy procházej pole kandidátních cest (`$lbpdatadir/status.json`, `/opt/loxberry/data/plugins/smtp2mqtt/status.json`, atd.).

---

## 6. Časové jednotky pro Auto-Reset (`MQTT_RESET_TIME`)

- `MQTT_RESET_TIME` je v Pythonu i PHP konfiguraci definován v **milisekundách (ms)** (výchozí: `200` ms).
- V HTML formuláři UI musí být popisek výhradně `MQTT Auto-Reset Čas (ms):` a nápověda udána v milisekundách.

---

## 7. Logika monitorů spojení (`monitor_mqtt_broker`)

- `monitor_mqtt_broker()` testuje TCP socket na portu 1883.
- **Pravidlo:** Pokud Paho MQTT klient selže na autentizaci (`Not authorized`), monitorovací cyklus **nesmí** přepsat stav na `Online` jen proto, že TCP port 1883 přijímá spojení.

---

## 8. Osobní branding & darovací odkaz

- Projekt je výhradně osobní open-source projekt Ondřeje Hály (`ondrejhala@gmail.com`).
- Nákup kávy: `https://buymeacoffee.com/ondrejhala8`.
- Do projektu nevkládej žádné zmínky o firemních entitách.
