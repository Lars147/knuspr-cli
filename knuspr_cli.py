#!/usr/bin/env python3
"""Knuspr CLI - Einkaufen bei Knuspr.de vom Terminal aus.

Rein Python, keine externen Dependencies (nur stdlib).

Nutzung:
    python3 knuspr_cli.py login                 # Einloggen
    python3 knuspr_cli.py setup                 # Präferenzen einrichten
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
CONFIG_FILE = Path.home() / ".knuspr_config.json"

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
        favorites_only: bool = False,
        expiring_only: bool = False,
        bio_only: bool = False
    ) -> list[dict[str, Any]]:
        """Search for products.
        
        Args:
            query: Search term
            limit: Maximum results
            favorites_only: Only show favorites
            expiring_only: Only show "Rette Lebensmittel" (expiring soon)
            bio_only: Only show BIO products (badge-based filter)
        """
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        # For badge-based filters, request more results to filter from
        needs_extra = expiring_only or bio_only
        request_limit = limit + 50 if needs_extra else limit + 5
        
        # API filters (currently not working reliably, kept for future)
        api_filters = []
        
        params = urllib.parse.urlencode({
            "search": query,
            "offset": "0",
            "limit": str(request_limit),
            "companyId": "1",
            "filterData": json.dumps({"filters": api_filters}),
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
        
        # Filter expiring products ("Rette Lebensmittel")
        if expiring_only:
            products = [
                p for p in products
                if any(
                    badge.get("slug") == "expiring" or badge.get("type") == "EXPIRING"
                    for badge in p.get("badge", [])
                )
            ]
        
        # Filter BIO products (badge-based)
        if bio_only:
            products = [
                p for p in products
                if any(
                    badge.get("slug") == "bio" or badge.get("type") == "bio"
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
            
            # Extract expiration badge text if present
            expiry_text = None
            discount_text = None
            for badge in p.get("badge", []):
                if badge.get("type") == "EXPIRING" or badge.get("slug") == "expiring":
                    expiry_text = badge.get("text") or badge.get("label")
                if badge.get("position") == "PRICE":
                    discount_text = badge.get("text") or badge.get("label")
            
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
                "expiry": expiry_text,
                "discount": discount_text,
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
    
    def get_current_reservation(self) -> Optional[dict[str, Any]]:
        """Get current timeslot reservation."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        try:
            response = self._make_request("/services/frontend-service/v1/timeslot-reservation")
            if isinstance(response, dict):
                return response.get("data", response) if response else None
            return response
        except KnusprAPIError as e:
            if e.status == 404:
                return None  # No reservation
            raise
    
    def reserve_slot(self, slot_id: int, slot_type: str = "ON_TIME") -> dict[str, Any]:
        """Reserve a delivery time slot.
        
        Args:
            slot_id: The slot ID to reserve
            slot_type: Slot type - "ON_TIME" for 15-min precision, "VIRTUAL" for 1-hour window
        
        Returns:
            Reservation confirmation data
        """
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        payload = {
            "slotId": slot_id,
            "slotType": slot_type
        }
        
        response = self._make_request(
            "/services/frontend-service/v1/timeslot-reservation",
            method="POST",
            data=payload
        )
        
        if isinstance(response, dict):
            return response.get("data", response)
        return response if response else {}
    
    def cancel_reservation(self) -> bool:
        """Cancel current timeslot reservation."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        self._make_request(
            "/services/frontend-service/v1/timeslot-reservation",
            method="DELETE"
        )
        return True
    
    def get_available_filters(self, query: str) -> list[dict[str, Any]]:
        """Get available filters for a search query.
        
        Knuspr generates filters dynamically based on the search results.
        This returns what filters can be applied to narrow down the search.
        
        Args:
            query: Search term
            
        Returns:
            List of filter groups with their options
        """
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        body = {
            "search": query,
            "warehouseId": 10000,
            "isFuzzy": False,
            "type": "PRODUCT",
            "filters": []
        }
        
        response = self._make_request("/api/v1/filters/search", method="POST", data=body)
        
        filter_groups = []
        for group in response.get("filterGroups", []):
            options = []
            for opt in group.get("options", []):
                options.append({
                    "title": opt.get("title"),
                    "key": opt.get("key"),
                    "value": opt.get("value"),
                    "filter_string": f"{opt.get('key')}:{opt.get('value')}",
                    "count": opt.get("matchingProductCount"),
                })
            
            filter_groups.append({
                "tag": group.get("tag"),
                "title": group.get("title"),
                "options": options,
            })
        
        return filter_groups
    
    def get_product_details(self, product_id: int) -> dict[str, Any]:
        """Get detailed product information.
        
        Args:
            product_id: The product ID
            
        Returns:
            Dict with product details including price, stock, freshness info
        """
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        response = self._make_request(f"/api/v1/products/{product_id}/details")
        
        if not response:
            raise KnusprAPIError(f"Produkt {product_id} nicht gefunden")
        
        product = response.get("product", {})
        stock = response.get("stock", {})
        prices = response.get("prices", {})
        
        # Extract country info
        countries = product.get("countries", [])
        country_name = countries[0].get("name") if countries else None
        country_code = countries[0].get("code") if countries else None
        
        # Extract badges
        badges = []
        for badge in product.get("badges", []):
            badges.append({
                "type": badge.get("type"),
                "title": badge.get("title"),
                "subtitle": badge.get("subtitle"),
            })
        
        # Extract shelf life / freshness
        shelf_life = stock.get("shelfLife", {}) or {}
        freshness = stock.get("freshness", {}) or {}
        
        # Extract price info
        price_obj = prices.get("price", {})
        unit_price_obj = prices.get("pricePerUnit", {})
        
        # Sales info
        sales = prices.get("sales", [])
        sale_info = None
        if sales:
            sale = sales[0]
            sale_info = {
                "title": sale.get("title"),
                "original_price": sale.get("originalPrice"),
                "sale_price": sale.get("salePrice"),
            }
        
        # Product story
        story = product.get("productStory")
        story_info = None
        if story:
            story_info = {
                "title": story.get("title"),
                "text": story.get("text"),
            }
        
        # Tooltips (contain additional info)
        tooltips = []
        for tooltip in stock.get("tooltips", []):
            tooltips.append({
                "type": tooltip.get("type"),
                "message": tooltip.get("message"),
            })
        
        return {
            "id": product.get("id"),
            "name": product.get("name"),
            "slug": product.get("slug"),
            "brand": product.get("brand"),
            "amount": product.get("textualAmount"),
            "unit": product.get("unit"),
            "price": price_obj.get("amount"),
            "currency": price_obj.get("currency", "EUR"),
            "unit_price": unit_price_obj.get("amount"),
            "unit_price_currency": unit_price_obj.get("currency", "EUR"),
            "in_stock": stock.get("inStock", False),
            "max_quantity": stock.get("maxBasketAmount"),
            "country": country_name,
            "country_code": country_code,
            "badges": badges,
            "images": product.get("images", []),
            "shelf_life": {
                "type": shelf_life.get("type"),
                "average_days": shelf_life.get("average"),
                "minimum_days": shelf_life.get("minimal"),
                "best_before": shelf_life.get("bestBefore"),
            } if shelf_life else None,
            "freshness_message": freshness.get("message") if freshness else None,
            "sale": sale_info,
            "story": story_info,
            "tooltips": tooltips,
            "information": product.get("information", []),
            "advice_for_safe_use": product.get("adviceForSafeUse"),
            "weighted_item": product.get("weightedItem", False),
            "premium_only": product.get("premiumOnly", False),
            "archived": product.get("archived", False),
        }

    def get_rette_products(self, category_id: Optional[int] = None) -> list[dict[str, Any]]:
        """Get all 'Rette Lebensmittel' (expiring) products.
        
        Args:
            category_id: Optional category filter (652=Fleisch, 532=Kühlregal, etc.)
        
        Returns:
            List of expiring products with details
        """
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        import re
        
        # Rette Lebensmittel category IDs
        RETTE_CATEGORIES = {
            652: "Fleisch & Fisch",
            532: "Kühlregal", 
            663: "Wurst & Schinken",
            480: "Brot & Gebäck",
            2416: "Plant Based",
            833: "Baby & Kinder",
            4668: "Süßes & Salziges",
            770: "Marks & Spencer",
        }
        
        if category_id:
            categories = {category_id: RETTE_CATEGORIES.get(category_id, "Unbekannt")}
        else:
            categories = RETTE_CATEGORIES
        
        all_product_ids = set()
        
        # Scrape each category page for product IDs
        for cat_id in categories.keys():
            try:
                url = f"{BASE_URL}/rette-lebensmittel/c{cat_id}"
                headers = self._get_headers()
                headers["Accept"] = "text/html"
                
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=15) as response:
                    html = response.read().decode("utf-8")
                
                # Extract product IDs from HTML
                pids = re.findall(r'"productId":(\d+)', html)
                all_product_ids.update(pids)
            except Exception:
                continue
        
        if not all_product_ids:
            return []
        
        # Fetch product details using the card endpoint
        product_ids = list(all_product_ids)
        params = "&".join([f"products={pid}" for pid in product_ids])
        
        try:
            result = self._make_request(f"/api/v1/products/card?{params}&categoryType=last-minute")
        except KnusprAPIError:
            return []
        
        if not isinstance(result, list):
            return []
        
        # Format results
        products = []
        for p in result:
            # Extract expiry badge
            expiry_text = None
            discount_text = None
            for badge in p.get("badges", []):
                if badge.get("type") == "EXPIRING":
                    expiry_text = badge.get("text")
                if badge.get("position") == "PRICE":
                    discount_text = badge.get("text")
            
            prices = p.get("prices", {})
            
            products.append({
                "id": p.get("productId"),
                "name": p.get("name"),
                "price": prices.get("salePrice") or prices.get("originalPrice"),
                "original_price": prices.get("originalPrice"),
                "currency": prices.get("currency", "EUR"),
                "unit_price": prices.get("unitPrice"),
                "brand": p.get("brand"),
                "amount": p.get("textualAmount"),
                "in_stock": p.get("stock", {}).get("availabilityStatus") == "AVAILABLE",
                "expiry": expiry_text,
                "discount": discount_text,
            })
        
        # Sort by expiry (today first)
        def expiry_sort(p):
            exp = (p.get("expiry") or "").lower()
            if "heute" in exp:
                return 0
            elif "morgen" in exp:
                return 1
            else:
                return 2
        
        products.sort(key=expiry_sort)
        
        return products
    
    # ==================== FAVORITES API METHODS ====================
    
    def get_favorites(self) -> list[dict[str, Any]]:
        """Get all favorite products.
        
        Since there's no direct endpoint to list favorites, we search through
        multiple common search terms and filter products marked as favorites.
        
        Returns:
            List of favorite products with details
        """
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        # Search terms: common German letters for broad coverage
        # With pagination (limit 500, max 1000 per term) = ~8-16 API calls
        search_terms = ["e", "a", "n", "i"]
        
        all_favorites: dict[int, dict] = {}
        
        for term in search_terms:
            offset = 0
            limit = 500  # API accepts up to ~500
            max_offset = 1000  # Don't go too deep per term (balance speed vs coverage)
            
            while offset < max_offset:
                try:
                    params = urllib.parse.urlencode({
                        "search": term,
                        "offset": str(offset),
                        "limit": str(limit),
                        "companyId": "1",
                        "filterData": json.dumps({"filters": []}),
                        "canCorrect": "true"
                    })
                    
                    response = self._make_request(f"/services/frontend-service/search-metadata?{params}")
                    products = response.get("data", {}).get("productList", [])
                    
                    for p in products:
                        if p.get("favourite") and p.get("productId") not in all_favorites:
                            price_info = p.get("price", {})
                            all_favorites[p.get("productId")] = {
                                "id": p.get("productId"),
                                "name": p.get("productName"),
                                "price": price_info.get("full"),
                                "currency": price_info.get("currency", "EUR"),
                                "unit_price": price_info.get("unitPrice"),
                                "brand": p.get("brand"),
                                "amount": p.get("textualAmount"),
                                "in_stock": p.get("inStock", True),
                                "image": p.get("image"),
                            }
                    
                    # Stop if we got less than requested (end of results)
                    if len(products) < limit:
                        break
                    
                    offset += limit
                except KnusprAPIError:
                    break
        
        # Sort by name
        return sorted(all_favorites.values(), key=lambda p: p.get("name", "").lower())
    
    def add_favorite(self, product_id: int) -> dict[str, Any]:
        """Add a product to favorites.
        
        Args:
            product_id: The product ID to add to favorites
        
        Returns:
            Dict with productId and favourite status
        """
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        payload = {
            "productId": product_id,
            "favourite": True
        }
        
        response = self._make_request(
            "/services/frontend-service/product/favourite",
            method="POST",
            data=payload
        )
        
        data = response.get("data", {})
        if not data.get("favourite"):
            raise KnusprAPIError(f"Failed to add product {product_id} to favorites")
        
        return data
    
    def remove_favorite(self, product_id: int) -> dict[str, Any]:
        """Remove a product from favorites.
        
        Args:
            product_id: The product ID to remove from favorites
        
        Returns:
            Dict with productId and favourite status
        """
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr login' first.")
        
        payload = {
            "productId": product_id,
            "favourite": False
        }
        
        response = self._make_request(
            "/services/frontend-service/product/favourite",
            method="POST",
            data=payload
        )
        
        data = response.get("data", {})
        if data.get("favourite"):
            raise KnusprAPIError(f"Failed to remove product {product_id} from favorites")
        
        return data


def load_credentials() -> tuple[Optional[str], Optional[str]]:
    """Load credentials from file or environment (returns None if not found)."""
    email = None
    password = None
    
    # 1. Check environment variables
    email = os.environ.get("KNUSPR_EMAIL")
    password = os.environ.get("KNUSPR_PASSWORD")
    if email and password:
        return email, password
    
    # 2. Check ~/.knuspr_credentials.json
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


def load_config() -> dict[str, Any]:
    """Load user configuration or return empty dict."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_config(config: dict[str, Any]) -> None:
    """Save user configuration to file."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


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
    
    # Load config and show hint if not configured
    config = load_config()
    show_setup_hint = not config and not args.json
    
    # Check for expiring/rette filter
    expiring_only = getattr(args, 'expiring', False) or getattr(args, 'rette', False)
    
    try:
        if not args.json:
            print()
            if expiring_only:
                print(f"🥬 Rette Lebensmittel: '{args.query}'")
            else:
                print(f"🔍 Suche in Knuspr: '{args.query}'")
            print("─" * 50)
        
        # Apply config preferences (CLI flags override config)
        prefer_bio = getattr(args, 'bio', None)
        if prefer_bio is None:
            prefer_bio = config.get("prefer_bio", False)
        
        results = api.search_products(
            args.query,
            limit=args.limit,
            favorites_only=args.favorites,
            expiring_only=expiring_only,
            bio_only=prefer_bio
        )
        
        exclusions = getattr(args, 'exclude', None)
        if exclusions is None:
            exclusions = config.get("exclusions", [])
        
        sort_order = getattr(args, 'sort', None)
        if sort_order is None:
            sort_order = config.get("default_sort", "relevance")
        
        # Filter exclusions
        if exclusions:
            original_count = len(results)
            results = [
                p for p in results
                if not any(
                    excl.lower() in (p.get("name") or "").lower() or
                    excl.lower() in (p.get("brand") or "").lower()
                    for excl in exclusions
                )
            ]
            filtered_count = original_count - len(results)
            if filtered_count > 0 and not args.json:
                print(f"   ({filtered_count} Produkte durch Ausschlüsse gefiltert)")
        
        # Apply sorting
        if sort_order == "price_asc":
            results.sort(key=lambda p: p.get("price") or float('inf'))
        elif sort_order == "price_desc":
            results.sort(key=lambda p: p.get("price") or 0, reverse=True)
        # rating and relevance keep original order (API default)
        
        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            if not results:
                print(f"Keine Produkte gefunden für '{args.query}'")
                print()
                if show_setup_hint:
                    print("💡 Tipp: Führe 'knuspr setup' aus um Präferenzen zu setzen")
                    print()
                return 0
            
            print(f"Gefunden: {len(results)} Produkte")
            if prefer_bio:
                print("   🌿 Nur Bio-Produkte")
            print()
            
            for i, p in enumerate(results, 1):
                stock = "✅" if p["in_stock"] else "❌"
                brand = f" ({p['brand']})" if p['brand'] else ""
                name = p['name']
                # Mark bio products
                name_lower = name.lower()
                brand_lower = (p.get('brand') or '').lower()
                is_bio = "bio" in name_lower or "bio" in brand_lower or "organic" in name_lower
                bio_badge = " 🌿" if is_bio and prefer_bio else ""
                
                # Show discount and expiry for Rette Lebensmittel
                discount = p.get('discount', '')
                expiry = p.get('expiry', '')
                discount_str = f" {discount}" if discount else ""
                
                print(f"  {i:2}. {name}{brand}{bio_badge}{discount_str}")
                
                if expiring_only and expiry:
                    print(f"      ⏰ {expiry}")
                
                print(f"      💰 {p['price']} {p['currency']}  │  📦 {p['amount']}  │  {stock}")
                print(f"      ID: {p['id']}")
                print()
            
            if show_setup_hint:
                print("💡 Tipp: Führe 'knuspr setup' aus um Präferenzen zu setzen")
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


def cmd_setup(args: argparse.Namespace) -> int:
    """Handle setup command - interactive onboarding for preferences."""
    
    # Handle reset flag
    if getattr(args, 'reset', False):
        if CONFIG_FILE.exists():
            CONFIG_FILE.unlink()
            print()
            print("✅ Konfiguration zurückgesetzt.")
            print()
        else:
            print()
            print("ℹ️  Keine Konfiguration vorhanden.")
            print()
        return 0
    
    print()
    print("╔═══════════════════════════════════════════════════════════╗")
    print("║  ⚙️  KNUSPR SETUP                                          ║")
    print("╚═══════════════════════════════════════════════════════════╝")
    print()
    print("   Richte deine Präferenzen ein für bessere Suchergebnisse!")
    print()
    print("─" * 60)
    print()
    
    config = load_config()
    
    # 1. Bio-Präferenz
    print("🌿 Bio-Produkte bevorzugen?")
    print("   Bio-Produkte werden in Suchergebnissen höher angezeigt.")
    print()
    current_bio = config.get("prefer_bio", False)
    default_bio = "ja" if current_bio else "nein"
    bio_input = input(f"   Bevorzuge Bio? (ja/nein) [{default_bio}]: ").strip().lower()
    
    if bio_input in ("ja", "j", "yes", "y", "1"):
        config["prefer_bio"] = True
    elif bio_input in ("nein", "n", "no", "0"):
        config["prefer_bio"] = False
    elif bio_input == "":
        config["prefer_bio"] = current_bio
    else:
        config["prefer_bio"] = False
    
    print()
    
    # 2. Standard-Sortierung
    print("📊 Standard-Sortierung für Suchergebnisse:")
    print()
    print("   1. Relevanz (Standard)")
    print("   2. Preis aufsteigend (günstigste zuerst)")
    print("   3. Preis absteigend (teuerste zuerst)")
    print("   4. Bewertung (beste zuerst)")
    print()
    
    sort_options = {
        "1": "relevance",
        "2": "price_asc",
        "3": "price_desc",
        "4": "rating"
    }
    sort_names = {
        "relevance": "Relevanz",
        "price_asc": "Preis aufsteigend",
        "price_desc": "Preis absteigend",
        "rating": "Bewertung"
    }
    
    current_sort = config.get("default_sort", "relevance")
    current_sort_num = next((k for k, v in sort_options.items() if v == current_sort), "1")
    
    sort_input = input(f"   Wähle Sortierung (1-4) [{current_sort_num}]: ").strip()
    
    if sort_input in sort_options:
        config["default_sort"] = sort_options[sort_input]
    elif sort_input == "":
        config["default_sort"] = current_sort
    else:
        config["default_sort"] = "relevance"
    
    print()
    
    # 3. Ausschlüsse
    print("🚫 Produkte ausschließen (optional):")
    print("   Begriffe, die aus Suchergebnissen gefiltert werden.")
    print("   z.B.: Laktose, Gluten, Schwein")
    print()
    
    current_exclusions = config.get("exclusions", [])
    current_exclusions_str = ", ".join(current_exclusions) if current_exclusions else ""
    default_hint = f" [{current_exclusions_str}]" if current_exclusions_str else ""
    
    exclusions_input = input(f"   Ausschlüsse (kommagetrennt){default_hint}: ").strip()
    
    if exclusions_input:
        exclusions = [e.strip() for e in exclusions_input.split(",") if e.strip()]
        config["exclusions"] = exclusions
    elif exclusions_input == "" and current_exclusions:
        config["exclusions"] = current_exclusions
    else:
        config["exclusions"] = []
    
    print()
    
    # Save config
    save_config(config)
    
    # Summary
    print("─" * 60)
    print()
    print("✅ Konfiguration gespeichert!")
    print()
    print("╔═══════════════════════════════════════════════════════════╗")
    print("║  📋 ZUSAMMENFASSUNG                                        ║")
    print("╚═══════════════════════════════════════════════════════════╝")
    print()
    
    bio_status = "✅ Ja" if config.get("prefer_bio") else "❌ Nein"
    print(f"   🌿 Bio bevorzugen:     {bio_status}")
    
    sort_name = sort_names.get(config.get("default_sort", "relevance"), "Relevanz")
    print(f"   📊 Standard-Sortierung: {sort_name}")
    
    exclusions = config.get("exclusions", [])
    if exclusions:
        print(f"   🚫 Ausschlüsse:         {', '.join(exclusions)}")
    else:
        print(f"   🚫 Ausschlüsse:         Keine")
    
    print()
    print(f"   💾 Gespeichert in: {CONFIG_FILE}")
    print()
    print("   Tipp: Nutze 'knuspr setup --reset' um zurückzusetzen.")
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
        raw_slots = api.get_delivery_slots()
        
        if args.json:
            print(json.dumps(raw_slots, indent=2, ensure_ascii=False))
            return 0
        
        print()
        print("╔═══════════════════════════════════════════════════════════╗")
        print("║  📅 LIEFERZEITFENSTER                                      ║")
        print("╚═══════════════════════════════════════════════════════════╝")
        print()
        
        if not raw_slots:
            print("   ℹ️  Keine Lieferzeitfenster verfügbar.")
            print()
            return 0
        
        # Parse the nested structure: 
        # .[0].availabilityDays[] -> {date, label, slots: {hour: [slot objects]}}
        all_days = []
        for response_item in raw_slots:
            if isinstance(response_item, dict):
                availability_days = response_item.get("availabilityDays", [])
                for day in availability_days:
                    if isinstance(day, dict):
                        date = day.get("date", "")
                        label = day.get("label", "")
                        slots_by_hour = day.get("slots", {})
                        day_slots = []
                        if isinstance(slots_by_hour, dict):
                            for hour, hour_slots in slots_by_hour.items():
                                if isinstance(hour_slots, list):
                                    day_slots.extend(hour_slots)
                        if day_slots:
                            all_days.append({"date": date, "label": label, "slots": day_slots})
        
        if not all_days:
            print("   ℹ️  Keine Lieferzeitfenster verfügbar.")
            print()
            return 0
        
        # Show days with their slots
        max_days = 10 if args.detailed else 5
        for day_info in all_days[:max_days]:
            date = day_info["date"]
            label = day_info["label"]
            slots = day_info["slots"]
            
            # Format date nicely
            date_display = label if label else format_date(date)
            print(f"   📅 {date_display} ({date})")
            print()
            
            # Show slots based on --detailed flag
            if args.detailed:
                # Show all slots including 15-min ON_TIME slots (no limit)
                display_slots = sorted(slots, key=lambda s: s.get("since", ""))
            else:
                # Show only VIRTUAL slots (1-hour windows)
                display_slots = [s for s in slots if s.get("type") == "VIRTUAL"]
                if not display_slots:
                    display_slots = slots[:12]  # Fallback
            
            for slot in display_slots:
                time_window = slot.get("timeWindow", "")
                price = slot.get("price", 0)
                capacity = slot.get("capacity", "")
                eco = "🌿" if slot.get("eco") else ""
                premium = "⭐" if slot.get("premium") else ""
                
                # Get capacity percentage and message
                capacity_dto = slot.get("timeSlotCapacityDTO", {})
                capacity_percent = capacity_dto.get("totalFreeCapacityPercent", 0)
                capacity_msg = capacity_dto.get("capacityMessage", "")
                
                # Determine status based on capacity
                if capacity_msg == "Ausgebucht" or capacity_percent == 0:
                    status = "❌ Ausgebucht"
                elif capacity == "GREEN" and capacity_percent >= 50:
                    status = f"✅ {capacity_percent}%"
                elif capacity == "GREEN" or capacity_percent > 0:
                    status = f"⚠️ {capacity_percent}%"
                else:
                    status = "❌ Ausgebucht"
                
                price_str = "Kostenlos" if price == 0 else f"{price:.2f} €"
                
                slot_id = slot.get("slotId") or slot.get("id") or "?"
                print(f"      🕐 {time_window:12} | 💰 {price_str:10} | {status:14} {eco}{premium} [ID: {slot_id}]")
            
            print()
        
        remaining_days = len(all_days) - max_days
        if remaining_days > 0:
            print(f"   ... und {remaining_days} weitere Tage verfügbar")
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
                total_obj = price_comp.get("total", {})
                if isinstance(total_obj, dict):
                    price = total_obj.get("amount", 0)
                else:
                    price = total_obj or order.get("totalPrice") or order.get("price") or 0
                
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
            
            # Parse order details from actual API structure
            status = order.get("state") or order.get("status") or "Unbekannt"
            date = order.get("orderTime") or order.get("deliveredAt") or order.get("createdAt") or ""
            
            # Get total price from priceComposition.total.amount
            price_comp = order.get("priceComposition", {})
            total_obj = price_comp.get("total", {})
            total_price = total_obj.get("amount", 0) if isinstance(total_obj, dict) else total_obj
            
            # Translate status
            status_map = {"DELIVERED": "Geliefert", "PENDING": "In Bearbeitung", "CANCELLED": "Storniert"}
            status_display = status_map.get(status, status)
            
            print(f"   📊 Status: {status_display}")
            print(f"   📅 Datum: {format_date(date)}")
            print(f"   💰 Gesamt: {format_price(total_price)}")
            
            # Show price breakdown
            delivery_price = price_comp.get("delivery", {}).get("amount", 0)
            tip = price_comp.get("courierTip", {}).get("amount", 0)
            credits_used = price_comp.get("creditsUsed", {}).get("amount", 0)
            goods_price = price_comp.get("goods", {}).get("amount", 0)
            
            if goods_price > 0:
                print(f"   🛍️  Waren: {format_price(goods_price)}")
            if delivery_price > 0:
                print(f"   🚚 Lieferung: {format_price(delivery_price)}")
            if tip > 0:
                print(f"   💚 Trinkgeld: {format_price(tip)}")
            if credits_used > 0:
                print(f"   🎁 Guthaben: -{format_price(credits_used)}")
            print()
            
            products = order.get("items") or order.get("products") or []
            if products:
                print(f"   🛒 Produkte ({len(products)}):")
                print()
                for p in products:
                    name = p.get("name") or p.get("productName") or "Unbekannt"
                    qty = p.get("amount") or p.get("quantity") or 1
                    textual_amount = p.get("textualAmount", "")
                    
                    # Get price from priceComposition.total.amount
                    p_price_comp = p.get("priceComposition", {})
                    p_total = p_price_comp.get("total", {})
                    price = p_total.get("amount", 0) if isinstance(p_total, dict) else 0
                    
                    amount_str = f" ({textual_amount})" if textual_amount else ""
                    print(f"      • {name}{amount_str}")
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
                count = bags.get("current") or bags.get("count") or bags.get("bagsCount") or 0
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


def cmd_slot_reserve(args: argparse.Namespace) -> int:
    """Handle slot reserve command - reserve a delivery time slot."""
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
        slot_id = int(args.slot_id)
        slot_type = args.type.upper() if hasattr(args, 'type') and args.type else "ON_TIME"
        
        if not args.json:
            print()
            print(f"  → Reserviere Slot {slot_id} ({slot_type})...")
        
        api.reserve_slot(slot_id, slot_type)
        
        # Fetch the current reservation to get full details
        reservation = api.get_current_reservation()
        
        if args.json:
            print(json.dumps(reservation or {"success": True, "slotId": slot_id}, indent=2, ensure_ascii=False))
        else:
            print()
            print("╔═══════════════════════════════════════════════════════════╗")
            print("║  ✅ SLOT RESERVIERT                                        ║")
            print("╚═══════════════════════════════════════════════════════════╝")
            print()
            
            # Parse reservationDetail structure (same as status)
            detail = (reservation or {}).get("reservationDetail", {})
            time_window = detail.get("dayAndTimeWindow") or f"Slot {slot_id}"
            duration = detail.get("duration") or 60
            expires = detail.get("tillZoned") or detail.get("till") or ""
            
            print(f"   🕐 Zeitfenster: {time_window}")
            print(f"   🆔 Slot-ID: {slot_id}")
            print(f"   ⏱️  Reservierung gültig für: {duration} Minuten")
            if expires:
                print(f"   ⏰ Läuft ab: {format_date(expires)}")
            print()
            print("   💡 Tipp: Reservierung wird beim Bestellen automatisch verwendet.")
            print()
        
        return 0
    except ValueError:
        if args.json:
            print(json.dumps({"error": f"Ungültige Slot-ID: {args.slot_id}"}, indent=2))
        else:
            print()
            print(f"❌ Ungültige Slot-ID: {args.slot_id}")
            print()
        return 1
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return 1


def cmd_slot_status(args: argparse.Namespace) -> int:
    """Handle slot status command - show current reservation."""
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
        reservation = api.get_current_reservation()
        
        if args.json:
            print(json.dumps(reservation or {"active": False}, indent=2, ensure_ascii=False))
        else:
            print()
            print("╔═══════════════════════════════════════════════════════════╗")
            print("║  📅 AKTUELLE RESERVIERUNG                                  ║")
            print("╚═══════════════════════════════════════════════════════════╝")
            print()
            
            is_active = reservation.get("active", False) if reservation else False
            
            if not reservation or not is_active:
                print("   ℹ️  Kein Zeitfenster reserviert.")
                print()
                print("   💡 Tipp: Nutze 'knuspr slots --detailed' um verfügbare Zeitfenster zu sehen,")
                print("           dann 'knuspr slot reserve <id>' zum Reservieren.")
                print()
                return 0
            
            # Parse reservationDetail structure
            detail = reservation.get("reservationDetail", {})
            time_window = detail.get("dayAndTimeWindow") or "Unbekannt"
            slot_id = detail.get("slotId") or "?"
            slot_type = detail.get("slotType") or "ON_TIME"
            duration = detail.get("duration") or 60
            expires = detail.get("tillZoned") or detail.get("till") or ""
            
            print(f"   ✅ Reserviert: {time_window}")
            print(f"   🆔 Slot-ID: {slot_id}")
            print(f"   📦 Typ: {slot_type}")
            print(f"   ⏱️  Reservierung gültig für: {duration} Minuten")
            if expires:
                print(f"   ⏰ Läuft ab: {format_date(expires)}")
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


def cmd_slot_cancel(args: argparse.Namespace) -> int:
    """Handle slot cancel command - cancel current reservation."""
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
        # First check if there's a reservation
        reservation = api.get_current_reservation()
        
        if not reservation:
            if args.json:
                print(json.dumps({"message": "Keine aktive Reservierung"}, indent=2))
            else:
                print()
                print("ℹ️  Keine aktive Reservierung zum Stornieren.")
                print()
            return 0
        
        if not args.json:
            print()
            print("  → Storniere Reservierung...")
        
        api.cancel_reservation()
        
        if args.json:
            print(json.dumps({"success": True, "message": "Reservierung storniert"}, indent=2))
        else:
            print()
            print("✅ Reservierung storniert.")
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


def cmd_product(args: argparse.Namespace) -> int:
    """Handle product command - show detailed product information."""
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
        product_id = int(args.product_id)
    except ValueError:
        if args.json:
            print(json.dumps({"error": f"Ungültige Produkt-ID: {args.product_id}"}, indent=2))
        else:
            print()
            print(f"❌ Ungültige Produkt-ID: {args.product_id}")
            print()
        return 1
    
    try:
        product = api.get_product_details(product_id)
        
        if args.json:
            print(json.dumps(product, indent=2, ensure_ascii=False))
        else:
            print()
            print("╔═══════════════════════════════════════════════════════════╗")
            print("║  📦 PRODUKT-DETAILS                                        ║")
            print("╚═══════════════════════════════════════════════════════════╝")
            print()
            
            # Name and Brand
            name = product.get("name", "Unbekannt")
            brand = product.get("brand")
            print(f"   🏷️  {name}")
            if brand:
                print(f"   🏭 Marke: {brand}")
            print()
            
            # Badges (Bio, Premium, etc.)
            badges = product.get("badges", [])
            if badges:
                badge_str = " ".join([f"[{b.get('title', '?')}]" for b in badges if b.get('title')])
                if badge_str:
                    print(f"   🏅 {badge_str}")
                    print()
            
            # Price Info
            print("   💰 PREIS")
            print("   ─────────────────────────────────")
            price = product.get("price")
            currency = product.get("currency", "EUR")
            amount = product.get("amount", "?")
            unit_price = product.get("unit_price")
            
            if price is not None:
                print(f"      Preis: {price:.2f} {currency}")
            print(f"      Menge: {amount}")
            if unit_price is not None:
                unit = product.get("unit", "kg")
                print(f"      Grundpreis: {unit_price:.2f} {currency}/{unit}")
            
            # Sale info
            sale = product.get("sale")
            if sale:
                orig = sale.get("original_price")
                sale_price = sale.get("sale_price")
                title = sale.get("title", "Angebot")
                if orig and sale_price:
                    print(f"      🔥 {title}: {sale_price:.2f} € (statt {orig:.2f} €)")
            print()
            
            # Stock Info
            print("   📊 VERFÜGBARKEIT")
            print("   ─────────────────────────────────")
            in_stock = product.get("in_stock", False)
            max_qty = product.get("max_quantity")
            stock_str = "✅ Auf Lager" if in_stock else "❌ Nicht verfügbar"
            print(f"      Status: {stock_str}")
            if max_qty:
                print(f"      Max. Bestellmenge: {max_qty}")
            
            if product.get("premium_only"):
                print(f"      ⭐ Nur für Premium-Kunden")
            print()
            
            # Freshness / Shelf Life
            shelf_life = product.get("shelf_life")
            freshness_msg = product.get("freshness_message")
            if shelf_life or freshness_msg:
                print("   🥬 FRISCHE")
                print("   ─────────────────────────────────")
                if freshness_msg:
                    print(f"      {freshness_msg}")
                if shelf_life:
                    avg = shelf_life.get("average_days")
                    min_days = shelf_life.get("minimum_days")
                    if avg:
                        print(f"      Durchschnittliche Frische: {avg} Tage")
                    if min_days:
                        print(f"      Mindest-Haltbarkeit: {min_days} Tage")
                print()
            
            # Country of Origin
            country = product.get("country")
            country_code = product.get("country_code")
            if country:
                flag = f" ({country_code})" if country_code else ""
                print("   🌍 HERKUNFT")
                print("   ─────────────────────────────────")
                print(f"      {country}{flag}")
                print()
            
            # Tooltips (additional info)
            tooltips = product.get("tooltips", [])
            if tooltips:
                print("   ℹ️  HINWEISE")
                print("   ─────────────────────────────────")
                for tip in tooltips:
                    msg = tip.get("message", "")
                    if msg:
                        # Word wrap long messages
                        words = msg.split()
                        lines = []
                        current = ""
                        for word in words:
                            if len(current) + len(word) + 1 <= 50:
                                current = f"{current} {word}".strip()
                            else:
                                if current:
                                    lines.append(current)
                                current = word
                        if current:
                            lines.append(current)
                        for i, line in enumerate(lines):
                            prefix = "      " if i == 0 else "        "
                            print(f"{prefix}{line}")
                print()
            
            # Product Story
            story = product.get("story")
            if story:
                title = story.get("title", "")
                text = story.get("text", "")
                if title or text:
                    print("   📖 PRODUKT-STORY")
                    print("   ─────────────────────────────────")
                    if title:
                        print(f"      {title}")
                    if text:
                        # Word wrap
                        words = text.split()
                        lines = []
                        current = ""
                        for word in words:
                            if len(current) + len(word) + 1 <= 50:
                                current = f"{current} {word}".strip()
                            else:
                                if current:
                                    lines.append(current)
                                current = word
                        if current:
                            lines.append(current)
                        for line in lines:
                            print(f"      {line}")
                    print()
            
            # Additional product information (if available)
            information = product.get("information", [])
            if information:
                print("   📋 WEITERE INFORMATIONEN")
                print("   ─────────────────────────────────")
                for info in information:
                    info_type = info.get("type", "")
                    info_value = info.get("value", "")
                    if info_type and info_value:
                        print(f"      {info_type}: {info_value}")
                print()
            
            # Safe use advice
            advice = product.get("advice_for_safe_use")
            if advice:
                print("   ⚠️  SICHERHEITSHINWEIS")
                print("   ─────────────────────────────────")
                print(f"      {advice}")
                print()
            
            # Images
            images = product.get("images", [])
            if images:
                print("   🖼️  BILDER")
                print("   ─────────────────────────────────")
                for i, img in enumerate(images[:3], 1):
                    print(f"      {i}. {img}")
                print()
            
            # Product ID for reference
            print(f"   🔗 Produkt-ID: {product.get('id')}")
            slug = product.get("slug")
            if slug:
                print(f"   🌐 https://www.knuspr.de/{product.get('id')}-{slug}")
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


def cmd_filters(args: argparse.Namespace) -> int:
    """Handle filters command - show available filters for a search."""
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
        filter_groups = api.get_available_filters(args.query)
        
        if args.json:
            print(json.dumps(filter_groups, indent=2, ensure_ascii=False))
            return 0
        
        print()
        print(f"🔍 Verfügbare Filter für: '{args.query}'")
        print("─" * 50)
        print()
        print("Filter können mit --filter \"key:value\" verwendet werden.")
        print("Mehrere Filter: --filter \"key1:value1\" --filter \"key2:value2\"")
        print()
        
        for group in filter_groups:
            title = group.get("title") or group.get("tag", "").upper()
            options = group.get("options", [])
            
            if not options:
                continue
            
            print(f"📁 {title}")
            
            # Show max 8 options per group, with counts if available
            for opt in options[:8]:
                name = opt.get("title")
                filter_str = opt.get("filter_string")
                count = opt.get("count")
                
                if count:
                    print(f"     {name} ({count})")
                else:
                    print(f"     {name}")
                print(f"       └─ --filter \"{filter_str}\"")
            
            if len(options) > 8:
                print(f"     ... und {len(options) - 8} weitere")
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


def cmd_rette(args: argparse.Namespace) -> int:
    """Handle rette command - show all Rette Lebensmittel products."""
    api = KnusprAPI()
    
    if not api.is_logged_in():
        if args.json:
            print(json.dumps({"error": "Nicht eingeloggt"}, indent=2))
        else:
            print()
            print("❌ Nicht eingeloggt. Führe 'knuspr login' aus.")
            print()
        return 1
    
    search_term = getattr(args, 'search', None)
    
    try:
        if not args.json:
            print()
            print("╔═══════════════════════════════════════════════════════════╗")
            print("║  🥬 RETTE LEBENSMITTEL                                     ║")
            print("╚═══════════════════════════════════════════════════════════╝")
            print()
            print("   → Lade Produkte...")
        
        products = api.get_rette_products()
        
        # Filter by search term if provided
        if search_term and products:
            search_lower = search_term.lower()
            products = [
                p for p in products
                if search_lower in (p.get("name") or "").lower()
                or search_lower in (p.get("brand") or "").lower()
            ]
        
        if args.json:
            print(json.dumps(products, indent=2, ensure_ascii=False))
        else:
            if not products:
                print()
                if search_term:
                    print(f"   ℹ️  Keine Rette-Lebensmittel für '{search_term}' gefunden.")
                else:
                    print("   ℹ️  Keine Rette-Lebensmittel verfügbar.")
                print()
                return 0
            
            if search_term:
                print(f"   Gefunden: {len(products)} Produkte für '{search_term}'")
            else:
                print(f"   Gefunden: {len(products)} Produkte")
            print()
            
            for i, p in enumerate(products, 1):
                stock = "✅" if p["in_stock"] else "❌"
                brand = f" ({p['brand']})" if p.get('brand') else ""
                name = p['name'] or "?"
                
                # Show discount
                discount = p.get('discount', '')
                discount_str = f" {discount}" if discount else ""
                
                # Price formatting
                price = p.get('price') or 0
                orig = p.get('original_price')
                if orig and orig != price:
                    price_str = f"💰 {price:.2f} € (statt {orig:.2f} €)"
                else:
                    price_str = f"💰 {price:.2f} €"
                
                print(f"  {i:2}. {name}{brand}{discount_str}")
                
                # Expiry info
                expiry = p.get('expiry', '')
                if expiry:
                    print(f"      ⏰ {expiry}")
                
                print(f"      {price_str}  │  📦 {p.get('amount', '?')}  │  {stock}")
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


# ==================== FAVORITES COMMANDS ====================

def cmd_favorites_list(args: argparse.Namespace) -> int:
    """Handle favorites list command - show all favorite products."""
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
            print("╔═══════════════════════════════════════════════════════════╗")
            print("║  ⭐ FAVORITEN                                              ║")
            print("╚═══════════════════════════════════════════════════════════╝")
            print()
            print("   → Lade Favoriten...")
        
        favorites = api.get_favorites()
        
        if args.json:
            print(json.dumps(favorites, indent=2, ensure_ascii=False))
        else:
            print()
            if not favorites:
                print("   ℹ️  Keine Favoriten gefunden.")
                print()
                print("   💡 Tipp: Füge Favoriten hinzu mit 'knuspr favorites add <id>'")
                print()
                return 0
            
            print(f"   Gefunden: {len(favorites)} Favoriten")
            print()
            
            for i, p in enumerate(favorites, 1):
                stock = "✅" if p.get("in_stock", True) else "❌"
                brand = f" ({p['brand']})" if p.get('brand') else ""
                name = p.get('name', 'Unbekannt')
                price = p.get('price', 0) or 0
                currency = p.get('currency', 'EUR')
                amount = p.get('amount', '?')
                
                print(f"  {i:2}. {name}{brand}")
                print(f"      💰 {price:.2f} {currency}  │  📦 {amount}  │  {stock}")
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


def cmd_favorites_add(args: argparse.Namespace) -> int:
    """Handle favorites add command - add a product to favorites."""
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
        product_id = int(args.product_id)
        
        if not args.json:
            print()
            print(f"  → Füge Produkt {product_id} zu Favoriten hinzu...")
        
        result = api.add_favorite(product_id)
        
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print()
            print(f"✅ Produkt {product_id} zu Favoriten hinzugefügt!")
            print()
        
        return 0
    except ValueError:
        if args.json:
            print(json.dumps({"error": f"Ungültige Produkt-ID: {args.product_id}"}, indent=2))
        else:
            print()
            print(f"❌ Ungültige Produkt-ID: {args.product_id}")
            print()
        return 1
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return 1


def cmd_favorites_remove(args: argparse.Namespace) -> int:
    """Handle favorites remove command - remove a product from favorites."""
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
        product_id = int(args.product_id)
        
        if not args.json:
            print()
            print(f"  → Entferne Produkt {product_id} aus Favoriten...")
        
        result = api.remove_favorite(product_id)
        
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print()
            print(f"✅ Produkt {product_id} aus Favoriten entfernt!")
            print()
        
        return 0
    except ValueError:
        if args.json:
            print(json.dumps({"error": f"Ungültige Produkt-ID: {args.product_id}"}, indent=2))
        else:
            print()
            print(f"❌ Ungültige Produkt-ID: {args.product_id}")
            print()
        return 1
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return 1


# ─────────────────────────────────────────────────────────────────────────────
# Shell Completion
# ─────────────────────────────────────────────────────────────────────────────

BASH_COMPLETION = '''
_knuspr_completion() {
    local cur prev words cword
    _init_completion || return

    local commands="login logout status setup search product filters favorites rette cart slots slot delivery orders order account frequent meals completion"
    local cart_cmds="show add remove open"
    local slot_cmds="reserve status cancel"
    local favorites_cmds="list add remove"

    # Get the main command and subcommand
    local cmd="" subcmd=""
    for ((i=1; i < cword; i++)); do
        if [[ "${words[i]}" != -* ]]; then
            if [[ -z "$cmd" ]]; then
                cmd="${words[i]}"
            elif [[ -z "$subcmd" ]]; then
                subcmd="${words[i]}"
                break
            fi
        fi
    done

    # Complete options if current word starts with -
    if [[ "${cur}" == -* ]]; then
        case "$cmd" in
            search) COMPREPLY=($(compgen -W "--limit -n --favorites --expiring --rette --json --help" -- "${cur}")) ;;
            product) COMPREPLY=($(compgen -W "--json --help" -- "${cur}")) ;;
            favorites) COMPREPLY=($(compgen -W "--json --help" -- "${cur}")) ;;
            rette) COMPREPLY=($(compgen -W "--json --help" -- "${cur}")) ;;
            cart)
                case "$subcmd" in
                    show) COMPREPLY=($(compgen -W "--json --help" -- "${cur}")) ;;
                    add) COMPREPLY=($(compgen -W "--quantity -q --json --help" -- "${cur}")) ;;
                    remove) COMPREPLY=($(compgen -W "--json --help" -- "${cur}")) ;;
                    *) COMPREPLY=($(compgen -W "--help" -- "${cur}")) ;;
                esac ;;
            slots) COMPREPLY=($(compgen -W "--detailed --json --help" -- "${cur}")) ;;
            slot) COMPREPLY=($(compgen -W "--json --help" -- "${cur}")) ;;
            orders) COMPREPLY=($(compgen -W "--limit -n --json --help" -- "${cur}")) ;;
            order) COMPREPLY=($(compgen -W "--json --help" -- "${cur}")) ;;
            account) COMPREPLY=($(compgen -W "--json --help" -- "${cur}")) ;;
            frequent) COMPREPLY=($(compgen -W "--limit -n --json --help" -- "${cur}")) ;;
            meals) COMPREPLY=($(compgen -W "--count -c --orders -o --json --help" -- "${cur}")) ;;
            login) COMPREPLY=($(compgen -W "--email -e --password -p --help" -- "${cur}")) ;;
            setup) COMPREPLY=($(compgen -W "--reset --help" -- "${cur}")) ;;
            *) COMPREPLY=($(compgen -W "--help" -- "${cur}")) ;;
        esac
        return
    fi

    # Complete commands and subcommands
    case "${cword}" in
        1)
            COMPREPLY=($(compgen -W "${commands}" -- "${cur}"))
            ;;
        *)
            if [[ -z "$subcmd" ]]; then
                case "$cmd" in
                    cart) COMPREPLY=($(compgen -W "${cart_cmds}" -- "${cur}")) ;;
                    slot) COMPREPLY=($(compgen -W "${slot_cmds}" -- "${cur}")) ;;
                    favorites) COMPREPLY=($(compgen -W "${favorites_cmds}" -- "${cur}")) ;;
                    completion) COMPREPLY=($(compgen -W "bash zsh fish" -- "${cur}")) ;;
                    meals) COMPREPLY=($(compgen -W "breakfast lunch dinner snack baking drinks healthy" -- "${cur}")) ;;
                esac
            fi
            ;;
    esac
}

complete -F _knuspr_completion knuspr
'''

ZSH_COMPLETION = '''
#compdef knuspr

_knuspr() {
    local curcontext="$curcontext" state line
    typeset -A opt_args

    _arguments -C \\
        '1: :->command' \\
        '*:: :->args'

    case "$state" in
        command)
            local -a commands
            commands=(
                'login:Bei Knuspr.de einloggen'
                'logout:Ausloggen'
                'status:Login-Status anzeigen'
                'setup:Präferenzen einrichten'
                'search:Produkte suchen'
                'filters:Verfügbare Filter anzeigen'
                'product:Produktdetails anzeigen'
                'favorites:Favoriten verwalten'
                'rette:Rette-Lebensmittel anzeigen'
                'cart:Warenkorb verwalten'
                'slots:Lieferzeitfenster anzeigen'
                'slot:Slot reservieren/verwalten'
                'delivery:Lieferinfos anzeigen'
                'orders:Bestellhistorie anzeigen'
                'order:Bestelldetails anzeigen'
                'account:Account-Info anzeigen'
                'frequent:Häufig gekaufte Produkte'
                'meals:Mahlzeitvorschläge'
                'completion:Shell-Completion ausgeben'
            )
            _describe 'command' commands
            ;;
        args)
            case "$line[1]" in
                cart)
                    _arguments -C '1: :->cart_cmd' '*:: :->cart_args'
                    case "$state" in
                        cart_cmd)
                            local -a cart_cmds
                            cart_cmds=(
                                'show:Warenkorb anzeigen'
                                'add:Produkt hinzufügen'
                                'remove:Produkt entfernen'
                                'open:Im Browser öffnen'
                            )
                            _describe 'cart command' cart_cmds
                            ;;
                        cart_args)
                            case "$line[1]" in
                                add) _arguments '1:product_id' '--quantity[Menge]:quantity' '-q[Menge]:quantity' '--json[JSON-Ausgabe]' ;;
                                remove) _arguments '1:product_id' '--json[JSON-Ausgabe]' ;;
                                show) _arguments '--json[JSON-Ausgabe]' ;;
                            esac
                            ;;
                    esac
                    ;;
                slot)
                    _arguments -C '1: :->slot_cmd' '*:: :->slot_args'
                    case "$state" in
                        slot_cmd)
                            local -a slot_cmds
                            slot_cmds=(
                                'reserve:Slot reservieren'
                                'status:Reservierung anzeigen'
                                'cancel:Reservierung stornieren'
                            )
                            _describe 'slot command' slot_cmds
                            ;;
                        slot_args)
                            case "$line[1]" in
                                reserve) _arguments '1:slot_id' '--json[JSON-Ausgabe]' ;;
                                *) _arguments '--json[JSON-Ausgabe]' ;;
                            esac
                            ;;
                    esac
                    ;;
                favorites)
                    _arguments -C '1: :->fav_cmd' '*:: :->fav_args'
                    case "$state" in
                        fav_cmd)
                            local -a fav_cmds
                            fav_cmds=(
                                'list:Favoriten anzeigen'
                                'add:Zu Favoriten hinzufügen'
                                'remove:Aus Favoriten entfernen'
                            )
                            _describe 'favorites command' fav_cmds
                            ;;
                        fav_args)
                            case "$line[1]" in
                                add|remove) _arguments '1:product_id' '--json[JSON-Ausgabe]' ;;
                                list) _arguments '--json[JSON-Ausgabe]' ;;
                            esac
                            ;;
                    esac
                    ;;
                search)
                    _arguments '1:query' '--limit[Anzahl]:limit' '-n[Anzahl]:limit' '--favorites[Nur Favoriten]' '--expiring[Rette-Lebensmittel]' '--rette[Rette-Lebensmittel]' '--json[JSON-Ausgabe]'
                    ;;
                product)
                    _arguments '1:product_id' '--json[JSON-Ausgabe]'
                    ;;
                rette)
                    _arguments '1:filter' '--json[JSON-Ausgabe]'
                    ;;
                slots)
                    _arguments '--detailed[Mit Slot-IDs]' '--json[JSON-Ausgabe]'
                    ;;
                orders)
                    _arguments '--limit[Anzahl]:limit' '-n[Anzahl]:limit' '--json[JSON-Ausgabe]'
                    ;;
                order)
                    _arguments '1:order_id' '--json[JSON-Ausgabe]'
                    ;;
                frequent)
                    _arguments '--limit[Anzahl]:limit' '-n[Anzahl]:limit' '--json[JSON-Ausgabe]'
                    ;;
                meals)
                    _arguments '1:meal_type:(breakfast lunch dinner snack baking drinks healthy)' '--count[Anzahl]:count' '-c[Anzahl]:count' '--orders[Bestellungen]:orders' '-o[Bestellungen]:orders' '--json[JSON-Ausgabe]'
                    ;;
                login)
                    _arguments '--email[E-Mail]:email' '-e[E-Mail]:email' '--password[Passwort]:password' '-p[Passwort]:password'
                    ;;
                setup)
                    _arguments '--reset[Zurücksetzen]'
                    ;;
                completion)
                    _arguments '1:shell:(bash zsh fish)'
                    ;;
            esac
            ;;
    esac
}

compdef _knuspr knuspr
'''

FISH_COMPLETION = '''
# knuspr completions for fish

set -l commands login logout status setup search filters product favorites rette cart slots slot delivery orders order account frequent meals completion
set -l cart_cmds show add remove open
set -l slot_cmds reserve status cancel
set -l favorites_cmds list add remove

complete -c knuspr -f
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "login" -d "Bei Knuspr.de einloggen"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "logout" -d "Ausloggen"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "status" -d "Login-Status"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "setup" -d "Präferenzen einrichten"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "search" -d "Produkte suchen"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "filters" -d "Verfügbare Filter"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "product" -d "Produktdetails"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "favorites" -d "Favoriten verwalten"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "rette" -d "Rette-Lebensmittel"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "cart" -d "Warenkorb"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "slots" -d "Lieferzeitfenster"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "slot" -d "Slot reservieren"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "delivery" -d "Lieferinfos"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "orders" -d "Bestellhistorie"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "order" -d "Bestelldetails"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "account" -d "Account-Info"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "frequent" -d "Häufig gekauft"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "meals" -d "Mahlzeitvorschläge"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "completion" -d "Shell-Completion"

# cart subcommands
complete -c knuspr -n "__fish_seen_subcommand_from cart; and not __fish_seen_subcommand_from $cart_cmds" -a "show" -d "Anzeigen"
complete -c knuspr -n "__fish_seen_subcommand_from cart; and not __fish_seen_subcommand_from $cart_cmds" -a "add" -d "Hinzufügen"
complete -c knuspr -n "__fish_seen_subcommand_from cart; and not __fish_seen_subcommand_from $cart_cmds" -a "remove" -d "Entfernen"
complete -c knuspr -n "__fish_seen_subcommand_from cart; and not __fish_seen_subcommand_from $cart_cmds" -a "open" -d "Im Browser öffnen"
complete -c knuspr -n "__fish_seen_subcommand_from cart; and __fish_seen_subcommand_from add" -l quantity -s q -d "Menge"

# slot subcommands
complete -c knuspr -n "__fish_seen_subcommand_from slot; and not __fish_seen_subcommand_from $slot_cmds" -a "reserve" -d "Reservieren"
complete -c knuspr -n "__fish_seen_subcommand_from slot; and not __fish_seen_subcommand_from $slot_cmds" -a "status" -d "Status anzeigen"
complete -c knuspr -n "__fish_seen_subcommand_from slot; and not __fish_seen_subcommand_from $slot_cmds" -a "cancel" -d "Stornieren"

# favorites subcommands
complete -c knuspr -n "__fish_seen_subcommand_from favorites; and not __fish_seen_subcommand_from $favorites_cmds" -a "list" -d "Anzeigen"
complete -c knuspr -n "__fish_seen_subcommand_from favorites; and not __fish_seen_subcommand_from $favorites_cmds" -a "add" -d "Hinzufügen"
complete -c knuspr -n "__fish_seen_subcommand_from favorites; and not __fish_seen_subcommand_from $favorites_cmds" -a "remove" -d "Entfernen"

# search options
complete -c knuspr -n "__fish_seen_subcommand_from search" -l limit -s n -d "Anzahl Ergebnisse"
complete -c knuspr -n "__fish_seen_subcommand_from search" -l favorites -d "Nur Favoriten"
complete -c knuspr -n "__fish_seen_subcommand_from search" -l expiring -d "Rette-Lebensmittel"
complete -c knuspr -n "__fish_seen_subcommand_from search" -l rette -d "Rette-Lebensmittel"
complete -c knuspr -n "__fish_seen_subcommand_from search" -l json -d "JSON-Ausgabe"

# slots options
complete -c knuspr -n "__fish_seen_subcommand_from slots" -l detailed -d "Mit Slot-IDs"
complete -c knuspr -n "__fish_seen_subcommand_from slots" -l json -d "JSON-Ausgabe"

# orders options
complete -c knuspr -n "__fish_seen_subcommand_from orders" -l limit -s n -d "Anzahl"
complete -c knuspr -n "__fish_seen_subcommand_from orders" -l json -d "JSON-Ausgabe"

# frequent options
complete -c knuspr -n "__fish_seen_subcommand_from frequent" -l limit -s n -d "Anzahl"
complete -c knuspr -n "__fish_seen_subcommand_from frequent" -l json -d "JSON-Ausgabe"

# meals options
complete -c knuspr -n "__fish_seen_subcommand_from meals" -a "breakfast lunch dinner snack baking drinks healthy" -d "Mahlzeittyp"
complete -c knuspr -n "__fish_seen_subcommand_from meals" -l count -s c -d "Anzahl"
complete -c knuspr -n "__fish_seen_subcommand_from meals" -l orders -s o -d "Bestellungen"
complete -c knuspr -n "__fish_seen_subcommand_from meals" -l json -d "JSON-Ausgabe"

# login options
complete -c knuspr -n "__fish_seen_subcommand_from login" -l email -s e -d "E-Mail"
complete -c knuspr -n "__fish_seen_subcommand_from login" -l password -s p -d "Passwort"

# setup options
complete -c knuspr -n "__fish_seen_subcommand_from setup" -l reset -d "Zurücksetzen"

# completion
complete -c knuspr -n "__fish_seen_subcommand_from completion" -a "bash zsh fish" -d "Shell"
'''


def cmd_completion(args) -> int:
    """Output shell completion script."""
    shell = args.shell
    
    if shell == "bash":
        print(BASH_COMPLETION.strip())
    elif shell == "zsh":
        print(ZSH_COMPLETION.strip())
    elif shell == "fish":
        print(FISH_COMPLETION.strip())
    else:
        print(f"❌ Unbekannte Shell: {shell}")
        print("   Unterstützt: bash, zsh, fish")
        return 1
    
    return 0


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
    
    # setup command
    setup_parser = subparsers.add_parser("setup", help="Präferenzen einrichten")
    setup_parser.add_argument("--reset", action="store_true", help="Konfiguration zurücksetzen")
    setup_parser.set_defaults(func=cmd_setup)
    
    # search command
    search_parser = subparsers.add_parser("search", help="Produkte suchen")
    search_parser.add_argument("query", help="Suchbegriff")
    search_parser.add_argument("-n", "--limit", type=int, default=10, help="Anzahl Ergebnisse (Standard: 10)")
    search_parser.add_argument("--favorites", action="store_true", help="Nur Favoriten anzeigen")
    search_parser.add_argument("--expiring", "--rette", action="store_true", 
                               help="Nur 'Rette Lebensmittel' (bald ablaufend, reduziert)")
    search_parser.add_argument("--bio", action="store_true", dest="bio", default=None, help="Nur Bio-Produkte")
    search_parser.add_argument("--no-bio", action="store_false", dest="bio", help="Bio-Filter deaktivieren")
    search_parser.add_argument("--sort", choices=["relevance", "price_asc", "price_desc", "rating"], help="Sortierung")
    search_parser.add_argument("--exclude", nargs="*", help="Begriffe ausschließen")
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
    slots_parser.add_argument("--detailed", "-d", action="store_true", help="Zeige auch 15-Minuten Slots")
    slots_parser.set_defaults(func=cmd_slots)
    
    # slot command (for reserve/status/cancel)
    slot_parser = subparsers.add_parser("slot", help="Slot-Reservierung verwalten")
    slot_subparsers = slot_parser.add_subparsers(dest="slot_command", help="Slot-Befehle")
    
    # slot reserve
    slot_reserve_parser = slot_subparsers.add_parser("reserve", help="Zeitfenster reservieren")
    slot_reserve_parser.add_argument("slot_id", help="Slot-ID (aus 'knuspr slots --detailed')")
    slot_reserve_parser.add_argument("--type", "-t", choices=["ON_TIME", "VIRTUAL"], default="ON_TIME", 
                                     help="Slot-Typ: ON_TIME (15-min) oder VIRTUAL (1-Stunde)")
    slot_reserve_parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    slot_reserve_parser.set_defaults(func=cmd_slot_reserve)
    
    # slot status
    slot_status_parser = slot_subparsers.add_parser("status", help="Aktuelle Reservierung anzeigen")
    slot_status_parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    slot_status_parser.set_defaults(func=cmd_slot_status)
    
    # slot cancel
    slot_cancel_parser = slot_subparsers.add_parser("cancel", help="Reservierung stornieren")
    slot_cancel_parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    slot_cancel_parser.set_defaults(func=cmd_slot_cancel)
    
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
    
    # product command
    product_parser = subparsers.add_parser("product", help="Produkt-Details anzeigen")
    product_parser.add_argument("product_id", help="Produkt-ID")
    product_parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    product_parser.set_defaults(func=cmd_product)
    
    # filters command
    filters_parser = subparsers.add_parser("filters", help="Verfügbare Filter für eine Suche anzeigen")
    filters_parser.add_argument("query", help="Suchbegriff")
    filters_parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    filters_parser.set_defaults(func=cmd_filters)
    
    # rette command
    rette_parser = subparsers.add_parser("rette", help="Alle 'Rette Lebensmittel' anzeigen (bald ablaufend)")
    rette_parser.add_argument("search", nargs="?", help="Optional: Suchbegriff zum Filtern")
    rette_parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    rette_parser.set_defaults(func=cmd_rette)
    
    # meals command
    meals_parser = subparsers.add_parser("meals", help="Mahlzeitvorschläge basierend auf Kaufhistorie")
    meals_parser.add_argument("meal_type", help="Mahlzeittyp: breakfast, lunch, dinner, snack, baking, drinks, healthy")
    meals_parser.add_argument("-c", "--count", type=int, default=10, help="Anzahl Vorschläge (Standard: 10)")
    meals_parser.add_argument("-o", "--orders", type=int, default=5, help="Anzahl Bestellungen zu analysieren (Standard: 5)")
    meals_parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    meals_parser.set_defaults(func=cmd_meals)
    
    # ==================== FAVORITES COMMANDS ====================
    
    # favorites command
    favorites_parser = subparsers.add_parser("favorites", help="Favoriten verwalten")
    favorites_subparsers = favorites_parser.add_subparsers(dest="favorites_command", help="Favoriten-Befehle")
    
    # favorites list (default when no subcommand)
    favorites_list_parser = favorites_subparsers.add_parser("list", help="Alle Favoriten anzeigen")
    favorites_list_parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    favorites_list_parser.set_defaults(func=cmd_favorites_list)
    
    # favorites add
    favorites_add_parser = favorites_subparsers.add_parser("add", help="Produkt zu Favoriten hinzufügen")
    favorites_add_parser.add_argument("product_id", help="Produkt-ID")
    favorites_add_parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    favorites_add_parser.set_defaults(func=cmd_favorites_add)
    
    # favorites remove
    favorites_remove_parser = favorites_subparsers.add_parser("remove", help="Produkt aus Favoriten entfernen")
    favorites_remove_parser.add_argument("product_id", help="Produkt-ID")
    favorites_remove_parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    favorites_remove_parser.set_defaults(func=cmd_favorites_remove)
    
    # completion command
    completion_parser = subparsers.add_parser("completion", help="Shell-Completion ausgeben")
    completion_parser.add_argument("shell", choices=["bash", "zsh", "fish"], help="Shell (bash, zsh, fish)")
    completion_parser.set_defaults(func=cmd_completion)
    
    # Parse and execute
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    if args.command == "cart" and not args.cart_command:
        cart_parser.print_help()
        return 0
    
    if args.command == "slot" and not args.slot_command:
        slot_parser.print_help()
        return 0
    
    if args.command == "favorites" and not args.favorites_command:
        # Default to list when no subcommand
        args.json = False
        return cmd_favorites_list(args)
    
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
