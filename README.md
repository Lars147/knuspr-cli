<p align="center">
  <h1 align="center">🛒 knuspr-cli</h1>
</p>

<p align="center">
  <strong>Einkaufen bei Knuspr.de — direkt vom Terminal</strong>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="Python 3.9+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/dependencies-none-brightgreen.svg" alt="Zero Dependencies">
</p>

<p align="center">
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-features">Features</a> •
  <a href="#-demo">Demo</a> •
  <a href="#-installation">Installation</a> •
  <a href="#-usage">Usage</a>
</p>

---

## What is this?

**knuspr-cli** bringt den Knuspr.de Online-Supermarkt ins Terminal. Produkte suchen, Warenkorb verwalten — alles ohne Browser.

Schnell (keine langsamen Web-Apps), hackbar (pipe Produkte in andere Tools, automatisiere deinen Einkauf), und läuft überall mit zero dependencies — nur Python Standard Library.

---

## 🚀 Quick Start

```bash
# Mit uvx (empfohlen) — läuft sofort ohne Installation
uvx --from git+https://github.com/Lars147/knuspr-cli knuspr login

# Einloggen, dann loslegen!
uvx --from git+https://github.com/Lars147/knuspr-cli knuspr search "Milch"
```

---

## ✨ Features

| Feature | Beschreibung |
|---------|-------------|
| 🎯 **Setup** | Interaktives Onboarding — Bio-Präferenz, Sortierung, Ausschlüsse |
| 🔐 **Login** | Sichere Authentifizierung mit deinem Knuspr-Account |
| 🔍 **Suche** | Produkte durchsuchen mit Filtern |
| 🛒 **Warenkorb** | Anzeigen, hinzufügen, entfernen |
| 📦 **Lieferung** | Lieferzeitfenster, Slots, Lieferinfos |
| 📋 **Bestellungen** | Bestellhistorie und Details |
| 👤 **Account** | Account-Info, Premium-Status |
| 🍽️ **Mahlzeiten** | Mahlzeitvorschläge nach Kategorie |
| ⚡ **JSON Output** | Maschinenlesbare Ausgabe für Scripting |
| 📦 **Zero Deps** | Nur Python Standard Library, keine Dependencies |
| 🤖 **AI-Agent Friendly** | Perfekt für Claude, Codex, OpenClaw & andere AI Assistenten |

### Works great with AI Agents

Der CLI-Ansatz macht knuspr-cli ideal für AI Coding Assistenten wie **Claude Code**, **Codex**, oder **OpenClaw**. Text-basierte, strukturierte Befehle und parsierbare Ausgabe ermöglichen es AI Agents, deinen Einkauf einfach zu verwalten.

---

## 🎬 Demo

### Login

```
$ knuspr login

╔═══════════════════════════════════════════════════════════╗
║  🛒 KNUSPR LOGIN                                          ║
╚═══════════════════════════════════════════════════════════╝

📧 E-Mail: user@example.com
🔑 Passwort: ********

  → Verbinde mit Knuspr.de...
  → Authentifizierung erfolgreich...
  → Speichere Session...

✅ Eingeloggt als Max Mustermann (user@example.com)
   User ID: 123456
```

### Produkte suchen

```
$ knuspr search "Champignons" -n 3

🔍 Suche in Knuspr: 'Champignons'
──────────────────────────────────────────────────
Gefunden: 3 Produkte

   1. Bio Champignons braun (REWE Bio)
      💰 2.49 EUR  │  📦 250g  │  ✅
      ID: 1234567

   2. Champignons weiß (Knuspr)
      💰 1.99 EUR  │  📦 400g  │  ✅
      ID: 1234568

   3. Mini Champignons (Gut Bio)
      💰 2.79 EUR  │  📦 200g  │  ✅
      ID: 1234569
```

### Warenkorb anzeigen

```
$ knuspr cart show

╔═══════════════════════════════════════════════════════════╗
║  🛒 WARENKORB                                              ║
╚═══════════════════════════════════════════════════════════╝

📦 Produkte (3):

   • Bio Champignons braun
     2× 2.49 € = 4.98 €
     [ID: 1234567]

   • Vollmilch 3.5%
     1× 1.29 € = 1.29 €
     [ID: 1234570]

────────────────────────────────────────────────────────────
   💰 Gesamt: 6.27 EUR
   ✅ Bestellbereit
```

---

## 📦 Installation

### Option 1: uvx (empfohlen)

```bash
# Direkt ausführen — keine Installation nötig
uvx --from git+https://github.com/Lars147/knuspr-cli knuspr --help

# Oder global installieren
uv tool install git+https://github.com/Lars147/knuspr-cli
knuspr --help

# Update auf neueste Version
uv tool install --upgrade git+https://github.com/Lars147/knuspr-cli
```

### Option 2: pipx

```bash
pipx install git+https://github.com/Lars147/knuspr-cli
knuspr --help

# Update
pipx install --force git+https://github.com/Lars147/knuspr-cli
```

### Option 3: Clone the repo

```bash
git clone https://github.com/Lars147/knuspr-cli.git
cd knuspr-cli
python3 knuspr_cli.py --help
```

---

## 📖 Usage

### 🎯 Setup & Konfiguration

```bash
knuspr setup                     # Interaktives Onboarding
                                 # → Bio-Präferenz (ja/nein/egal)
                                 # → Standard-Sortierung (Preis/Relevanz/etc.)
                                 # → Ausschlüsse (z.B. Laktose, Gluten)
                                 # Suchen nutzen danach automatisch diese Präferenzen!
```

### 🔐 Authentication

```bash
knuspr login                                    # Interaktives Login
knuspr login --email user@example.com --password secret  # Mit Credentials
knuspr status                                   # Login-Status prüfen
knuspr logout                                   # Ausloggen
```

### 🔍 Suche

```bash
knuspr search "Milch"                   # Einfache Suche
knuspr search "Käse" -n 20              # Mehr Ergebnisse
knuspr search "Brot" --favorites        # Nur Favoriten
knuspr search "Obst" --json             # JSON Output
```

### 🛒 Warenkorb

```bash
knuspr cart show                        # Warenkorb anzeigen
knuspr cart show --json                 # Als JSON
knuspr cart add 123456                  # Produkt hinzufügen
knuspr cart add 123456 -q 3             # 3 Stück hinzufügen
knuspr cart remove 123456               # Produkt entfernen
knuspr cart open                        # Im Browser öffnen
```

### 📦 Lieferung

```bash
knuspr slots                            # Verfügbare Lieferzeitfenster
knuspr slots --detailed                 # Mit 15-Minuten Slots
knuspr delivery                         # Aktuelle Lieferinfos
```

### 📋 Bestellungen

```bash
knuspr orders                           # Bestellhistorie anzeigen
knuspr order 12345678                   # Bestelldetails für ID
```

### 👤 Account

```bash
knuspr account                          # Account-Info, Premium-Status
knuspr frequent                         # Häufig gekaufte Produkte
```

### 🍽️ Mahlzeiten & Vorschläge

```bash
knuspr meals breakfast                  # Frühstücks-Vorschläge
knuspr meals lunch                      # Mittagessen-Ideen
knuspr meals dinner                     # Abendessen-Vorschläge
knuspr meals snack                      # Snack-Ideen
```

---

## ⚙️ Configuration

Credentials können auf verschiedene Weisen bereitgestellt werden (in dieser Reihenfolge geprüft):

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

### 4. Secrets File

Erstelle `~/.openclaw/workspace/secrets/knuspr.env`:
```bash
KNUSPR_EMAIL="user@example.com"
KNUSPR_PASSWORD="secret"
```

### 5. Credentials File

Erstelle `~/.knuspr_credentials.json`:
```json
{
  "email": "user@example.com",
  "password": "secret"
}
```

---

## 🔧 How It Works

| Component | Technology |
|-----------|------------|
| Authentication | Knuspr/Rohlik REST API |
| Search | Knuspr Search API |
| Cart | Knuspr Cart API |
| Storage | Local JSON session file |

### Files

```
~/
├── .knuspr_session.json       # Session cookies
└── .knuspr_credentials.json   # Optional: gespeicherte Credentials
```

---

## 🤝 Contributing

Contributions are welcome!

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/awesome`)
3. Commit your changes (`git commit -m 'Add awesome feature'`)
4. Push to the branch (`git push origin feature/awesome`)
5. Open a Pull Request

### Ideas & TODOs

- [ ] Favorites management
- [x] ~~Order history~~ ✅
- [x] ~~Delivery slots~~ ✅
- [ ] Shopping list import from tmx-cli

---

## ⚠️ Disclaimer

This is an **unofficial** tool. Knuspr® is a trademark of Rohlik Group.

This project is not affiliated with, endorsed, or sponsored by Rohlik/Knuspr. Please respect their terms of service.

---

## 📄 License

MIT © [Lars Heinen](https://github.com/Lars147)

---

<p align="center">
  <sub>Made with ❤️ for people who prefer terminals over browsers</sub>
</p>
