<p align="center">
  <h1 align="center">🛒 knuspr-cli</h1>
</p>

<p align="center">
  <strong>Einkaufen bei Knuspr.de — direkt vom Terminal</strong>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="Python 3.9+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/dependencies-keine-brightgreen.svg" alt="Keine Dependencies">
</p>

---

## Was ist das?

**knuspr-cli** bringt den Knuspr.de Online-Supermarkt ins Terminal. Produkte suchen, Warenkorb verwalten, Lieferslots reservieren — alles ohne Browser.

- **Schnell** — keine langsamen Web-Apps
- **Hackbar** — pipe Produkte in andere Tools, automatisiere deinen Einkauf
- **Portabel** — läuft überall, nur Python Standard Library (keine Dependencies)

> ⚠️ **Hinweis:** Dies ist ein Hobby-Projekt für die persönliche Nutzung. Nicht offiziell mit Knuspr.de verbunden oder von Knuspr.de unterstützt.

---

## Schnellstart

```bash
# Mit uvx (empfohlen) — läuft sofort ohne Installation
uvx --from git+https://github.com/Lars147/knuspr-cli knuspr login

# Einloggen, dann loslegen
uvx --from git+https://github.com/Lars147/knuspr-cli knuspr search "Milch"
```

---

## Features

| Feature | Beschreibung |
|---------|-------------|
| 🎯 **Setup** | Interaktives Onboarding — Bio-Präferenz, Sortierung, Ausschlüsse |
| 🔐 **Login** | Sichere Authentifizierung mit deinem Knuspr-Account |
| 🔍 **Suche** | Produkte durchsuchen mit Filtern |
| 📦 **Produkt** | Detaillierte Produktinformationen |
| ⭐ **Favoriten** | Favoriten anzeigen, hinzufügen, entfernen |
| 🥬 **Rette** | Alle Rette-Lebensmittel (bald ablaufend, reduziert) |
| 🛒 **Warenkorb** | Anzeigen, hinzufügen, entfernen |
| 📅 **Lieferslots** | Zeitfenster anzeigen und **reservieren** |
| 📋 **Bestellungen** | Bestellhistorie und Details |
| 👤 **Account** | Account-Info, Premium-Status |
| 🍽️ **Mahlzeiten** | Mahlzeitvorschläge nach Kategorie |
| ⚡ **JSON** | Maschinenlesbare Ausgabe für Scripting |

---

## Installation

### Option 1: uvx (empfohlen)

```bash
# Direkt ausführen — keine Installation nötig
uvx --from git+https://github.com/Lars147/knuspr-cli knuspr --help

# Oder global installieren
uv tool install git+https://github.com/Lars147/knuspr-cli
knuspr --help

# Update
uv tool install --upgrade git+https://github.com/Lars147/knuspr-cli
```

### Option 2: pipx

```bash
pipx install git+https://github.com/Lars147/knuspr-cli
knuspr --help
```

### Option 3: Repository klonen

```bash
git clone https://github.com/Lars147/knuspr-cli.git
cd knuspr-cli
python3 knuspr_cli.py --help
```

---

## Verwendung

### Setup & Login

```bash
knuspr setup                    # Interaktives Onboarding (Bio, Sortierung, Ausschlüsse)
knuspr login                    # Einloggen
knuspr status                   # Login-Status prüfen
knuspr logout                   # Ausloggen
```

### Suche

```bash
knuspr search "Milch"           # Einfache Suche
knuspr search "Käse" -n 20      # Mehr Ergebnisse
knuspr search "Brot" --favorites  # Nur Favoriten
knuspr search "Obst" --json     # JSON Output
```

### Rette Lebensmittel

Produkte die bald ablaufen — reduziert, gegen Verschwendung:

```bash
knuspr rette                    # Alle Rette-Produkte
knuspr rette "Krapfen"          # Filtern
knuspr search "X" --expiring    # Suche + Badge-Filter
```

### Produkt-Details

```bash
knuspr product 5273             # Produkt-Details
knuspr product 5273 --json      # Als JSON
```

### Favoriten

```bash
knuspr favorites                # Alle Favoriten
knuspr favorites add 123456     # Hinzufügen
knuspr favorites remove 123456  # Entfernen
```

### Warenkorb

```bash
knuspr cart show                # Warenkorb anzeigen
knuspr cart add 123456          # Produkt hinzufügen
knuspr cart add 123456 -q 3     # 3 Stück hinzufügen
knuspr cart remove 123456       # Entfernen
knuspr cart open                # Im Browser öffnen
```

### Lieferung & Slot-Reservierung

```bash
knuspr slots                    # Verfügbare Zeitfenster
knuspr slots --detailed         # Mit 15-Minuten Slots + IDs
knuspr delivery                 # Aktuelle Lieferinfos

# Slot reservieren (60 Minuten gültig)
knuspr slot reserve 262025      # Slot-ID aus --detailed
knuspr slot status              # Reservierung anzeigen
knuspr slot cancel              # Reservierung stornieren
```

### Bestellungen

```bash
knuspr orders                   # Bestellhistorie
knuspr order 12345678           # Details einer Bestellung
```

### Account & mehr

```bash
knuspr account                  # Account-Info, Premium-Status
knuspr frequent                 # Häufig gekaufte Produkte
knuspr meals breakfast          # Frühstücks-Vorschläge
knuspr meals lunch              # Mittagessen
knuspr meals dinner             # Abendessen
```

---

## Konfiguration

Credentials können auf verschiedene Weisen bereitgestellt werden:

### 1. Interaktiv

```bash
knuspr login
# → Prompt für E-Mail und Passwort
```

### 2. Command-line

```bash
knuspr login --email user@example.com --password secret
```

### 3. Environment Variables

```bash
export KNUSPR_EMAIL="user@example.com"
export KNUSPR_PASSWORD="secret"
knuspr login
```

### 4. Credentials-Datei

Erstelle `~/.knuspr_credentials.json`:
```json
{
  "email": "user@example.com",
  "password": "secret"
}
```

---

## Dateien

```
~/
├── .knuspr_session.json       # Session-Cookies
├── .knuspr_credentials.json   # Gespeicherte Credentials (optional)
└── .knuspr_config.json        # Setup-Präferenzen (optional)
```

---

## Lizenz

MIT © [Lars Heinen](https://github.com/Lars147)

---

<p align="center">
  <sub>Für alle, die lieber tippen als klicken 🖥️</sub>
</p>
