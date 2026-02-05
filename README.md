# Knuspr CLI

Command-line interface for [Knuspr.de](https://www.knuspr.de) online supermarket.

**Pure Python** - no external dependencies required (stdlib only).

## Installation

```bash
# Clone the repository
git clone https://github.com/Lars147/knuspr-cli.git
cd knuspr-cli

# Make executable
chmod +x knuspr_cli.py

# Optional: Create symlink
ln -s $(pwd)/knuspr_cli.py ~/.local/bin/knuspr
```

## Configuration

Create credentials in one of these locations (checked in order):

### 1. Environment Variables (recommended for CI/scripts)
```bash
export KNUSPR_EMAIL="your@email.com"
export KNUSPR_PASSWORD="your-password"
```

### 2. Secrets File (for workspace integration)
Create `~/.openclaw/workspace/secrets/knuspr.env`:
```bash
KNUSPR_EMAIL="your@email.com"
KNUSPR_PASSWORD="your-password"
```

### 3. Credentials File
Create `~/.knuspr_credentials.json`:
```json
{
  "email": "your@email.com",
  "password": "your-password"
}
```

## Usage

### Login
```bash
knuspr login                    # Login and save session
knuspr logout                   # Logout and clear session
knuspr status                   # Show login status
```

### Search Products
```bash
knuspr search "Champignons"              # Search for products
knuspr search "Milch" -n 5               # Limit to 5 results
knuspr search "Käse" --favorites         # Only favorites
knuspr search "Brot" --json              # JSON output (for scripts)
```

### Cart Operations
```bash
knuspr cart show                         # Show cart contents
knuspr cart show --json                  # JSON output
knuspr cart add 123456                   # Add product by ID
knuspr cart add 123456 -q 3              # Add 3 units
knuspr cart remove 123456                # Remove product
knuspr cart open                         # Open cart in browser
```

## JSON Output

Use `--json` flag for machine-readable output (for integration with other tools):

```bash
# Search and pipe to jq
knuspr search "Tomaten" --json | jq '.[] | select(.in_stock) | .name'

# Get cart total
knuspr cart show --json | jq '.total_price'
```

## Session Management

Sessions are stored in `~/.knuspr_session.json` and reused across commands.
Run `knuspr logout` to clear the session.

## Integration with tmx-cli

The `--json` flag enables integration with other tools like tmx-cli:

```bash
# Future: Import shopping list from Cookidoo
knuspr import shopping_list.json
```

## API Reference

Based on reverse-engineered Rohlik/Knuspr API. Key endpoints:
- Login: `POST /services/frontend-service/login`
- Search: `GET /services/frontend-service/search-metadata`
- Cart: `GET/POST/DELETE /services/frontend-service/v2/cart`

## License

MIT
