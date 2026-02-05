#!/usr/bin/env python3
"""Knuspr CLI - Einkaufen bei Knuspr.de vom Terminal aus.

Rein Python, keine externen Dependencies (nur stdlib).

Nutzung:
    python3 knuspr_cli.py login                 # Einloggen
    python3 knuspr_cli.py search "Milch"        # Produkte suchen
    python3 knuspr_cli.py cart show             # Warenkorb anzeigen
    python3 knuspr_cli.py cart add 123456       # Produkt hinzufügen
    python3 knuspr_cli.py slots                 # Lieferzeitfenster
    python3 knuspr_cli.py delivery              # Lieferinfo
    python3 knuspr_cli.py orders                # Bestellhistorie
    python3 knuspr_cli.py account               # Account-Info
    python3 knuspr_cli.py frequent              # Häufig gekaufte Produkte
    python3 knuspr_cli.py meals breakfast       # Mahlzeitvorschläge
"""

import argparse
import getpass
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


# Configuration
BASE_URL = "https://www.knuspr.de"
SESSION_FILE = Path.home() / ".knuspr_session.json"
CREDENTIALS_FILE = Path.home() / ".knuspr_credentials.json"

# Also check workspace secrets
WORKSPACE_CREDENTIALS = Path(__file__).parent.parent / "secrets" / "knuspr.env"

# Meal category mappings (German categories for Knuspr.de)
MEAL_CATEGORY_MAPPINGS = {
    "breakfast": [
        "Brot & Backwaren", "Milch", "Müsli", "Aufstriche", "Marmelade",
        "Obst", "Honig", "Butter", "Eier", "Käse", "Joghurt"
    ],
    "lunch": [
        "Fleisch", "Geflügel", "Gemüse", "Beilagen", "Nudeln",
        "Reis", "Soßen", "Suppen", "Hülsenfrüchte"
    ],
    "dinner": [
        "Fleisch", "Geflügel", "Fisch", "Meeresfrüchte", "Gemüse",
        "Beilagen", "Nudeln", "Reis", "Kartoffeln", "Soßen"
    ],
    "snack": [
        "Süßigkeiten", "Obst", "Nüsse", "Joghurt",
        "Käse", "Chips", "Riegel", "Kekse"
    ],
    "baking": [
        "Mehl", "Zucker", "Backzutaten", "Schokolade", "Kakao",
        "Nüsse", "Eier", "Butter", "Hefe"
    ],
    "drinks": [
        "Getränke", "Kaffee", "Tee", "Milch",
        "Säfte", "Wasser", "Bier", "Wein"
    ],
    "healthy": [
        "Bio", "Gesund", "Glutenfrei", "Vegan",
        "Obst", "Gemüse", "Nüsse", "Hülsenfrüchte"
    ]
}


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
        self._last_request_time: float = 0
        self._min_request_interval: float = 0.1  # 100ms between requests
        self._load_session()
    
    def _rate_limit(self) -> None:
        """Apply rate limiting between requests."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()
    
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
        self._rate_limit()
        
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
            quantity = item.get("quantity", 0)
            price = item.get("price", 0)
            # Calculate total ourselves - API's totalPrice can be unreliable
            item_total = item.get("totalPrice", 0) or (quantity * price)
            products.append({
                "id": product_id,
                "order_field_id": item.get("orderFieldId"),
                "name": item.get("productName"),
                "quantity": quantity,
                "price": price,
                "total_price": item_total,
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
    
    # ==================== NEW API METHODS ====================
    
    def get_delivery_info(self) -> dict[str, Any]:
        """Get delivery information."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        response = self._make_request(
            "/services/frontend-service/first-delivery?reasonableDeliveryTime=true"
        )
        return response.get("data", response)
    
    def get_upcoming_orders(self) -> list[dict[str, Any]]:
        """Get upcoming/pending orders."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        response = self._make_request("/api/v3/orders/upcoming")
        if isinstance(response, list):
            return response
        data = response.get("data", response) if isinstance(response, dict) else response
        return data if isinstance(data, list) else []
    
    def get_order_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get order history."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        response = self._make_request(f"/api/v3/orders/delivered?offset=0&limit={limit}")
        if isinstance(response, list):
            return response
        data = response.get("data", response) if isinstance(response, dict) else response
        return data if isinstance(data, list) else [data] if data else []
    
    def get_order_detail(self, order_id: str) -> dict[str, Any]:
        """Get details of a specific order."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        response = self._make_request(f"/api/v3/orders/{order_id}")
        if isinstance(response, dict):
            return response.get("data", response)
        return response
    
    def get_delivery_slots(self) -> list[dict[str, Any]]:
        """Get available delivery time slots."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        if not self.user_id or not self.address_id:
            raise KnusprAPIError("User ID or Address ID not available")
        
        response = self._make_request(
            f"/services/frontend-service/timeslots-api/0?userId={self.user_id}&addressId={self.address_id}&reasonableDeliveryTime=true"
        )
        if isinstance(response, list):
            return response
        data = response.get("data", response) if isinstance(response, dict) else response
        return data if isinstance(data, list) else [data] if data else []
    
    def get_premium_info(self) -> dict[str, Any]:
        """Get premium membership information."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        response = self._make_request("/services/frontend-service/premium/profile")
        if isinstance(response, dict):
            return response.get("data", response)
        return response if response else {}
    
    def get_reusable_bags_info(self) -> dict[str, Any]:
        """Get reusable bags information."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        response = self._make_request("/api/v1/reusable-bags/user-info")
        if isinstance(response, dict):
            return response.get("data", response)
        return response if response else {}
    
    def get_announcements(self) -> list[dict[str, Any]]:
        """Get announcements."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        response = self._make_request("/services/frontend-service/announcements/top")
        if isinstance(response, list):
            return response
        data = response.get("data", response) if isinstance(response, dict) else response
        return data if isinstance(data, list) else []


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


def format_price(price: float, currency: str = "€") -> str:
    """Format price for display."""
    if price is None:
        return "N/A"
    return f"{price:.2f} {currency}"


def format_date(date_str: str) -> str:
    """Format date string for display."""
    if not date_str:
        return "Unbekannt"
    try:
        # Try ISO format
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M")
    except:
        return date_str


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
    url = f"{BASE_URL}/bestellung/mein-warenkorb"
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


# ==================== NEW COMMANDS ====================

def cmd_delivery(args: argparse.Namespace) -> int:
    """Handle delivery command - show delivery info and upcoming orders."""
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
        delivery_info = None
        upcoming_orders = []
        
        try:
            delivery_info = api.get_delivery_info()
        except KnusprAPIError:
            pass
        
        try:
            upcoming_orders = api.get_upcoming_orders()
        except KnusprAPIError:
            pass
        
        result = {
            "delivery_info": delivery_info,
            "upcoming_orders": upcoming_orders
        }
        
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print()
            print("╔═══════════════════════════════════════════════════════════╗")
            print("║  🚚 LIEFERINFORMATIONEN                                    ║")
            print("╚═══════════════════════════════════════════════════════════╝")
            print()
            
            if delivery_info:
                fee = delivery_info.get("deliveryFee") or delivery_info.get("fee") or 0
                free_from = delivery_info.get("freeDeliveryFrom") or delivery_info.get("freeFrom") or 0
                print(f"   💰 Liefergebühr: {format_price(fee)}")
                print(f"   🆓 Kostenlos ab: {format_price(free_from)}")
                print()
            
            if upcoming_orders:
                print(f"📦 Bevorstehende Bestellungen ({len(upcoming_orders)}):")
                print()
                for order in upcoming_orders:
                    order_id = order.get("id") or order.get("orderNumber")
                    date = order.get("deliveryDate") or order.get("estimatedDelivery") or "Unbekannt"
                    status = order.get("status") or "Unbekannt"
                    print(f"   • Bestellung #{order_id}")
                    print(f"     📅 {format_date(date)} | Status: {status}")
                    print()
            else:
                print("   ℹ️  Keine bevorstehenden Bestellungen.")
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


def cmd_slots(args: argparse.Namespace) -> int:
    """Handle slots command - show available delivery time slots."""
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
        slots = api.get_delivery_slots()
        
        if args.json:
            print(json.dumps(slots, indent=2, ensure_ascii=False))
        else:
            print()
            print("╔═══════════════════════════════════════════════════════════╗")
            print("║  📅 LIEFERZEITFENSTER                                      ║")
            print("╚═══════════════════════════════════════════════════════════╝")
            print()
            
            if not slots:
                print("   ℹ️  Keine Lieferzeitfenster verfügbar.")
                print()
                return 0
            
            # Group slots by date if possible
            displayed = 0
            for slot in slots[:20]:  # Limit to 20 slots
                date = slot.get("date") or slot.get("deliveryDate") or "Unbekannt"
                time_slot = slot.get("time") or slot.get("timeSlot") or f"{slot.get('from', '')} - {slot.get('to', '')}"
                price = slot.get("price") or slot.get("fee") or 0
                available = slot.get("available", True) != False
                
                status = "✅ Verfügbar" if available else "❌ Belegt"
                
                print(f"   📅 {format_date(date)}")
                print(f"      🕐 {time_slot}")
                print(f"      💰 {format_price(price)} | {status}")
                print()
                displayed += 1
            
            if len(slots) > 20:
                print(f"   ... und {len(slots) - 20} weitere Zeitfenster")
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


def cmd_orders(args: argparse.Namespace) -> int:
    """Handle orders command - show order history."""
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
        orders = api.get_order_history(limit=args.limit)
        
        if args.json:
            print(json.dumps(orders, indent=2, ensure_ascii=False))
        else:
            print()
            print("╔═══════════════════════════════════════════════════════════╗")
            print("║  📋 BESTELLHISTORIE                                        ║")
            print("╚═══════════════════════════════════════════════════════════╝")
            print()
            
            if not orders:
                print("   ℹ️  Keine Bestellungen gefunden.")
                print()
                return 0
            
            print(f"   Gefunden: {len(orders)} Bestellungen")
            print()
            
            for order in orders:
                order_id = order.get("id") or order.get("orderNumber")
                date = order.get("orderTime") or order.get("deliveredAt") or order.get("createdAt") or ""
                
                # Get price from various possible locations
                price_comp = order.get("priceComposition", {})
                price = price_comp.get("total") or order.get("totalPrice") or order.get("price") or 0
                
                items_count = order.get("itemsCount") or 0
                
                print(f"   📦 Bestellung #{order_id}")
                print(f"      📅 {format_date(date)}")
                print(f"      🛒 {items_count} Artikel | 💰 {format_price(price)}")
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


def cmd_order_detail(args: argparse.Namespace) -> int:
    """Handle order detail command - show details of a specific order."""
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
        order = api.get_order_detail(args.order_id)
        
        if args.json:
            print(json.dumps(order, indent=2, ensure_ascii=False))
        else:
            print()
            print("╔═══════════════════════════════════════════════════════════╗")
            print(f"║  📦 BESTELLUNG #{args.order_id}                            ")
            print("╚═══════════════════════════════════════════════════════════╝")
            print()
            
            if not order:
                print(f"   ℹ️  Bestellung {args.order_id} nicht gefunden.")
                print()
                return 0
            
            status = order.get("status") or "Unbekannt"
            date = order.get("deliveredAt") or order.get("createdAt") or ""
            total_price = order.get("totalPrice") or order.get("price") or 0
            
            print(f"   📊 Status: {status}")
            print(f"   📅 Datum: {format_date(date)}")
            print(f"   💰 Gesamt: {format_price(total_price)}")
            print()
            
            products = order.get("products") or order.get("items") or []
            if products:
                print(f"   🛒 Produkte ({len(products)}):")
                print()
                for p in products:
                    name = p.get("productName") or p.get("name") or "Unbekannt"
                    qty = p.get("quantity") or 1
                    price = p.get("price") or p.get("totalPrice") or 0
                    print(f"      • {name}")
                    print(f"        {qty}× | {format_price(price)}")
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


def cmd_account(args: argparse.Namespace) -> int:
    """Handle account command - show account information."""
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
        premium = None
        bags = None
        announcements = None
        
        try:
            premium = api.get_premium_info()
        except KnusprAPIError:
            pass
        
        try:
            bags = api.get_reusable_bags_info()
        except KnusprAPIError:
            pass
        
        try:
            announcements = api.get_announcements()
        except KnusprAPIError:
            pass
        
        result = {
            "premium": premium,
            "bags": bags,
            "announcements": announcements
        }
        
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print()
            print("╔═══════════════════════════════════════════════════════════╗")
            print("║  👤 ACCOUNT INFORMATION                                    ║")
            print("╚═══════════════════════════════════════════════════════════╝")
            print()
            
            # Premium Info
            if premium:
                is_premium = premium.get("stats", {}).get("orderCount") is not None or premium.get("premiumLimits") is not None
                savings = premium.get("savings", {}).get("total", {}).get("amount", {})
                saved_total = savings.get("amount") or premium.get("stats", {}).get("savedTotal", {}).get("full") or 0
                
                print(f"   ⭐ Premium Status: {'✅ Aktiv' if is_premium else '❌ Inaktiv'}")
                
                if is_premium and saved_total > 0:
                    currency = savings.get("currency", "€")
                    print(f"   💰 Gespart: {format_price(saved_total, currency)}")
                
                limits = premium.get("premiumLimits", {}).get("ordersWithoutPriceLimit", {})
                if limits:
                    remaining = limits.get("remaining", 0)
                    total = limits.get("total", 0)
                    print(f"   📦 Bestellungen ohne Mindestbestellwert: {remaining}/{total}")
                print()
            
            # Reusable Bags
            if bags:
                count = bags.get("count") or bags.get("bagsCount") or 0
                saved_plastic = bags.get("savedPlastic") or bags.get("plasticSaved") or 0
                
                print(f"   ♻️  Mehrwegtaschen: {count}")
                if saved_plastic > 0:
                    print(f"   🌱 Plastik gespart: {saved_plastic}g")
                print()
            
            # Announcements
            if announcements and len(announcements) > 0:
                print(f"   📢 Ankündigungen ({len(announcements)}):")
                print()
                for ann in announcements[:5]:
                    title = ann.get("title") or ann.get("headline") or "Ankündigung"
                    message = ann.get("message") or ann.get("content") or ""
                    print(f"      • {title}")
                    if message:
                        # Truncate long messages
                        if len(message) > 80:
                            message = message[:80] + "..."
                        print(f"        {message}")
                    print()
            else:
                print("   📢 Keine Ankündigungen.")
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


def cmd_frequent(args: argparse.Namespace) -> int:
    """Handle frequent command - show frequently purchased items."""
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
        orders_to_analyze = min(20, max(1, args.orders))
        top_items = min(30, max(3, args.top))
        
        if not args.json:
            print()
            print("╔═══════════════════════════════════════════════════════════╗")
            print("║  ⭐ HÄUFIG GEKAUFTE PRODUKTE                               ║")
            print("╚═══════════════════════════════════════════════════════════╝")
            print()
            print(f"   → Analysiere {orders_to_analyze} Bestellungen...")
        
        order_history = api.get_order_history(limit=orders_to_analyze)
        
        if not order_history:
            if args.json:
                print(json.dumps({"error": "Keine Bestellhistorie gefunden"}, indent=2))
            else:
                print()
                print("   ℹ️  Keine Bestellhistorie gefunden.")
                print()
            return 0
        
        # Analyze products
        product_map = {}
        processed_orders = 0
        total_products = 0
        
        for order in order_history:
            try:
                order_id = order.get("id") or order.get("orderNumber")
                if not order_id:
                    continue
                
                if not args.json:
                    print(f"   → Lade Bestellung #{order_id}...")
                
                order_detail = api.get_order_detail(str(order_id))
                if not order_detail:
                    continue
                
                processed_orders += 1
                products = order_detail.get("products") or order_detail.get("items") or []
                order_date = order_detail.get("deliveredAt") or order_detail.get("createdAt")
                
                for product in products:
                    product_id = product.get("productId") or product.get("id")
                    product_name = product.get("productName") or product.get("name")
                    
                    if not product_id or not product_name:
                        continue
                    
                    total_products += 1
                    key = str(product_id)
                    
                    # Get category
                    categories = product.get("categories") or []
                    main_category = None
                    for cat in categories:
                        if cat.get("level") == 1:
                            main_category = cat
                            break
                    if not main_category and categories:
                        main_category = categories[0]
                    
                    category_name = main_category.get("name", "Unkategorisiert") if main_category else "Unkategorisiert"
                    category_id = main_category.get("id", 0) if main_category else 0
                    
                    if key in product_map:
                        existing = product_map[key]
                        existing["frequency"] += 1
                        existing["total_quantity"] += (product.get("quantity") or 1)
                        
                        if product.get("price"):
                            current_avg = existing.get("average_price") or 0
                            existing["average_price"] = (current_avg * (existing["frequency"] - 1) + product["price"]) / existing["frequency"]
                        
                        if order_date and (not existing.get("last_order_date") or order_date > existing["last_order_date"]):
                            existing["last_order_date"] = order_date
                    else:
                        product_map[key] = {
                            "product_id": str(product_id),
                            "product_name": product_name,
                            "brand": product.get("brand") or "",
                            "frequency": 1,
                            "total_quantity": product.get("quantity") or 1,
                            "last_order_date": order_date,
                            "average_price": product.get("price") or 0,
                            "category": category_name,
                            "category_id": category_id
                        }
            except:
                continue
        
        # Sort by frequency
        sorted_products = sorted(product_map.values(), key=lambda x: x["frequency"], reverse=True)[:top_items]
        
        result = {
            "analyzed_orders": processed_orders,
            "total_products": total_products,
            "top_items": sorted_products
        }
        
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print()
            print(f"   📊 Analysiert: {processed_orders} Bestellungen | {total_products} Produkte")
            print()
            
            if not sorted_products:
                print("   ℹ️  Keine Produkte gefunden.")
                print()
                return 0
            
            print(f"   🏆 Top {len(sorted_products)} Produkte:")
            print()
            
            for i, item in enumerate(sorted_products, 1):
                brand = f" ({item['brand']})" if item['brand'] else ""
                avg_price = format_price(item['average_price']) if item['average_price'] else "N/A"
                last_order = format_date(item['last_order_date']) if item['last_order_date'] else "N/A"
                
                print(f"   {i:2}. {item['product_name']}{brand}")
                print(f"       📦 {item['frequency']}× bestellt | {item['total_quantity']} Stück | ⌀ {avg_price}")
                print(f"       📅 Zuletzt: {last_order}")
                print(f"       ID: {item['product_id']}")
                print()
            
            # Show categories breakdown if requested
            if args.categories:
                print("─" * 60)
                print()
                print("   📂 Nach Kategorie:")
                print()
                
                # Group by category
                category_map = {}
                for product in product_map.values():
                    cat_id = product["category_id"]
                    if cat_id not in category_map:
                        category_map[cat_id] = {"name": product["category"], "products": []}
                    category_map[cat_id]["products"].append(product)
                
                # Sort categories by total frequency
                sorted_categories = sorted(
                    category_map.values(),
                    key=lambda x: sum(p["frequency"] for p in x["products"]),
                    reverse=True
                )
                
                for category in sorted_categories[:10]:
                    print(f"   {category['name'].upper()}")
                    top_cat_products = sorted(category["products"], key=lambda x: x["frequency"], reverse=True)[:3]
                    for p in top_cat_products:
                        print(f"      • {p['product_name']} ({p['frequency']}×)")
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


def cmd_meals(args: argparse.Namespace) -> int:
    """Handle meals command - get meal suggestions based on purchase history."""
    api = KnusprAPI()
    
    meal_type = args.meal_type.lower()
    valid_types = list(MEAL_CATEGORY_MAPPINGS.keys())
    
    if meal_type not in valid_types:
        if args.json:
            print(json.dumps({"error": f"Ungültiger Mahlzeittyp: {meal_type}. Gültig: {', '.join(valid_types)}"}, indent=2))
        else:
            print()
            print(f"❌ Ungültiger Mahlzeittyp: {meal_type}")
            print(f"   Gültige Typen: {', '.join(valid_types)}")
            print()
        return 1
    
    if not api.is_logged_in():
        if args.json:
            print(json.dumps({"error": "Nicht eingeloggt"}, indent=2))
        else:
            print()
            print("❌ Nicht eingeloggt. Führe 'knuspr login' aus.")
            print()
        return 1
    
    try:
        items_count = min(30, max(3, args.count))
        orders_to_analyze = min(20, max(1, args.orders))
        relevant_categories = MEAL_CATEGORY_MAPPINGS[meal_type]
        
        meal_names = {
            "breakfast": "Frühstück",
            "lunch": "Mittagessen",
            "dinner": "Abendessen",
            "snack": "Snacks",
            "baking": "Backen",
            "drinks": "Getränke",
            "healthy": "Gesund"
        }
        meal_name = meal_names.get(meal_type, meal_type.capitalize())
        
        if not args.json:
            print()
            print("╔═══════════════════════════════════════════════════════════╗")
            print(f"║  🍽️  {meal_name.upper()}-VORSCHLÄGE                              ")
            print("╚═══════════════════════════════════════════════════════════╝")
            print()
            print(f"   → Analysiere {orders_to_analyze} Bestellungen...")
        
        order_history = api.get_order_history(limit=orders_to_analyze)
        
        if not order_history:
            if args.json:
                print(json.dumps({"error": "Keine Bestellhistorie gefunden"}, indent=2))
            else:
                print()
                print("   ℹ️  Keine Bestellhistorie gefunden.")
                print()
            return 0
        
        # Analyze products
        product_map = {}
        processed_orders = 0
        
        for order in order_history:
            try:
                order_id = order.get("id") or order.get("orderNumber")
                if not order_id:
                    continue
                
                if not args.json:
                    print(f"   → Lade Bestellung #{order_id}...")
                
                order_detail = api.get_order_detail(str(order_id))
                if not order_detail:
                    continue
                
                processed_orders += 1
                products = order_detail.get("products") or order_detail.get("items") or []
                
                for product in products:
                    product_id = product.get("productId") or product.get("id")
                    product_name = product.get("productName") or product.get("name")
                    
                    if not product_id or not product_name:
                        continue
                    
                    # Get category
                    categories = product.get("categories") or []
                    main_category = None
                    for cat in categories:
                        if cat.get("level") == 1:
                            main_category = cat
                            break
                    if not main_category and categories:
                        main_category = categories[0]
                    
                    category_name = main_category.get("name", "") if main_category else ""
                    
                    # Check if relevant for meal type
                    is_relevant = any(
                        cat.lower() in category_name.lower() or category_name.lower() in cat.lower()
                        for cat in relevant_categories
                    )
                    
                    if not is_relevant:
                        continue
                    
                    key = str(product_id)
                    
                    if key in product_map:
                        existing = product_map[key]
                        existing["frequency"] += 1
                        existing["total_quantity"] += (product.get("quantity") or 1)
                        
                        if product.get("price"):
                            current_avg = existing.get("average_price") or 0
                            existing["average_price"] = (current_avg * (existing["frequency"] - 1) + product["price"]) / existing["frequency"]
                    else:
                        product_map[key] = {
                            "product_id": str(product_id),
                            "product_name": product_name,
                            "brand": product.get("brand") or "",
                            "frequency": 1,
                            "total_quantity": product.get("quantity") or 1,
                            "average_price": product.get("price") or 0,
                            "category": category_name
                        }
            except:
                continue
        
        # Sort by frequency
        sorted_products = sorted(product_map.values(), key=lambda x: x["frequency"], reverse=True)[:items_count]
        
        result = {
            "meal_type": meal_type,
            "analyzed_orders": processed_orders,
            "relevant_items": len(product_map),
            "suggestions": sorted_products
        }
        
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print()
            print(f"   📊 Analysiert: {processed_orders} Bestellungen | {len(product_map)} relevante Produkte")
            print()
            
            if not sorted_products:
                print(f"   ℹ️  Keine {meal_name}-Produkte in deiner Bestellhistorie gefunden.")
                print()
                return 0
            
            print(f"   🍽️  Top {len(sorted_products)} {meal_name}-Produkte:")
            print()
            
            for i, item in enumerate(sorted_products, 1):
                brand = f" ({item['brand']})" if item['brand'] else ""
                avg_price = format_price(item['average_price']) if item['average_price'] else "N/A"
                category = f" | {item['category']}" if item['category'] else ""
                
                print(f"   {i:2}. {item['product_name']}{brand}")
                print(f"       📦 {item['frequency']}× bestellt | ⌀ {avg_price}{category}")
                print(f"       ID: {item['product_id']}")
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


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="knuspr",
        description="🛒 Knuspr.de im Terminal — Einkaufen, Suchen, Warenkorb verwalten, Lieferzeiten, Bestellhistorie und mehr"
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
    
    # ==================== NEW COMMANDS ====================
    
    # delivery command
    delivery_parser = subparsers.add_parser("delivery", help="Lieferinformationen anzeigen")
    delivery_parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    delivery_parser.set_defaults(func=cmd_delivery)
    
    # slots command
    slots_parser = subparsers.add_parser("slots", help="Verfügbare Lieferzeitfenster anzeigen")
    slots_parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    slots_parser.set_defaults(func=cmd_slots)
    
    # orders command
    orders_parser = subparsers.add_parser("orders", help="Bestellhistorie anzeigen")
    orders_parser.add_argument("-n", "--limit", type=int, default=10, help="Anzahl Bestellungen (Standard: 10)")
    orders_parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    orders_parser.set_defaults(func=cmd_orders)
    
    # order command (single order detail)
    order_parser = subparsers.add_parser("order", help="Details einer Bestellung anzeigen")
    order_parser.add_argument("order_id", help="Bestellnummer")
    order_parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    order_parser.set_defaults(func=cmd_order_detail)
    
    # account command
    account_parser = subparsers.add_parser("account", help="Account-Informationen anzeigen")
    account_parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    account_parser.set_defaults(func=cmd_account)
    
    # frequent command
    frequent_parser = subparsers.add_parser("frequent", help="Häufig gekaufte Produkte anzeigen")
    frequent_parser.add_argument("-o", "--orders", type=int, default=5, help="Anzahl Bestellungen zu analysieren (Standard: 5)")
    frequent_parser.add_argument("-t", "--top", type=int, default=10, help="Anzahl Top-Produkte (Standard: 10)")
    frequent_parser.add_argument("--categories", action="store_true", help="Nach Kategorie gruppieren")
    frequent_parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    frequent_parser.set_defaults(func=cmd_frequent)
    
    # meals command
    meals_parser = subparsers.add_parser("meals", help="Mahlzeitvorschläge basierend auf Kaufhistorie")
    meals_parser.add_argument("meal_type", help="Mahlzeittyp: breakfast, lunch, dinner, snack, baking, drinks, healthy")
    meals_parser.add_argument("-c", "--count", type=int, default=10, help="Anzahl Vorschläge (Standard: 10)")
    meals_parser.add_argument("-o", "--orders", type=int, default=5, help="Anzahl Bestellungen zu analysieren (Standard: 5)")
    meals_parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    meals_parser.set_defaults(func=cmd_meals)
    
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
