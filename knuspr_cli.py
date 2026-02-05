#!/usr/bin/env python3
"""Knuspr CLI - Einkaufen bei Knuspr.de vom Terminal aus.

Rein Python, keine externen Dependencies (nur stdlib).

Nutzung:
    python3 knuspr_cli.py login                 # Einloggen
    python3 knuspr_cli.py search "Milch"        # Produkte suchen
    python3 knuspr_cli.py cart show             # Warenkorb anzeigen
    python3 knuspr_cli.py cart add 123456       # Produkt hinzufügen
"""

import argparse
import getpass
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Optional


# Configuration
BASE_URL = "https://www.knuspr.de"
SESSION_FILE = Path.home() / ".knuspr_session.json"
CREDENTIALS_FILE = Path.home() / ".knuspr_credentials.json"

# Also check workspace secrets
WORKSPACE_CREDENTIALS = Path(__file__).parent.parent / "secrets" / "knuspr.env"


class KnusprAPIError(Exception):
    """Custom exception for Knuspr API errors."""
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class KnusprAPI:
    """Knuspr.de API client using only Python stdlib."""
    
    def __init__(self):
        self.cookies: dict[str, str] = {}
        self.user_id: Optional[int] = None
        self.address_id: Optional[int] = None
        self._load_session()
    
    def _get_headers(self) -> dict[str, str]:
        """Get default HTTP headers."""
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Referer": BASE_URL,
            "Origin": BASE_URL,
            "sec-ch-ua": '"Google Chrome";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }
        
        if self.cookies:
            cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
            headers["Cookie"] = cookie_str
        
        return headers
    
    def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        data: Optional[dict] = None
    ) -> dict[str, Any]:
        """Make HTTP request to Knuspr API."""
        url = f"{BASE_URL}{endpoint}"
        headers = self._get_headers()
        
        body = None
        if data:
            body = json.dumps(data).encode("utf-8")
        
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                # Parse Set-Cookie headers
                for header in response.headers.get_all("Set-Cookie") or []:
                    self._parse_cookie(header)
                
                content = response.read().decode("utf-8")
                if content:
                    return json.loads(content)
                return {}
        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")
            except:
                pass
            raise KnusprAPIError(f"HTTP {e.code}: {e.reason}. {error_body}", e.code)
        except urllib.error.URLError as e:
            raise KnusprAPIError(f"Connection error: {e.reason}")
    
    def _parse_cookie(self, cookie_header: str) -> None:
        """Parse Set-Cookie header and store cookies."""
        parts = cookie_header.split(";")
        if parts:
            cookie_part = parts[0].strip()
            if "=" in cookie_part:
                name, value = cookie_part.split("=", 1)
                self.cookies[name.strip()] = value.strip()
    
    def _save_session(self) -> None:
        """Save session cookies to file."""
        session_data = {
            "cookies": self.cookies,
            "user_id": self.user_id,
            "address_id": self.address_id,
        }
        with open(SESSION_FILE, "w") as f:
            json.dump(session_data, f)
    
    def _load_session(self) -> None:
        """Load session cookies from file."""
        if SESSION_FILE.exists():
            try:
                with open(SESSION_FILE) as f:
                    data = json.load(f)
                    self.cookies = data.get("cookies", {})
                    self.user_id = data.get("user_id")
                    self.address_id = data.get("address_id")
            except (json.JSONDecodeError, IOError):
                pass
    
    def _clear_session(self) -> None:
        """Clear session data."""
        self.cookies = {}
        self.user_id = None
        self.address_id = None
        if SESSION_FILE.exists():
            SESSION_FILE.unlink()
    
    def is_logged_in(self) -> bool:
        """Check if we have a valid session."""
        return bool(self.cookies and self.user_id)
    
    def login(self, email: str, password: str) -> dict[str, Any]:
        """Login to Knuspr.de."""
        login_data = {
            "email": email,
            "password": password,
            "name": ""
        }
        
        response = self._make_request(
            "/services/frontend-service/login",
            method="POST",
            data=login_data
        )
        
        # Check response
        status = response.get("status", 200)
        if status not in (200, 202, None):
            messages = response.get("messages", [])
            error_msg = messages[0].get("content") if messages else "Login failed"
            raise KnusprAPIError(f"Login failed: {error_msg}", status)
        
        # Extract user data
        data = response.get("data", {})
        user = data.get("user", {})
        
        if not user.get("id"):
            raise KnusprAPIError("Login succeeded but no user data received")
        
        self.user_id = user["id"]
        self.address_id = data.get("address", {}).get("id")
        
        self._save_session()
        
        return {
            "user_id": self.user_id,
            "email": user.get("email"),
            "name": f"{user.get('name', '')} {user.get('surname', '')}".strip(),
            "address_id": self.address_id,
        }
    
    def logout(self) -> None:
        """Logout from Knuspr.de."""
        try:
            self._make_request("/services/frontend-service/logout", method="POST")
        except KnusprAPIError:
            pass  # Ignore logout errors
        finally:
            self._clear_session()
    
    def search_products(
        self,
        query: str,
        limit: int = 10,
        favorites_only: bool = False
    ) -> list[dict[str, Any]]:
        """Search for products."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        params = urllib.parse.urlencode({
            "search": query,
            "offset": "0",
            "limit": str(limit + 5),  # Request extra to filter sponsored
            "companyId": "1",
            "filterData": json.dumps({"filters": []}),
            "canCorrect": "true"
        })
        
        response = self._make_request(f"/services/frontend-service/search-metadata?{params}")
        
        products = response.get("data", {}).get("productList", [])
        
        # Filter out sponsored products
        products = [
            p for p in products
            if not any(
                badge.get("slug") == "promoted"
                for badge in p.get("badge", [])
            )
        ]
        
        # Filter favorites if requested
        if favorites_only:
            products = [p for p in products if p.get("favourite")]
        
        # Limit results
        products = products[:limit]
        
        # Format results
        results = []
        for p in products:
            price_info = p.get("price", {})
            results.append({
                "id": p.get("productId"),
                "name": p.get("productName"),
                "price": price_info.get("full"),
                "currency": price_info.get("currency", "EUR"),
                "unit_price": price_info.get("unitPrice"),
                "brand": p.get("brand"),
                "amount": p.get("textualAmount"),
                "in_stock": p.get("inStock", True),
                "image": p.get("image"),
            })
        
        return results
    
    def get_cart(self) -> dict[str, Any]:
        """Get cart contents."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        response = self._make_request("/services/frontend-service/v2/cart")
        data = response.get("data", {})
        
        items = data.get("items", {})
        products = []
        
        for product_id, item in items.items():
            products.append({
                "id": product_id,
                "order_field_id": item.get("orderFieldId"),
                "name": item.get("productName"),
                "quantity": item.get("quantity", 0),
                "price": item.get("price", 0),
                "total_price": item.get("totalPrice", 0),
                "category": item.get("primaryCategoryName"),
                "brand": item.get("brand"),
                "image": item.get("image"),
            })
        
        return {
            "total_price": data.get("totalPrice", 0),
            "currency": "EUR",
            "item_count": len(products),
            "can_order": data.get("submitConditionPassed", False),
            "min_order_price": data.get("minOrderPrice"),
            "products": products,
        }
    
    def add_to_cart(self, product_id: int, quantity: int = 1) -> bool:
        """Add product to cart."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        payload = {
            "actionId": None,
            "productId": product_id,
            "quantity": quantity,
            "recipeId": None,
            "source": "true:Search"
        }
        
        self._make_request(
            "/services/frontend-service/v2/cart",
            method="POST",
            data=payload
        )
        return True
    
    def remove_from_cart(self, order_field_id: str) -> bool:
        """Remove product from cart using order_field_id."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        self._make_request(
            f"/services/frontend-service/v2/cart?orderFieldId={order_field_id}",
            method="DELETE"
        )
        return True
    
    def update_cart_quantity(self, order_field_id: str, quantity: int) -> bool:
        """Update quantity of a cart item."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        payload = {
            "orderFieldId": order_field_id,
            "quantity": quantity,
        }
        
        self._make_request(
            "/services/frontend-service/v2/cart",
            method="PUT",
            data=payload
        )
        return True


def load_credentials() -> tuple[Optional[str], Optional[str]]:
    """Load credentials from file or environment (returns None if not found)."""
    email = None
    password = None
    
    # 1. Check environment variables
    email = os.environ.get("KNUSPR_EMAIL")
    password = os.environ.get("KNUSPR_PASSWORD")
    if email and password:
        return email, password
    
    # 2. Check workspace secrets (knuspr.env)
    if WORKSPACE_CREDENTIALS.exists():
        with open(WORKSPACE_CREDENTIALS) as f:
            for line in f:
                line = line.strip()
                if line.startswith("KNUSPR_EMAIL="):
                    email = line.split("=", 1)[1].strip().strip('"\'')
                elif line.startswith("KNUSPR_PASSWORD="):
                    password = line.split("=", 1)[1].strip().strip('"\'')
        if email and password:
            return email, password
    
    # 3. Check ~/.knuspr_credentials.json
    if CREDENTIALS_FILE.exists():
        try:
            with open(CREDENTIALS_FILE) as f:
                data = json.load(f)
                email = data.get("email")
                password = data.get("password")
                if email and password:
                    return email, password
        except (json.JSONDecodeError, IOError):
            pass
    
    return None, None


def cmd_login(args: argparse.Namespace) -> int:
    """Handle login command."""
    api = KnusprAPI()
    
    # Check if already logged in
    if api.is_logged_in():
        print()
        print("✅ Bereits eingeloggt!")
        print(f"   User ID: {api.user_id}")
        print()
        print("   Zum erneuten Einloggen erst 'knuspr logout' ausführen.")
        print()
        return 0
    
    print()
    print("╔═══════════════════════════════════════════════════════════╗")
    print("║  🛒 KNUSPR LOGIN                                          ║")
    print("╚═══════════════════════════════════════════════════════════╝")
    print()
    
    # Try to load credentials from files first
    email, password = load_credentials()
    
    # If command-line args provided, use them
    if getattr(args, 'email', None):
        email = args.email
    if getattr(args, 'password', None):
        password = args.password
    
    # Interactive prompts for missing credentials
    if not email:
        email = input("📧 E-Mail: ").strip()
    else:
        print(f"📧 E-Mail: {email}")
    
    if not password:
        password = getpass.getpass("🔑 Passwort: ")
    else:
        print("🔑 Passwort: ********")
    
    if not email or not password:
        print()
        print("❌ E-Mail und Passwort werden benötigt!")
        return 1
    
    print()
    print("  → Verbinde mit Knuspr.de...")
    
    try:
        result = api.login(email, password)
        print("  → Authentifizierung erfolgreich...")
        print("  → Speichere Session...")
        print()
        print(f"✅ Eingeloggt als {result['name']} ({result['email']})")
        print(f"   User ID: {result['user_id']}")
        if result['address_id']:
            print(f"   Adresse ID: {result['address_id']}")
        print()
        return 0
    except KnusprAPIError as e:
        print()
        print(f"❌ Login fehlgeschlagen: {e}")
        print()
        return 1


def cmd_logout(args: argparse.Namespace) -> int:
    """Handle logout command."""
    api = KnusprAPI()
    
    if not api.is_logged_in():
        print()
        print("ℹ️  Nicht eingeloggt.")
        print()
        return 0
    
    api.logout()
    print()
    print("✅ Ausgeloggt und Session gelöscht.")
    print()
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    """Handle search command."""
    api = KnusprAPI()
    
    if not api.is_logged_in():
        if args.json:
            print(json.dumps({"error": "Nicht eingeloggt"}, indent=2))
        else:
            print()
            print("❌ Nicht eingeloggt. Führe 'knuspr login' aus.")
            print()
        return 1
    
    try:
        if not args.json:
            print()
            print(f"🔍 Suche in Knuspr: '{args.query}'")
            print("─" * 50)
        
        results = api.search_products(
            args.query,
            limit=args.limit,
            favorites_only=args.favorites
        )
        
        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            if not results:
                print(f"Keine Produkte gefunden für '{args.query}'")
                print()
                return 0
            
            print(f"Gefunden: {len(results)} Produkte")
            print()
            
            for i, p in enumerate(results, 1):
                stock = "✅" if p["in_stock"] else "❌"
                brand = f" ({p['brand']})" if p['brand'] else ""
                print(f"  {i:2}. {p['name']}{brand}")
                print(f"      💰 {p['price']} {p['currency']}  │  📦 {p['amount']}  │  {stock}")
                print(f"      ID: {p['id']}")
                print()
        
        return 0
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return 1


def cmd_cart_show(args: argparse.Namespace) -> int:
    """Handle cart show command."""
    api = KnusprAPI()
    
    if not api.is_logged_in():
        if args.json:
            print(json.dumps({"error": "Nicht eingeloggt"}, indent=2))
        else:
            print()
            print("❌ Nicht eingeloggt. Führe 'knuspr login' aus.")
            print()
        return 1
    
    try:
        cart = api.get_cart()
        
        if args.json:
            print(json.dumps(cart, indent=2, ensure_ascii=False))
        else:
            print()
            print("╔═══════════════════════════════════════════════════════════╗")
            print("║  🛒 WARENKORB                                              ║")
            print("╚═══════════════════════════════════════════════════════════╝")
            print()
            
            if not cart["products"]:
                print("   (leer)")
                print()
                return 0
            
            print(f"📦 Produkte ({cart['item_count']}):")
            print()
            
            for p in cart["products"]:
                print(f"   • {p['name']}")
                print(f"     {p['quantity']}× {p['price']:.2f} € = {p['total_price']:.2f} €")
                print(f"     [ID: {p['id']}]")
                print()
            
            print("─" * 60)
            print(f"   💰 Gesamt: {cart['total_price']:.2f} {cart['currency']}")
            
            if cart['min_order_price'] and cart['total_price'] < cart['min_order_price']:
                remaining = cart['min_order_price'] - cart['total_price']
                print(f"   ⚠️  Mindestbestellwert: {cart['min_order_price']:.2f} € (noch {remaining:.2f} €)")
            
            if cart['can_order']:
                print("   ✅ Bestellbereit")
            else:
                print("   ❌ Noch nicht bestellbar")
            print()
        
        return 0
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return 1


def cmd_cart_add(args: argparse.Namespace) -> int:
    """Handle cart add command."""
    api = KnusprAPI()
    
    if not api.is_logged_in():
        print()
        print("❌ Nicht eingeloggt. Führe 'knuspr login' aus.")
        print()
        return 1
    
    try:
        print()
        print(f"  → Füge Produkt {args.product_id} hinzu...")
        api.add_to_cart(args.product_id, args.quantity)
        print()
        print(f"✅ Produkt hinzugefügt (ID: {args.product_id}, Menge: {args.quantity})")
        print()
        return 0
    except KnusprAPIError as e:
        print()
        print(f"❌ Fehler: {e}")
        print()
        return 1


def cmd_cart_remove(args: argparse.Namespace) -> int:
    """Handle cart remove command."""
    api = KnusprAPI()
    
    if not api.is_logged_in():
        print()
        print("❌ Nicht eingeloggt. Führe 'knuspr login' aus.")
        print()
        return 1
    
    try:
        print()
        print(f"  → Suche Produkt {args.product_id}...")
        cart = api.get_cart()
        
        # Find the product
        order_field_id = None
        product_name = None
        for p in cart["products"]:
            if str(p["id"]) == str(args.product_id):
                order_field_id = p["order_field_id"]
                product_name = p["name"]
                break
        
        if not order_field_id:
            # Maybe they passed the order_field_id directly
            order_field_id = args.product_id
        
        print(f"  → Entferne aus Warenkorb...")
        api.remove_from_cart(str(order_field_id))
        print()
        if product_name:
            print(f"✅ Entfernt: {product_name}")
        else:
            print(f"✅ Produkt entfernt")
        print()
        return 0
    except KnusprAPIError as e:
        print()
        print(f"❌ Fehler: {e}")
        print()
        return 1


def cmd_cart_open(args: argparse.Namespace) -> int:
    """Handle cart open command - opens cart in browser."""
    url = f"{BASE_URL}/obchod/kosik"
    print()
    print(f"  → Öffne {url}...")
    webbrowser.open(url)
    print()
    print("✅ Warenkorb im Browser geöffnet")
    print()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Handle status command."""
    api = KnusprAPI()
    
    print()
    print("╔═══════════════════════════════════════════════════════════╗")
    print("║  🛒 KNUSPR STATUS                                         ║")
    print("╚═══════════════════════════════════════════════════════════╝")
    print()
    
    if api.is_logged_in():
        print(f"✅ Eingeloggt")
        print(f"   User ID: {api.user_id}")
        if api.address_id:
            print(f"   Adresse ID: {api.address_id}")
        print(f"   Session: {SESSION_FILE}")
    else:
        print("❌ Nicht eingeloggt")
        print()
        print("   Führe 'knuspr login' aus um dich einzuloggen.")
    
    print()
    return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="knuspr",
        description="🛒 Knuspr.de im Terminal — Einkaufen, Suchen, Warenkorb verwalten"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # login command
    login_parser = subparsers.add_parser("login", help="Bei Knuspr.de einloggen")
    login_parser.add_argument("--email", "-e", help="E-Mail Adresse")
    login_parser.add_argument("--password", "-p", help="Passwort")
    login_parser.set_defaults(func=cmd_login)
    
    # logout command
    logout_parser = subparsers.add_parser("logout", help="Ausloggen und Session löschen")
    logout_parser.set_defaults(func=cmd_logout)
    
    # status command
    status_parser = subparsers.add_parser("status", help="Login-Status anzeigen")
    status_parser.set_defaults(func=cmd_status)
    
    # search command
    search_parser = subparsers.add_parser("search", help="Produkte suchen")
    search_parser.add_argument("query", help="Suchbegriff")
    search_parser.add_argument("-n", "--limit", type=int, default=10, help="Anzahl Ergebnisse (Standard: 10)")
    search_parser.add_argument("--favorites", action="store_true", help="Nur Favoriten anzeigen")
    search_parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    search_parser.set_defaults(func=cmd_search)
    
    # cart commands
    cart_parser = subparsers.add_parser("cart", help="Warenkorb-Operationen")
    cart_subparsers = cart_parser.add_subparsers(dest="cart_command", help="Warenkorb-Befehle")
    
    # cart show
    cart_show_parser = cart_subparsers.add_parser("show", help="Warenkorb anzeigen")
    cart_show_parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    cart_show_parser.set_defaults(func=cmd_cart_show)
    
    # cart add
    cart_add_parser = cart_subparsers.add_parser("add", help="Produkt hinzufügen")
    cart_add_parser.add_argument("product_id", type=int, help="Produkt-ID")
    cart_add_parser.add_argument("-q", "--quantity", type=int, default=1, help="Menge (Standard: 1)")
    cart_add_parser.set_defaults(func=cmd_cart_add)
    
    # cart remove
    cart_remove_parser = cart_subparsers.add_parser("remove", help="Produkt entfernen")
    cart_remove_parser.add_argument("product_id", help="Produkt-ID")
    cart_remove_parser.set_defaults(func=cmd_cart_remove)
    
    # cart open
    cart_open_parser = cart_subparsers.add_parser("open", help="Warenkorb im Browser öffnen")
    cart_open_parser.set_defaults(func=cmd_cart_open)
    
    # Parse and execute
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    if args.command == "cart" and not args.cart_command:
        cart_parser.print_help()
        return 0
    
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
