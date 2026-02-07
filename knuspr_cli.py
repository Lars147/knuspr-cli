#!/usr/bin/env python3
"""Knuspr CLI - Einkaufen bei Knuspr.de vom Terminal aus.

REST-ähnliche, AI-Agent-freundliche Struktur.
Rein Python, keine externen Dependencies (nur stdlib).

Nutzung:
    knuspr auth login                 # Einloggen
    knuspr auth status                # Login-Status
    knuspr config set                 # Präferenzen einrichten
    knuspr product search "Milch"     # Produkte suchen
    knuspr product show 123456        # Produktdetails
    knuspr product rette              # Rette Lebensmittel
    knuspr cart show                  # Warenkorb anzeigen
    knuspr cart add 123456            # Produkt hinzufügen
    knuspr slot list                  # Lieferzeitfenster
    knuspr slot reserve 12345         # Slot reservieren
    knuspr order list                 # Bestellhistorie
    knuspr order show 123             # Bestelldetails
    knuspr delivery show              # Lieferinfo
    knuspr account show               # Account-Info
    knuspr favorite list              # Favoriten anzeigen
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

# Exit codes
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_AUTH_ERROR = 2


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
    
    # Mapping from CLI sort names to Knuspr API sortType values
    SORT_TYPE_MAP = {
        "relevance": "orderRecommended",
        "price_asc": "orderPriceAsc",
        "price_desc": "orderPriceDesc",
        "unit_price_asc": "orderUnitPriceAsc",
    }

    def search_products(
        self,
        query: str,
        limit: int = 10,
        favorites_only: bool = False,
        expiring_only: bool = False,
        bio_only: bool = False,
        sort_order: str = "relevance"
    ) -> list[dict[str, Any]]:
        """Search for products."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
        needs_extra = expiring_only or bio_only
        request_limit = limit + 50 if needs_extra else limit + 5
        
        api_filters = []
        
        filter_data: dict[str, Any] = {"filters": api_filters}
        sort_type = self.SORT_TYPE_MAP.get(sort_order)
        if sort_type:
            filter_data["sortType"] = sort_type
        
        params = urllib.parse.urlencode({
            "search": query,
            "offset": "0",
            "limit": str(request_limit),
            "companyId": "1",
            "filterData": json.dumps(filter_data),
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
        
        # Filter expiring products
        if expiring_only:
            products = [
                p for p in products
                if any(
                    badge.get("slug") == "expiring" or badge.get("type") == "EXPIRING"
                    for badge in p.get("badge", [])
                )
            ]
        
        # Filter BIO products
        if bio_only:
            products = [
                p for p in products
                if any(
                    badge.get("slug") == "bio" or badge.get("type") == "bio"
                    for badge in p.get("badge", [])
                )
            ]
        
        # Filter favorites
        if favorites_only:
            products = [p for p in products if p.get("favourite")]
        
        products = products[:limit]
        
        results = []
        for p in products:
            price_info = p.get("price", {})
            
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
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
        response = self._make_request("/services/frontend-service/v2/cart")
        data = response.get("data", {})
        
        items = data.get("items", {})
        products = []
        
        for product_id, item in items.items():
            quantity = item.get("quantity", 0)
            price = item.get("price", 0)
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
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
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
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
        self._make_request(
            f"/services/frontend-service/v2/cart?orderFieldId={order_field_id}",
            method="DELETE"
        )
        return True
    
    def clear_cart(self) -> bool:
        """Clear all items from cart."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
        cart = self.get_cart()
        for product in cart.get("products", []):
            order_field_id = product.get("order_field_id")
            if order_field_id:
                self.remove_from_cart(str(order_field_id))
        return True
    
    def update_cart_quantity(self, order_field_id: str, quantity: int) -> bool:
        """Update quantity of a cart item."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
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
    
    def get_delivery_info(self) -> dict[str, Any]:
        """Get delivery information."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
        response = self._make_request(
            "/services/frontend-service/first-delivery?reasonableDeliveryTime=true"
        )
        return response.get("data", response)
    
    def get_upcoming_orders(self) -> list[dict[str, Any]]:
        """Get upcoming/pending orders."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
        response = self._make_request("/api/v3/orders/upcoming")
        if isinstance(response, list):
            return response
        data = response.get("data", response) if isinstance(response, dict) else response
        return data if isinstance(data, list) else []
    
    def get_order_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get order history."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
        response = self._make_request(f"/api/v3/orders/delivered?offset=0&limit={limit}")
        if isinstance(response, list):
            return response
        data = response.get("data", response) if isinstance(response, dict) else response
        return data if isinstance(data, list) else [data] if data else []
    
    def get_order_detail(self, order_id: str) -> dict[str, Any]:
        """Get details of a specific order."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
        response = self._make_request(f"/api/v3/orders/{order_id}")
        if isinstance(response, dict):
            return response.get("data", response)
        return response
    
    def get_delivery_slots(self) -> list[dict[str, Any]]:
        """Get available delivery time slots."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
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
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
        response = self._make_request("/services/frontend-service/premium/profile")
        if isinstance(response, dict):
            return response.get("data", response)
        return response if response else {}
    
    def get_reusable_bags_info(self) -> dict[str, Any]:
        """Get reusable bags information."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
        response = self._make_request("/api/v1/reusable-bags/user-info")
        if isinstance(response, dict):
            return response.get("data", response)
        return response if response else {}
    
    def get_announcements(self) -> list[dict[str, Any]]:
        """Get announcements."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
        response = self._make_request("/services/frontend-service/announcements/top")
        if isinstance(response, list):
            return response
        data = response.get("data", response) if isinstance(response, dict) else response
        return data if isinstance(data, list) else []
    
    def get_current_reservation(self) -> Optional[dict[str, Any]]:
        """Get current timeslot reservation."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
        try:
            response = self._make_request("/services/frontend-service/v1/timeslot-reservation")
            if isinstance(response, dict):
                return response.get("data", response) if response else None
            return response
        except KnusprAPIError as e:
            if e.status == 404:
                return None
            raise
    
    def reserve_slot(self, slot_id: int, slot_type: str = "ON_TIME") -> dict[str, Any]:
        """Reserve a delivery time slot."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
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
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
        self._make_request(
            "/services/frontend-service/v1/timeslot-reservation",
            method="DELETE"
        )
        return True
    
    def get_available_filters(self, query: str) -> list[dict[str, Any]]:
        """Get available filters for a search query."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
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
        """Get detailed product information."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
        response = self._make_request(f"/api/v1/products/{product_id}/details")
        
        if not response:
            raise KnusprAPIError(f"Produkt {product_id} nicht gefunden")
        
        product = response.get("product", {})
        stock = response.get("stock", {})
        prices = response.get("prices", {})
        
        countries = product.get("countries", [])
        country_name = countries[0].get("name") if countries else None
        country_code = countries[0].get("code") if countries else None
        
        badges = []
        for badge in product.get("badges", []):
            badges.append({
                "type": badge.get("type"),
                "title": badge.get("title"),
                "subtitle": badge.get("subtitle"),
            })
        
        shelf_life = stock.get("shelfLife", {}) or {}
        freshness = stock.get("freshness", {}) or {}
        
        price_obj = prices.get("price", {})
        unit_price_obj = prices.get("pricePerUnit", {})
        
        sales = prices.get("sales", [])
        sale_info = None
        if sales:
            sale = sales[0]
            sale_info = {
                "title": sale.get("title"),
                "original_price": sale.get("originalPrice"),
                "sale_price": sale.get("salePrice"),
            }
        
        story = product.get("productStory")
        story_info = None
        if story:
            story_info = {
                "title": story.get("title"),
                "text": story.get("text"),
            }
        
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
        """Get all 'Rette Lebensmittel' (expiring) products."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
        import re
        
        # Dynamically fetch categories from the Rette Lebensmittel page
        categories: dict[int, str] = {}
        if category_id:
            categories = {category_id: "Unbekannt"}
        else:
            try:
                url = f"{BASE_URL}/rette-lebensmittel"
                headers = self._get_headers()
                headers["Accept"] = "text/html"
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=15) as response:
                    html = response.read().decode("utf-8")
                
                # Extract category IDs and names from page data
                cat_matches = re.findall(r'"categoryId":(\d+),"name":"([^"]*)"', html)
                for cid, cname in cat_matches:
                    cname = cname.replace("\\u0026", "&")
                    categories[int(cid)] = cname
            except Exception:
                pass
            
            if not categories:
                # Fallback to known categories
                categories = {
                    652: "Fleisch & Fisch", 532: "Kühlregal", 663: "Wurst & Schinken",
                    480: "Brot & Gebäck", 2416: "Plant Based", 29: "Kochen & Backen",
                    833: "Baby & Kinder", 4668: "Süßes & Salziges", 4915: "Bistro",
                }
        
        all_product_ids = set()
        
        for cat_id in categories.keys():
            try:
                url = f"{BASE_URL}/rette-lebensmittel/c{cat_id}"
                headers = self._get_headers()
                headers["Accept"] = "text/html"
                
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=15) as response:
                    html = response.read().decode("utf-8")
                
                pids = re.findall(r'"productId":(\d+)', html)
                all_product_ids.update(pids)
            except Exception:
                continue
        
        if not all_product_ids:
            return []
        
        product_ids = list(all_product_ids)
        params = "&".join([f"products={pid}" for pid in product_ids])
        
        try:
            result = self._make_request(f"/api/v1/products/card?{params}&categoryType=last-minute")
        except KnusprAPIError:
            return []
        
        if not isinstance(result, list):
            return []
        
        products = []
        for p in result:
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
    
    def get_favorites(self) -> list[dict[str, Any]]:
        """Get all favorite products."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
        response = self._make_request("/api/v1/categories/favorite/products?limit=500")
        product_ids = response.get("productIds", [])
        
        if not product_ids:
            return []
        
        favorites = []
        batch_size = 50
        
        for i in range(0, len(product_ids), batch_size):
            batch_ids = product_ids[i:i + batch_size]
            ids_param = ",".join(map(str, batch_ids))
            
            try:
                cards = self._make_request(f"/api/v1/products/card?products={ids_param}")
                
                for card in cards:
                    prices = card.get("prices", {})
                    stock = card.get("stock", {})
                    price = prices.get("salePrice") or prices.get("originalPrice")
                    
                    favorites.append({
                        "id": card.get("productId"),
                        "name": card.get("name"),
                        "price": price,
                        "currency": prices.get("currency", "EUR"),
                        "unit_price": prices.get("unitPrice"),
                        "brand": card.get("brand"),
                        "amount": card.get("textualAmount"),
                        "in_stock": stock.get("availabilityStatus") == "AVAILABLE",
                        "image": card.get("image", {}).get("path") if isinstance(card.get("image"), dict) else card.get("image"),
                    })
            except KnusprAPIError:
                for pid in batch_ids:
                    try:
                        card = self._make_request(f"/api/v1/products/{pid}/card")
                        prices = card.get("prices", {})
                        stock = card.get("stock", {})
                        price = prices.get("salePrice") or prices.get("originalPrice")
                        
                        favorites.append({
                            "id": card.get("productId"),
                            "name": card.get("name"),
                            "price": price,
                            "currency": prices.get("currency", "EUR"),
                            "unit_price": prices.get("unitPrice"),
                            "brand": card.get("brand"),
                            "amount": card.get("textualAmount"),
                            "in_stock": stock.get("availabilityStatus") == "AVAILABLE",
                            "image": card.get("image", {}).get("path") if isinstance(card.get("image"), dict) else card.get("image"),
                        })
                    except KnusprAPIError:
                        continue
        
        return sorted(favorites, key=lambda p: (p.get("name") or "").lower())
    
    def add_favorite(self, product_id: int) -> dict[str, Any]:
        """Add a product to favorites."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
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
        """Remove a product from favorites."""
        if not self.is_logged_in():
            raise KnusprAPIError("Not logged in. Run 'knuspr auth login' first.")
        
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


# ─────────────────────────────────────────────────────────────────────────────
# Utility Functions
# ─────────────────────────────────────────────────────────────────────────────

def load_credentials() -> tuple[Optional[str], Optional[str]]:
    """Load credentials from file or environment."""
    email = os.environ.get("KNUSPR_EMAIL")
    password = os.environ.get("KNUSPR_PASSWORD")
    if email and password:
        return email, password
    
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
    """Load user configuration."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_config(config: dict[str, Any]) -> None:
    """Save user configuration."""
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
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M")
    except:
        return date_str


def check_auth(api: KnusprAPI, json_output: bool = False) -> Optional[int]:
    """Check authentication. Returns exit code if not logged in, None otherwise."""
    if not api.is_logged_in():
        if json_output:
            print(json.dumps({"error": "Nicht eingeloggt", "code": EXIT_AUTH_ERROR}, indent=2))
        else:
            print()
            print("❌ Nicht eingeloggt. Führe 'knuspr auth login' aus.")
            print()
        return EXIT_AUTH_ERROR
    return None


# ─────────────────────────────────────────────────────────────────────────────
# AUTH Commands
# ─────────────────────────────────────────────────────────────────────────────

def cmd_auth_login(args: argparse.Namespace) -> int:
    """Handle auth login command."""
    api = KnusprAPI()
    
    if api.is_logged_in():
        if args.json:
            print(json.dumps({"status": "already_logged_in", "user_id": api.user_id}, indent=2))
        else:
            print()
            print("✅ Bereits eingeloggt!")
            print(f"   User ID: {api.user_id}")
            print()
            print("   Zum erneuten Einloggen erst 'knuspr auth logout' ausführen.")
            print()
        return EXIT_OK
    
    if not args.json:
        print()
        print("╔═══════════════════════════════════════════════════════════╗")
        print("║  🛒 KNUSPR LOGIN                                          ║")
        print("╚═══════════════════════════════════════════════════════════╝")
        print()
    
    email, password = load_credentials()
    
    if getattr(args, 'email', None):
        email = args.email
    if getattr(args, 'password', None):
        password = args.password
    
    if not args.json:
        if not email:
            email = input("📧 E-Mail: ").strip()
        else:
            print(f"📧 E-Mail: {email}")
        
        if not password:
            password = getpass.getpass("🔑 Passwort: ")
        else:
            print("🔑 Passwort: ********")
    
    if not email or not password:
        if args.json:
            print(json.dumps({"error": "E-Mail und Passwort werden benötigt"}, indent=2))
        else:
            print()
            print("❌ E-Mail und Passwort werden benötigt!")
        return EXIT_ERROR
    
    if not args.json:
        print()
        print("  → Verbinde mit Knuspr.de...")
    
    try:
        result = api.login(email, password)
        if args.json:
            print(json.dumps({"status": "success", **result}, indent=2))
        else:
            print("  → Authentifizierung erfolgreich...")
            print("  → Speichere Session...")
            print()
            print(f"✅ Eingeloggt als {result['name']} ({result['email']})")
            print(f"   User ID: {result['user_id']}")
            if result['address_id']:
                print(f"   Adresse ID: {result['address_id']}")
            print()
        return EXIT_OK
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Login fehlgeschlagen: {e}")
            print()
        return EXIT_AUTH_ERROR


def cmd_auth_logout(args: argparse.Namespace) -> int:
    """Handle auth logout command."""
    api = KnusprAPI()
    
    if not api.is_logged_in():
        if args.json:
            print(json.dumps({"status": "not_logged_in"}, indent=2))
        else:
            print()
            print("ℹ️  Nicht eingeloggt.")
            print()
        return EXIT_OK
    
    api.logout()
    
    if args.json:
        print(json.dumps({"status": "logged_out"}, indent=2))
    else:
        print()
        print("✅ Ausgeloggt und Session gelöscht.")
        print()
    return EXIT_OK


def cmd_auth_status(args: argparse.Namespace) -> int:
    """Handle auth status command."""
    api = KnusprAPI()
    
    if args.json:
        print(json.dumps({
            "logged_in": api.is_logged_in(),
            "user_id": api.user_id,
            "address_id": api.address_id,
            "session_file": str(SESSION_FILE),
        }, indent=2))
    else:
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
            print("   Führe 'knuspr auth login' aus um dich einzuloggen.")
        print()
    return EXIT_OK


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG Commands
# ─────────────────────────────────────────────────────────────────────────────

def cmd_config_show(args: argparse.Namespace) -> int:
    """Handle config show command."""
    config = load_config()
    
    if args.json:
        print(json.dumps(config, indent=2, ensure_ascii=False))
    else:
        print()
        print("╔═══════════════════════════════════════════════════════════╗")
        print("║  ⚙️  KNUSPR KONFIGURATION                                  ║")
        print("╚═══════════════════════════════════════════════════════════╝")
        print()
        
        if not config:
            print("   ℹ️  Keine Konfiguration gesetzt.")
            print()
            print("   💡 Tipp: Führe 'knuspr config set' aus um Präferenzen zu setzen.")
            print()
        else:
            bio_status = "✅ Ja" if config.get("prefer_bio") else "❌ Nein"
            print(f"   🌿 Bio bevorzugen:      {bio_status}")
            
            sort_names = {
                "relevance": "Empfohlen",
                "price_asc": "Preis aufsteigend",
                "unit_price_asc": "Preis pro Einheit aufsteigend",
                "price_desc": "Preis absteigend",
            }
            sort_name = sort_names.get(config.get("default_sort", "relevance"), "Relevanz")
            print(f"   📊 Standard-Sortierung: {sort_name}")
            
            exclusions = config.get("exclusions", [])
            if exclusions:
                print(f"   🚫 Ausschlüsse:         {', '.join(exclusions)}")
            else:
                print(f"   🚫 Ausschlüsse:         Keine")
            
            print()
            print(f"   💾 Datei: {CONFIG_FILE}")
            print()
    return EXIT_OK


def cmd_config_set(args: argparse.Namespace) -> int:
    """Handle config set command - interactive onboarding."""
    print()
    print("╔═══════════════════════════════════════════════════════════╗")
    print("║  ⚙️  KNUSPR KONFIGURATION                                  ║")
    print("╚═══════════════════════════════════════════════════════════╝")
    print()
    print("   Richte deine Präferenzen ein für bessere Suchergebnisse!")
    print()
    print("─" * 60)
    print()
    
    config = load_config()
    
    # Bio preference
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
    
    # Default sorting
    print("📊 Standard-Sortierung für Suchergebnisse:")
    print()
    print("   1. Relevanz (Standard)")
    print("   2. Preis aufsteigend (günstigste zuerst)")
    print("   3. Preis absteigend (teuerste zuerst)")
    print("   4. Bewertung (beste zuerst)")
    print()
    
    sort_options = {"1": "relevance", "2": "price_asc", "3": "unit_price_asc", "4": "price_desc"}
    sort_names = {"relevance": "Empfohlen", "price_asc": "Preis aufsteigend", "unit_price_asc": "Preis pro Einheit aufsteigend", "price_desc": "Preis absteigend"}
    
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
    
    # Exclusions
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
    
    save_config(config)
    
    # Summary
    print("─" * 60)
    print()
    print("✅ Konfiguration gespeichert!")
    print()
    
    bio_status = "✅ Ja" if config.get("prefer_bio") else "❌ Nein"
    print(f"   🌿 Bio bevorzugen:      {bio_status}")
    
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
    
    return EXIT_OK


def cmd_config_reset(args: argparse.Namespace) -> int:
    """Handle config reset command."""
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()
        if args.json:
            print(json.dumps({"status": "reset"}, indent=2))
        else:
            print()
            print("✅ Konfiguration zurückgesetzt.")
            print()
    else:
        if args.json:
            print(json.dumps({"status": "no_config"}, indent=2))
        else:
            print()
            print("ℹ️  Keine Konfiguration vorhanden.")
            print()
    return EXIT_OK


# ─────────────────────────────────────────────────────────────────────────────
# ACCOUNT Commands
# ─────────────────────────────────────────────────────────────────────────────

def cmd_account_show(args: argparse.Namespace) -> int:
    """Handle account show command."""
    api = KnusprAPI()
    
    if exit_code := check_auth(api, args.json):
        return exit_code
    
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
        
        result = {"premium": premium, "bags": bags, "announcements": announcements}
        
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print()
            print("╔═══════════════════════════════════════════════════════════╗")
            print("║  👤 ACCOUNT INFORMATION                                    ║")
            print("╚═══════════════════════════════════════════════════════════╝")
            print()
            
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
            
            if bags:
                count = bags.get("current") or bags.get("count") or bags.get("bagsCount") or 0
                saved_plastic = bags.get("savedPlastic") or bags.get("plasticSaved") or 0
                
                print(f"   ♻️  Mehrwegtaschen: {count}")
                if saved_plastic > 0:
                    print(f"   🌱 Plastik gespart: {saved_plastic}g")
                print()
            
            if announcements and len(announcements) > 0:
                print(f"   📢 Ankündigungen ({len(announcements)}):")
                print()
                for ann in announcements[:5]:
                    title = ann.get("title") or ann.get("headline") or "Ankündigung"
                    message = ann.get("message") or ann.get("content") or ""
                    print(f"      • {title}")
                    if message:
                        if len(message) > 80:
                            message = message[:80] + "..."
                        print(f"        {message}")
                    print()
            else:
                print("   📢 Keine Ankündigungen.")
                print()
        
        return EXIT_OK
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return EXIT_ERROR


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT Commands
# ─────────────────────────────────────────────────────────────────────────────

def cmd_product_search(args: argparse.Namespace) -> int:
    """Handle product search command."""
    api = KnusprAPI()
    
    if exit_code := check_auth(api, args.json):
        return exit_code
    
    config = load_config()
    show_setup_hint = not config and not args.json
    
    expiring_only = getattr(args, 'rette', False)
    
    try:
        if not args.json:
            print()
            if expiring_only:
                print(f"🥬 Rette Lebensmittel: '{args.query}'")
            else:
                print(f"🔍 Suche in Knuspr: '{args.query}'")
            print("─" * 50)
        
        prefer_bio = getattr(args, 'bio', None)
        if prefer_bio is None:
            prefer_bio = config.get("prefer_bio", False)
        
        sort_order = getattr(args, 'sort', None)
        if sort_order is None:
            sort_order = config.get("default_sort", "relevance")
        
        results = api.search_products(
            args.query,
            limit=args.limit,
            favorites_only=getattr(args, 'favorites', False),
            expiring_only=expiring_only,
            bio_only=prefer_bio,
            sort_order=sort_order
        )
        
        exclusions = getattr(args, 'exclude', None)
        if exclusions is None:
            exclusions = config.get("exclusions", [])
        
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
        
        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            if not results:
                print(f"Keine Produkte gefunden für '{args.query}'")
                print()
                if show_setup_hint:
                    print("💡 Tipp: Führe 'knuspr config set' aus um Präferenzen zu setzen")
                    print()
                return EXIT_OK
            
            print(f"Gefunden: {len(results)} Produkte")
            if prefer_bio:
                print("   🌿 Nur Bio-Produkte")
            print()
            
            for i, p in enumerate(results, 1):
                stock = "✅" if p["in_stock"] else "❌"
                brand = f" ({p['brand']})" if p['brand'] else ""
                name = p['name']
                name_lower = name.lower()
                brand_lower = (p.get('brand') or '').lower()
                is_bio = "bio" in name_lower or "bio" in brand_lower or "organic" in name_lower
                bio_badge = " 🌿" if is_bio and prefer_bio else ""
                
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
                print("💡 Tipp: Führe 'knuspr config set' aus um Präferenzen zu setzen")
                print()
        
        return EXIT_OK
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return EXIT_ERROR


def cmd_product_show(args: argparse.Namespace) -> int:
    """Handle product show command."""
    api = KnusprAPI()
    
    if exit_code := check_auth(api, args.json):
        return exit_code
    
    try:
        product_id = int(args.product_id)
    except ValueError:
        if args.json:
            print(json.dumps({"error": f"Ungültige Produkt-ID: {args.product_id}"}, indent=2))
        else:
            print()
            print(f"❌ Ungültige Produkt-ID: {args.product_id}")
            print()
        return EXIT_ERROR
    
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
            
            name = product.get("name", "Unbekannt")
            brand = product.get("brand")
            print(f"   🏷️  {name}")
            if brand:
                print(f"   🏭 Marke: {brand}")
            print()
            
            badges = product.get("badges", [])
            if badges:
                badge_str = " ".join([f"[{b.get('title', '?')}]" for b in badges if b.get('title')])
                if badge_str:
                    print(f"   🏅 {badge_str}")
                    print()
            
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
            
            sale = product.get("sale")
            if sale:
                orig = sale.get("original_price")
                sale_price = sale.get("sale_price")
                title = sale.get("title", "Angebot")
                if orig and sale_price:
                    print(f"      🔥 {title}: {sale_price:.2f} € (statt {orig:.2f} €)")
            print()
            
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
            
            country = product.get("country")
            if country:
                country_code = product.get("country_code")
                flag = f" ({country_code})" if country_code else ""
                print("   🌍 HERKUNFT")
                print("   ─────────────────────────────────")
                print(f"      {country}{flag}")
                print()
            
            print(f"   🔗 Produkt-ID: {product.get('id')}")
            slug = product.get("slug")
            if slug:
                print(f"   🌐 https://www.knuspr.de/{product.get('id')}-{slug}")
            print()
        
        return EXIT_OK
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return EXIT_ERROR


def cmd_product_filters(args: argparse.Namespace) -> int:
    """Handle product filters command."""
    api = KnusprAPI()
    
    if exit_code := check_auth(api, args.json):
        return exit_code
    
    try:
        filter_groups = api.get_available_filters(args.query)
        
        if args.json:
            print(json.dumps(filter_groups, indent=2, ensure_ascii=False))
            return EXIT_OK
        
        print()
        print(f"🔍 Verfügbare Filter für: '{args.query}'")
        print("─" * 50)
        print()
        
        for group in filter_groups:
            title = group.get("title") or group.get("tag", "").upper()
            options = group.get("options", [])
            
            if not options:
                continue
            
            print(f"📁 {title}")
            
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
        
        return EXIT_OK
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return EXIT_ERROR


def cmd_product_rette(args: argparse.Namespace) -> int:
    """Handle product rette command."""
    api = KnusprAPI()
    
    if exit_code := check_auth(api, args.json):
        return exit_code
    
    search_term = getattr(args, 'query', None)
    
    try:
        if not args.json:
            print()
            print("╔═══════════════════════════════════════════════════════════╗")
            print("║  🥬 RETTE LEBENSMITTEL                                     ║")
            print("╚═══════════════════════════════════════════════════════════╝")
            print()
            print("   → Lade Produkte...")
        
        products = api.get_rette_products()
        
        if search_term and products:
            search_lower = search_term.lower()
            products = [
                p for p in products
                if search_lower in (p.get("name") or "").lower()
                or search_lower in (p.get("brand") or "").lower()
            ]
        
        # Apply limit
        limit = getattr(args, 'limit', 20)
        products = products[:limit]
        
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
                return EXIT_OK
            
            if search_term:
                print(f"   Gefunden: {len(products)} Produkte für '{search_term}'")
            else:
                print(f"   Gefunden: {len(products)} Produkte")
            print()
            
            for i, p in enumerate(products, 1):
                stock = "✅" if p["in_stock"] else "❌"
                brand = f" ({p['brand']})" if p.get('brand') else ""
                name = p['name'] or "?"
                
                discount = p.get('discount', '')
                discount_str = f" {discount}" if discount else ""
                
                price = p.get('price') or 0
                orig = p.get('original_price')
                if orig and orig != price:
                    price_str = f"💰 {price:.2f} € (statt {orig:.2f} €)"
                else:
                    price_str = f"💰 {price:.2f} €"
                
                print(f"  {i:2}. {name}{brand}{discount_str}")
                
                expiry = p.get('expiry', '')
                if expiry:
                    print(f"      ⏰ {expiry}")
                
                print(f"      {price_str}  │  📦 {p.get('amount', '?')}  │  {stock}")
                print(f"      ID: {p['id']}")
                print()
        
        return EXIT_OK
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return EXIT_ERROR


# ─────────────────────────────────────────────────────────────────────────────
# FAVORITE Commands
# ─────────────────────────────────────────────────────────────────────────────

def cmd_favorite_list(args: argparse.Namespace) -> int:
    """Handle favorite list command."""
    api = KnusprAPI()
    
    if exit_code := check_auth(api, args.json):
        return exit_code
    
    try:
        if not args.json:
            print()
            print("╔═══════════════════════════════════════════════════════════╗")
            print("║  ⭐ FAVORITEN                                              ║")
            print("╚═══════════════════════════════════════════════════════════╝")
            print()
            print("   → Lade Favoriten...")
        
        favorites = api.get_favorites()
        
        # Apply limit
        limit = getattr(args, 'limit', 50)
        favorites = favorites[:limit]
        
        if args.json:
            print(json.dumps(favorites, indent=2, ensure_ascii=False))
        else:
            print()
            if not favorites:
                print("   ℹ️  Keine Favoriten gefunden.")
                print()
                print("   💡 Tipp: Füge Favoriten hinzu mit 'knuspr favorite add <id>'")
                print()
                return EXIT_OK
            
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
        
        return EXIT_OK
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return EXIT_ERROR


def cmd_favorite_add(args: argparse.Namespace) -> int:
    """Handle favorite add command."""
    api = KnusprAPI()
    
    if exit_code := check_auth(api, args.json):
        return exit_code
    
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
        
        return EXIT_OK
    except ValueError:
        if args.json:
            print(json.dumps({"error": f"Ungültige Produkt-ID: {args.product_id}"}, indent=2))
        else:
            print()
            print(f"❌ Ungültige Produkt-ID: {args.product_id}")
            print()
        return EXIT_ERROR
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return EXIT_ERROR


def cmd_favorite_remove(args: argparse.Namespace) -> int:
    """Handle favorite remove command."""
    api = KnusprAPI()
    
    if exit_code := check_auth(api, args.json):
        return exit_code
    
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
        
        return EXIT_OK
    except ValueError:
        if args.json:
            print(json.dumps({"error": f"Ungültige Produkt-ID: {args.product_id}"}, indent=2))
        else:
            print()
            print(f"❌ Ungültige Produkt-ID: {args.product_id}")
            print()
        return EXIT_ERROR
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return EXIT_ERROR


# ─────────────────────────────────────────────────────────────────────────────
# CART Commands
# ─────────────────────────────────────────────────────────────────────────────

def cmd_cart_show(args: argparse.Namespace) -> int:
    """Handle cart show command."""
    api = KnusprAPI()
    
    if exit_code := check_auth(api, args.json):
        return exit_code
    
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
                return EXIT_OK
            
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
        
        return EXIT_OK
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return EXIT_ERROR


def cmd_cart_add(args: argparse.Namespace) -> int:
    """Handle cart add command."""
    api = KnusprAPI()
    
    if exit_code := check_auth(api, args.json):
        return exit_code
    
    try:
        product_id = int(args.product_id)
        quantity = getattr(args, 'quantity', 1)
        
        if not args.json:
            print()
            print(f"  → Füge Produkt {product_id} hinzu...")
        
        api.add_to_cart(product_id, quantity)
        
        if args.json:
            print(json.dumps({"status": "added", "product_id": product_id, "quantity": quantity}, indent=2))
        else:
            print()
            print(f"✅ Produkt hinzugefügt (ID: {product_id}, Menge: {quantity})")
            print()
        return EXIT_OK
    except ValueError:
        if args.json:
            print(json.dumps({"error": f"Ungültige Produkt-ID: {args.product_id}"}, indent=2))
        else:
            print()
            print(f"❌ Ungültige Produkt-ID: {args.product_id}")
            print()
        return EXIT_ERROR
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return EXIT_ERROR


def cmd_cart_remove(args: argparse.Namespace) -> int:
    """Handle cart remove command."""
    api = KnusprAPI()
    
    if exit_code := check_auth(api, args.json):
        return exit_code
    
    try:
        if not args.json:
            print()
            print(f"  → Suche Produkt {args.product_id}...")
        
        cart = api.get_cart()
        
        order_field_id = None
        product_name = None
        for p in cart["products"]:
            if str(p["id"]) == str(args.product_id):
                order_field_id = p["order_field_id"]
                product_name = p["name"]
                break
        
        if not order_field_id:
            order_field_id = args.product_id
        
        if not args.json:
            print(f"  → Entferne aus Warenkorb...")
        
        api.remove_from_cart(str(order_field_id))
        
        if args.json:
            print(json.dumps({"status": "removed", "product_id": args.product_id}, indent=2))
        else:
            print()
            if product_name:
                print(f"✅ Entfernt: {product_name}")
            else:
                print(f"✅ Produkt entfernt")
            print()
        return EXIT_OK
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return EXIT_ERROR


def cmd_cart_clear(args: argparse.Namespace) -> int:
    """Handle cart clear command."""
    api = KnusprAPI()
    
    if exit_code := check_auth(api, args.json):
        return exit_code
    
    try:
        if not args.json:
            print()
            print("  → Leere Warenkorb...")
        
        api.clear_cart()
        
        if args.json:
            print(json.dumps({"status": "cleared"}, indent=2))
        else:
            print()
            print("✅ Warenkorb geleert!")
            print()
        return EXIT_OK
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return EXIT_ERROR


def cmd_cart_open(args: argparse.Namespace) -> int:
    """Handle cart open command."""
    url = f"{BASE_URL}/bestellung/mein-warenkorb"
    
    if args.json:
        print(json.dumps({"url": url}, indent=2))
    else:
        print()
        print(f"  → Öffne {url}...")
        webbrowser.open(url)
        print()
        print("✅ Warenkorb im Browser geöffnet")
        print()
    return EXIT_OK


# ─────────────────────────────────────────────────────────────────────────────
# SLOT Commands
# ─────────────────────────────────────────────────────────────────────────────

def cmd_slot_list(args: argparse.Namespace) -> int:
    """Handle slot list command."""
    api = KnusprAPI()
    
    if exit_code := check_auth(api, args.json):
        return exit_code
    
    try:
        raw_slots = api.get_delivery_slots()
        
        if args.json:
            print(json.dumps(raw_slots, indent=2, ensure_ascii=False))
            return EXIT_OK
        
        print()
        print("╔═══════════════════════════════════════════════════════════╗")
        print("║  📅 LIEFERZEITFENSTER                                      ║")
        print("╚═══════════════════════════════════════════════════════════╝")
        print()
        
        if not raw_slots:
            print("   ℹ️  Keine Lieferzeitfenster verfügbar.")
            print()
            return EXIT_OK
        
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
            return EXIT_OK
        
        # Apply limit
        limit = getattr(args, 'limit', 5)
        detailed = getattr(args, 'detailed', False)
        max_days = limit if detailed else min(limit, 5)
        
        for day_info in all_days[:max_days]:
            date = day_info["date"]
            label = day_info["label"]
            slots = day_info["slots"]
            
            date_display = label if label else format_date(date)
            print(f"   📅 {date_display} ({date})")
            print()
            
            if detailed:
                display_slots = sorted(slots, key=lambda s: s.get("since", ""))
            else:
                display_slots = [s for s in slots if s.get("type") == "VIRTUAL"]
                if not display_slots:
                    display_slots = slots[:12]
            
            for slot in display_slots:
                time_window = slot.get("timeWindow", "")
                price = slot.get("price", 0)
                capacity = slot.get("capacity", "")
                eco = "🌿" if slot.get("eco") else ""
                premium = "⭐" if slot.get("premium") else ""
                
                capacity_dto = slot.get("timeSlotCapacityDTO", {})
                capacity_percent = capacity_dto.get("totalFreeCapacityPercent", 0)
                capacity_msg = capacity_dto.get("capacityMessage", "")
                
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
        
        return EXIT_OK
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return EXIT_ERROR


def cmd_slot_reserve(args: argparse.Namespace) -> int:
    """Handle slot reserve command."""
    api = KnusprAPI()
    
    if exit_code := check_auth(api, args.json):
        return exit_code
    
    try:
        slot_id = int(args.slot_id)
        slot_type = getattr(args, 'type', 'ON_TIME').upper()
        
        if not args.json:
            print()
            print(f"  → Reserviere Slot {slot_id} ({slot_type})...")
        
        api.reserve_slot(slot_id, slot_type)
        reservation = api.get_current_reservation()
        
        if args.json:
            print(json.dumps(reservation or {"success": True, "slotId": slot_id}, indent=2, ensure_ascii=False))
        else:
            print()
            print("╔═══════════════════════════════════════════════════════════╗")
            print("║  ✅ SLOT RESERVIERT                                        ║")
            print("╚═══════════════════════════════════════════════════════════╝")
            print()
            
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
        
        return EXIT_OK
    except ValueError:
        if args.json:
            print(json.dumps({"error": f"Ungültige Slot-ID: {args.slot_id}"}, indent=2))
        else:
            print()
            print(f"❌ Ungültige Slot-ID: {args.slot_id}")
            print()
        return EXIT_ERROR
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return EXIT_ERROR


def cmd_slot_release(args: argparse.Namespace) -> int:
    """Handle slot release command."""
    api = KnusprAPI()
    
    if exit_code := check_auth(api, args.json):
        return exit_code
    
    try:
        reservation = api.get_current_reservation()
        
        if not reservation:
            if args.json:
                print(json.dumps({"message": "Keine aktive Reservierung"}, indent=2))
            else:
                print()
                print("ℹ️  Keine aktive Reservierung zum Stornieren.")
                print()
            return EXIT_OK
        
        if not args.json:
            print()
            print("  → Storniere Reservierung...")
        
        api.cancel_reservation()
        
        if args.json:
            print(json.dumps({"status": "released"}, indent=2))
        else:
            print()
            print("✅ Reservierung storniert.")
            print()
        
        return EXIT_OK
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return EXIT_ERROR


def cmd_slot_current(args: argparse.Namespace) -> int:
    """Handle slot current command."""
    api = KnusprAPI()
    
    if exit_code := check_auth(api, args.json):
        return exit_code
    
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
                print("   💡 Tipp: Nutze 'knuspr slot list --detailed' um verfügbare Zeitfenster zu sehen,")
                print("           dann 'knuspr slot reserve <id>' zum Reservieren.")
                print()
                return EXIT_OK
            
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
        
        return EXIT_OK
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return EXIT_ERROR


# ─────────────────────────────────────────────────────────────────────────────
# ORDER Commands
# ─────────────────────────────────────────────────────────────────────────────

def cmd_order_list(args: argparse.Namespace) -> int:
    """Handle order list command."""
    api = KnusprAPI()
    
    if exit_code := check_auth(api, args.json):
        return exit_code
    
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
                return EXIT_OK
            
            print(f"   Gefunden: {len(orders)} Bestellungen")
            print()
            
            for order in orders:
                order_id = order.get("id") or order.get("orderNumber")
                date = order.get("orderTime") or order.get("deliveredAt") or order.get("createdAt") or ""
                
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
        
        return EXIT_OK
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return EXIT_ERROR


def cmd_order_show(args: argparse.Namespace) -> int:
    """Handle order show command."""
    api = KnusprAPI()
    
    if exit_code := check_auth(api, args.json):
        return exit_code
    
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
                return EXIT_OK
            
            status = order.get("state") or order.get("status") or "Unbekannt"
            date = order.get("orderTime") or order.get("deliveredAt") or order.get("createdAt") or ""
            
            price_comp = order.get("priceComposition", {})
            total_obj = price_comp.get("total", {})
            total_price = total_obj.get("amount", 0) if isinstance(total_obj, dict) else total_obj
            
            status_map = {"DELIVERED": "Geliefert", "PENDING": "In Bearbeitung", "CANCELLED": "Storniert"}
            status_display = status_map.get(status, status)
            
            print(f"   📊 Status: {status_display}")
            print(f"   📅 Datum: {format_date(date)}")
            print(f"   💰 Gesamt: {format_price(total_price)}")
            
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
                    
                    p_price_comp = p.get("priceComposition", {})
                    p_total = p_price_comp.get("total", {})
                    price = p_total.get("amount", 0) if isinstance(p_total, dict) else 0
                    
                    amount_str = f" ({textual_amount})" if textual_amount else ""
                    print(f"      • {name}{amount_str}")
                    print(f"        {qty}× | {format_price(price)}")
                    print()
        
        return EXIT_OK
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return EXIT_ERROR


def cmd_order_repeat(args: argparse.Namespace) -> int:
    """Handle order repeat command - add all items from an order to cart."""
    api = KnusprAPI()
    
    if exit_code := check_auth(api, args.json):
        return exit_code
    
    try:
        if not args.json:
            print()
            print(f"  → Lade Bestellung #{args.order_id}...")
        
        order = api.get_order_detail(args.order_id)
        
        if not order:
            if args.json:
                print(json.dumps({"error": f"Bestellung {args.order_id} nicht gefunden"}, indent=2))
            else:
                print()
                print(f"❌ Bestellung {args.order_id} nicht gefunden.")
                print()
            return EXIT_ERROR
        
        products = order.get("items") or order.get("products") or []
        
        if not products:
            if args.json:
                print(json.dumps({"error": "Keine Produkte in der Bestellung"}, indent=2))
            else:
                print()
                print("❌ Keine Produkte in der Bestellung gefunden.")
                print()
            return EXIT_ERROR
        
        added = []
        failed = []
        
        for p in products:
            product_id = p.get("productId") or p.get("id")
            name = p.get("name") or p.get("productName") or "Unbekannt"
            qty = p.get("amount") or p.get("quantity") or 1
            
            if not product_id:
                failed.append({"name": name, "reason": "Keine Produkt-ID"})
                continue
            
            try:
                if not args.json:
                    print(f"  → Füge hinzu: {name}...")
                api.add_to_cart(int(product_id), qty)
                added.append({"id": product_id, "name": name, "quantity": qty})
            except KnusprAPIError as e:
                failed.append({"name": name, "reason": str(e)})
        
        if args.json:
            print(json.dumps({"added": added, "failed": failed}, indent=2, ensure_ascii=False))
        else:
            print()
            print(f"✅ {len(added)} Produkte zum Warenkorb hinzugefügt!")
            if failed:
                print(f"⚠️  {len(failed)} Produkte konnten nicht hinzugefügt werden:")
                for f in failed:
                    print(f"   • {f['name']}: {f['reason']}")
            print()
        
        return EXIT_OK
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return EXIT_ERROR


# ─────────────────────────────────────────────────────────────────────────────
# DELIVERY Commands
# ─────────────────────────────────────────────────────────────────────────────

def cmd_delivery_show(args: argparse.Namespace) -> int:
    """Handle delivery show command."""
    api = KnusprAPI()
    
    if exit_code := check_auth(api, args.json):
        return exit_code
    
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
        
        result = {"delivery_info": delivery_info, "upcoming_orders": upcoming_orders}
        
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
        
        return EXIT_OK
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return EXIT_ERROR


# ─────────────────────────────────────────────────────────────────────────────
# INSIGHT Commands
# ─────────────────────────────────────────────────────────────────────────────

def cmd_insight_frequent(args: argparse.Namespace) -> int:
    """Handle insight frequent command - show frequently purchased items."""
    api = KnusprAPI()
    
    if exit_code := check_auth(api, args.json):
        return exit_code
    
    try:
        orders_to_analyze = min(20, max(1, args.orders))
        top_items = min(30, max(3, args.limit))
        
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
            return EXIT_OK
        
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
                return EXIT_OK
            
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
        
        return EXIT_OK
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return EXIT_ERROR


def cmd_insight_meals(args: argparse.Namespace) -> int:
    """Handle insight meals command - get meal suggestions based on purchase history."""
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
        return EXIT_ERROR
    
    if exit_code := check_auth(api, args.json):
        return exit_code
    
    try:
        items_count = min(30, max(3, args.limit))
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
            return EXIT_OK
        
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
                return EXIT_OK
            
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
        
        return EXIT_OK
    except KnusprAPIError as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print()
            print(f"❌ Fehler: {e}")
            print()
        return EXIT_ERROR


# ─────────────────────────────────────────────────────────────────────────────
# COMPLETION Commands
# ─────────────────────────────────────────────────────────────────────────────

BASH_COMPLETION = '''
_knuspr_completion() {
    local cur prev words cword
    _init_completion || return

    local commands="auth config account product favorite cart slot order insight delivery completion"
    local auth_cmds="login logout status"
    local config_cmds="show set reset"
    local account_cmds="show"
    local product_cmds="search show filters rette"
    local favorite_cmds="list add remove"
    local cart_cmds="show add remove clear open"
    local slot_cmds="list reserve release current"
    local order_cmds="list show repeat"
    local insight_cmds="frequent meals"
    local delivery_cmds="show"
    local completion_cmds="bash zsh fish"

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

    if [[ "${cur}" == -* ]]; then
        COMPREPLY=($(compgen -W "--json --limit -n --help" -- "${cur}"))
        return
    fi

    case "${cword}" in
        1)
            COMPREPLY=($(compgen -W "${commands}" -- "${cur}"))
            ;;
        *)
            if [[ -z "$subcmd" ]]; then
                case "$cmd" in
                    auth) COMPREPLY=($(compgen -W "${auth_cmds}" -- "${cur}")) ;;
                    config) COMPREPLY=($(compgen -W "${config_cmds}" -- "${cur}")) ;;
                    account) COMPREPLY=($(compgen -W "${account_cmds}" -- "${cur}")) ;;
                    product) COMPREPLY=($(compgen -W "${product_cmds}" -- "${cur}")) ;;
                    favorite) COMPREPLY=($(compgen -W "${favorite_cmds}" -- "${cur}")) ;;
                    cart) COMPREPLY=($(compgen -W "${cart_cmds}" -- "${cur}")) ;;
                    slot) COMPREPLY=($(compgen -W "${slot_cmds}" -- "${cur}")) ;;
                    order) COMPREPLY=($(compgen -W "${order_cmds}" -- "${cur}")) ;;
                    insight) COMPREPLY=($(compgen -W "${insight_cmds}" -- "${cur}")) ;;
                    delivery) COMPREPLY=($(compgen -W "${delivery_cmds}" -- "${cur}")) ;;
                    completion) COMPREPLY=($(compgen -W "${completion_cmds}" -- "${cur}")) ;;
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
                'auth:Authentifizierung (login|logout|status)'
                'config:Konfiguration (show|set|reset)'
                'account:Account-Informationen anzeigen'
                'product:Produkte (search|show|filters|rette)'
                'favorite:Favoriten (list|add|remove)'
                'cart:Warenkorb (show|add|remove|clear|open)'
                'slot:Lieferzeitfenster (list|reserve|release|current)'
                'order:Bestellungen (list|show|repeat)'
                'insight:Einkaufs-Insights (frequent|meals)'
                'delivery:Lieferinformationen anzeigen'
                'completion:Shell-Completion ausgeben'
            )
            _describe 'command' commands
            ;;
        args)
            case "$line[1]" in
                auth)
                    local -a auth_cmds
                    auth_cmds=('login:Einloggen' 'logout:Ausloggen' 'status:Status anzeigen')
                    _describe 'auth command' auth_cmds
                    ;;
                config)
                    local -a config_cmds
                    config_cmds=('show:Konfiguration anzeigen' 'set:Konfiguration setzen' 'reset:Zurücksetzen')
                    _describe 'config command' config_cmds
                    ;;
                account)
                    local -a account_cmds
                    account_cmds=('show:Account-Info anzeigen')
                    _describe 'account command' account_cmds
                    ;;
                product)
                    local -a product_cmds
                    product_cmds=('search:Produkte suchen' 'show:Produkt anzeigen' 'filters:Filter anzeigen' 'rette:Rette Lebensmittel')
                    _describe 'product command' product_cmds
                    ;;
                favorite)
                    local -a favorite_cmds
                    favorite_cmds=('list:Favoriten anzeigen' 'add:Favorit hinzufügen' 'remove:Favorit entfernen')
                    _describe 'favorite command' favorite_cmds
                    ;;
                cart)
                    local -a cart_cmds
                    cart_cmds=('show:Warenkorb anzeigen' 'add:Produkt hinzufügen' 'remove:Produkt entfernen' 'clear:Warenkorb leeren' 'open:Im Browser öffnen')
                    _describe 'cart command' cart_cmds
                    ;;
                slot)
                    local -a slot_cmds
                    slot_cmds=('list:Zeitfenster anzeigen' 'reserve:Reservieren' 'release:Freigeben' 'current:Aktuelle Reservierung')
                    _describe 'slot command' slot_cmds
                    ;;
                order)
                    local -a order_cmds
                    order_cmds=('list:Bestellungen anzeigen' 'show:Bestellung anzeigen' 'repeat:Bestellung wiederholen')
                    _describe 'order command' order_cmds
                    ;;
                insight)
                    local -a insight_cmds
                    insight_cmds=('frequent:Häufig gekaufte Produkte' 'meals:Mahlzeitvorschläge')
                    _describe 'insight command' insight_cmds
                    ;;
                delivery)
                    local -a delivery_cmds
                    delivery_cmds=('show:Lieferinfo anzeigen')
                    _describe 'delivery command' delivery_cmds
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

set -l commands auth config account product favorite cart slot order insight delivery completion

complete -c knuspr -f
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "auth" -d "Authentifizierung"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "config" -d "Konfiguration"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "account" -d "Account-Info"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "product" -d "Produkte"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "favorite" -d "Favoriten"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "cart" -d "Warenkorb"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "slot" -d "Lieferzeitfenster"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "order" -d "Bestellungen"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "insight" -d "Einkaufs-Insights"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "delivery" -d "Lieferinfo"
complete -c knuspr -n "not __fish_seen_subcommand_from $commands" -a "completion" -d "Shell-Completion"

# auth subcommands
complete -c knuspr -n "__fish_seen_subcommand_from auth" -a "login" -d "Einloggen"
complete -c knuspr -n "__fish_seen_subcommand_from auth" -a "logout" -d "Ausloggen"
complete -c knuspr -n "__fish_seen_subcommand_from auth" -a "status" -d "Status anzeigen"

# config subcommands
complete -c knuspr -n "__fish_seen_subcommand_from config" -a "show" -d "Anzeigen"
complete -c knuspr -n "__fish_seen_subcommand_from config" -a "set" -d "Setzen"
complete -c knuspr -n "__fish_seen_subcommand_from config" -a "reset" -d "Zurücksetzen"

# account subcommands
complete -c knuspr -n "__fish_seen_subcommand_from account" -a "show" -d "Account anzeigen"

# product subcommands
complete -c knuspr -n "__fish_seen_subcommand_from product" -a "search" -d "Suchen"
complete -c knuspr -n "__fish_seen_subcommand_from product" -a "show" -d "Details anzeigen"
complete -c knuspr -n "__fish_seen_subcommand_from product" -a "filters" -d "Filter anzeigen"
complete -c knuspr -n "__fish_seen_subcommand_from product" -a "rette" -d "Rette Lebensmittel"

# favorite subcommands
complete -c knuspr -n "__fish_seen_subcommand_from favorite" -a "list" -d "Anzeigen"
complete -c knuspr -n "__fish_seen_subcommand_from favorite" -a "add" -d "Hinzufügen"
complete -c knuspr -n "__fish_seen_subcommand_from favorite" -a "remove" -d "Entfernen"

# cart subcommands
complete -c knuspr -n "__fish_seen_subcommand_from cart" -a "show" -d "Anzeigen"
complete -c knuspr -n "__fish_seen_subcommand_from cart" -a "add" -d "Hinzufügen"
complete -c knuspr -n "__fish_seen_subcommand_from cart" -a "remove" -d "Entfernen"
complete -c knuspr -n "__fish_seen_subcommand_from cart" -a "clear" -d "Leeren"
complete -c knuspr -n "__fish_seen_subcommand_from cart" -a "open" -d "Im Browser öffnen"

# slot subcommands
complete -c knuspr -n "__fish_seen_subcommand_from slot" -a "list" -d "Anzeigen"
complete -c knuspr -n "__fish_seen_subcommand_from slot" -a "reserve" -d "Reservieren"
complete -c knuspr -n "__fish_seen_subcommand_from slot" -a "release" -d "Freigeben"
complete -c knuspr -n "__fish_seen_subcommand_from slot" -a "current" -d "Aktuelle Reservierung"

# order subcommands
complete -c knuspr -n "__fish_seen_subcommand_from order" -a "list" -d "Anzeigen"
complete -c knuspr -n "__fish_seen_subcommand_from order" -a "show" -d "Details anzeigen"
complete -c knuspr -n "__fish_seen_subcommand_from order" -a "repeat" -d "Wiederholen"

# insight subcommands
complete -c knuspr -n "__fish_seen_subcommand_from insight" -a "frequent" -d "Häufig gekauft"
complete -c knuspr -n "__fish_seen_subcommand_from insight" -a "meals" -d "Mahlzeitvorschläge"

# delivery subcommands
complete -c knuspr -n "__fish_seen_subcommand_from delivery" -a "show" -d "Anzeigen"

# completion
complete -c knuspr -n "__fish_seen_subcommand_from completion" -a "bash zsh fish" -d "Shell"

# Global options
complete -c knuspr -l json -d "JSON-Ausgabe"
complete -c knuspr -l limit -s n -d "Anzahl Ergebnisse"
complete -c knuspr -l help -s h -d "Hilfe anzeigen"
'''


def cmd_completion(args: argparse.Namespace) -> int:
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
        return EXIT_ERROR
    
    return EXIT_OK


# ─────────────────────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="knuspr",
        description="🛒 Knuspr.de im Terminal — REST-ähnliche CLI für Einkaufen, Suchen, Warenkorb und mehr"
    )
    subparsers = parser.add_subparsers(dest="command", help="Ressourcen")
    
    # ─────────────────────────────────────────────────────────────────────────
    # AUTH
    # ─────────────────────────────────────────────────────────────────────────
    auth_parser = subparsers.add_parser("auth", help="Authentifizierung (login|logout|status)")
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command", help="Auth-Befehle")
    
    auth_login = auth_subparsers.add_parser("login", help="Bei Knuspr.de einloggen")
    auth_login.add_argument("--email", "-e", help="E-Mail Adresse")
    auth_login.add_argument("--password", "-p", help="Passwort")
    auth_login.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    auth_login.set_defaults(func=cmd_auth_login)
    
    auth_logout = auth_subparsers.add_parser("logout", help="Ausloggen und Session löschen")
    auth_logout.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    auth_logout.set_defaults(func=cmd_auth_logout)
    
    auth_status = auth_subparsers.add_parser("status", help="Login-Status anzeigen")
    auth_status.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    auth_status.set_defaults(func=cmd_auth_status)
    
    # ─────────────────────────────────────────────────────────────────────────
    # CONFIG
    # ─────────────────────────────────────────────────────────────────────────
    config_parser = subparsers.add_parser("config", help="Konfiguration (show|set|reset)")
    config_subparsers = config_parser.add_subparsers(dest="config_command", help="Config-Befehle")
    
    config_show = config_subparsers.add_parser("show", help="Konfiguration anzeigen")
    config_show.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    config_show.set_defaults(func=cmd_config_show)
    
    config_set = config_subparsers.add_parser("set", help="Präferenzen interaktiv setzen")
    config_set.set_defaults(func=cmd_config_set)
    
    config_reset = config_subparsers.add_parser("reset", help="Konfiguration zurücksetzen")
    config_reset.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    config_reset.set_defaults(func=cmd_config_reset)
    
    # ─────────────────────────────────────────────────────────────────────────
    # ACCOUNT
    # ─────────────────────────────────────────────────────────────────────────
    account_parser = subparsers.add_parser("account", help="Account-Informationen (show)")
    account_subparsers = account_parser.add_subparsers(dest="account_command", help="Account-Befehle")
    
    account_show = account_subparsers.add_parser("show", help="Account-Informationen anzeigen")
    account_show.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    account_show.set_defaults(func=cmd_account_show)
    
    # ─────────────────────────────────────────────────────────────────────────
    # PRODUCT
    # ─────────────────────────────────────────────────────────────────────────
    product_parser = subparsers.add_parser("product", help="Produkte (search|show|filters|rette)")
    product_subparsers = product_parser.add_subparsers(dest="product_command", help="Produkt-Befehle")
    
    product_search = product_subparsers.add_parser("search", help="Produkte suchen")
    product_search.add_argument("query", help="Suchbegriff")
    product_search.add_argument("-n", "--limit", type=int, default=10, help="Anzahl Ergebnisse (Standard: 10)")
    product_search.add_argument("--favorites", action="store_true", help="Nur Favoriten anzeigen")
    product_search.add_argument("--rette", action="store_true", help="Nur Rette Lebensmittel")
    product_search.add_argument("--bio", action="store_true", dest="bio", default=None, help="Nur Bio-Produkte")
    product_search.add_argument("--no-bio", action="store_false", dest="bio", help="Bio-Filter deaktivieren")
    product_search.add_argument("--sort", choices=["relevance", "price_asc", "unit_price_asc", "price_desc"], help="Sortierung")
    product_search.add_argument("--exclude", nargs="*", help="Begriffe ausschließen")
    product_search.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    product_search.set_defaults(func=cmd_product_search)
    
    product_show = product_subparsers.add_parser("show", help="Produkt-Details anzeigen")
    product_show.add_argument("product_id", help="Produkt-ID")
    product_show.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    product_show.set_defaults(func=cmd_product_show)
    
    product_filters = product_subparsers.add_parser("filters", help="Verfügbare Filter anzeigen")
    product_filters.add_argument("query", help="Suchbegriff")
    product_filters.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    product_filters.set_defaults(func=cmd_product_filters)
    
    product_rette = product_subparsers.add_parser("rette", help="Rette Lebensmittel anzeigen")
    product_rette.add_argument("query", nargs="?", help="Optional: Suchbegriff zum Filtern")
    product_rette.add_argument("-n", "--limit", type=int, default=20, help="Anzahl Ergebnisse (Standard: 20)")
    product_rette.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    product_rette.set_defaults(func=cmd_product_rette)
    
    # ─────────────────────────────────────────────────────────────────────────
    # FAVORITE
    # ─────────────────────────────────────────────────────────────────────────
    favorite_parser = subparsers.add_parser("favorite", help="Favoriten (list|add|remove)")
    favorite_subparsers = favorite_parser.add_subparsers(dest="favorite_command", help="Favoriten-Befehle")
    
    favorite_list = favorite_subparsers.add_parser("list", help="Alle Favoriten anzeigen")
    favorite_list.add_argument("-n", "--limit", type=int, default=50, help="Anzahl Ergebnisse (Standard: 50)")
    favorite_list.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    favorite_list.set_defaults(func=cmd_favorite_list)
    
    favorite_add = favorite_subparsers.add_parser("add", help="Produkt zu Favoriten hinzufügen")
    favorite_add.add_argument("product_id", help="Produkt-ID")
    favorite_add.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    favorite_add.set_defaults(func=cmd_favorite_add)
    
    favorite_remove = favorite_subparsers.add_parser("remove", help="Produkt aus Favoriten entfernen")
    favorite_remove.add_argument("product_id", help="Produkt-ID")
    favorite_remove.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    favorite_remove.set_defaults(func=cmd_favorite_remove)
    
    # ─────────────────────────────────────────────────────────────────────────
    # CART
    # ─────────────────────────────────────────────────────────────────────────
    cart_parser = subparsers.add_parser("cart", help="Warenkorb (show|add|remove|clear|open)")
    cart_subparsers = cart_parser.add_subparsers(dest="cart_command", help="Warenkorb-Befehle")
    
    cart_show = cart_subparsers.add_parser("show", help="Warenkorb anzeigen")
    cart_show.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    cart_show.set_defaults(func=cmd_cart_show)
    
    cart_add = cart_subparsers.add_parser("add", help="Produkt hinzufügen")
    cart_add.add_argument("product_id", help="Produkt-ID")
    cart_add.add_argument("-q", "--quantity", type=int, default=1, help="Menge (Standard: 1)")
    cart_add.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    cart_add.set_defaults(func=cmd_cart_add)
    
    cart_remove = cart_subparsers.add_parser("remove", help="Produkt entfernen")
    cart_remove.add_argument("product_id", help="Produkt-ID")
    cart_remove.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    cart_remove.set_defaults(func=cmd_cart_remove)
    
    cart_clear = cart_subparsers.add_parser("clear", help="Warenkorb leeren")
    cart_clear.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    cart_clear.set_defaults(func=cmd_cart_clear)
    
    cart_open = cart_subparsers.add_parser("open", help="Warenkorb im Browser öffnen")
    cart_open.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    cart_open.set_defaults(func=cmd_cart_open)
    
    # ─────────────────────────────────────────────────────────────────────────
    # SLOT
    # ─────────────────────────────────────────────────────────────────────────
    slot_parser = subparsers.add_parser("slot", help="Lieferzeitfenster (list|reserve|release|current)")
    slot_subparsers = slot_parser.add_subparsers(dest="slot_command", help="Slot-Befehle")
    
    slot_list = slot_subparsers.add_parser("list", help="Verfügbare Zeitfenster anzeigen")
    slot_list.add_argument("-n", "--limit", type=int, default=5, help="Anzahl Tage (Standard: 5)")
    slot_list.add_argument("--detailed", "-d", action="store_true", help="Zeige auch 15-Minuten Slots mit IDs")
    slot_list.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    slot_list.set_defaults(func=cmd_slot_list)
    
    slot_reserve = slot_subparsers.add_parser("reserve", help="Zeitfenster reservieren")
    slot_reserve.add_argument("slot_id", help="Slot-ID (aus 'knuspr slot list --detailed')")
    slot_reserve.add_argument("--type", "-t", choices=["ON_TIME", "VIRTUAL"], default="ON_TIME", 
                              help="Slot-Typ: ON_TIME (15-min) oder VIRTUAL (1-Stunde)")
    slot_reserve.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    slot_reserve.set_defaults(func=cmd_slot_reserve)
    
    slot_release = slot_subparsers.add_parser("release", help="Reservierung stornieren")
    slot_release.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    slot_release.set_defaults(func=cmd_slot_release)
    
    slot_current = slot_subparsers.add_parser("current", help="Aktuelle Reservierung anzeigen")
    slot_current.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    slot_current.set_defaults(func=cmd_slot_current)
    
    # ─────────────────────────────────────────────────────────────────────────
    # ORDER
    # ─────────────────────────────────────────────────────────────────────────
    order_parser = subparsers.add_parser("order", help="Bestellungen (list|show|repeat)")
    order_subparsers = order_parser.add_subparsers(dest="order_command", help="Bestell-Befehle")
    
    order_list = order_subparsers.add_parser("list", help="Bestellhistorie anzeigen")
    order_list.add_argument("-n", "--limit", type=int, default=10, help="Anzahl Bestellungen (Standard: 10)")
    order_list.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    order_list.set_defaults(func=cmd_order_list)
    
    order_show = order_subparsers.add_parser("show", help="Details einer Bestellung anzeigen")
    order_show.add_argument("order_id", help="Bestellnummer")
    order_show.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    order_show.set_defaults(func=cmd_order_show)
    
    order_repeat = order_subparsers.add_parser("repeat", help="Bestellung wiederholen (Produkte in Warenkorb)")
    order_repeat.add_argument("order_id", help="Bestellnummer")
    order_repeat.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    order_repeat.set_defaults(func=cmd_order_repeat)
    
    # ─────────────────────────────────────────────────────────────────────────
    # INSIGHT
    # ─────────────────────────────────────────────────────────────────────────
    insight_parser = subparsers.add_parser("insight", help="Einkaufs-Insights (frequent|meals)")
    insight_subparsers = insight_parser.add_subparsers(dest="insight_command", help="Insight-Befehle")
    
    insight_frequent = insight_subparsers.add_parser("frequent", help="Häufig gekaufte Produkte")
    insight_frequent.add_argument("-n", "--limit", type=int, default=10, help="Anzahl Top-Produkte (Standard: 10)")
    insight_frequent.add_argument("-o", "--orders", type=int, default=5, help="Anzahl zu analysierende Bestellungen (Standard: 5)")
    insight_frequent.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    insight_frequent.set_defaults(func=cmd_insight_frequent)
    
    insight_meals = insight_subparsers.add_parser("meals", help="Mahlzeitvorschläge basierend auf Kaufhistorie")
    insight_meals.add_argument("meal_type", choices=["breakfast", "lunch", "dinner", "snack", "baking", "drinks", "healthy"],
                               help="Mahlzeittyp")
    insight_meals.add_argument("-n", "--limit", type=int, default=10, help="Anzahl Vorschläge (Standard: 10)")
    insight_meals.add_argument("-o", "--orders", type=int, default=5, help="Anzahl zu analysierende Bestellungen (Standard: 5)")
    insight_meals.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    insight_meals.set_defaults(func=cmd_insight_meals)
    
    # ─────────────────────────────────────────────────────────────────────────
    # DELIVERY
    # ─────────────────────────────────────────────────────────────────────────
    delivery_parser = subparsers.add_parser("delivery", help="Lieferinformationen (show)")
    delivery_subparsers = delivery_parser.add_subparsers(dest="delivery_command", help="Liefer-Befehle")
    
    delivery_show = delivery_subparsers.add_parser("show", help="Lieferinformationen anzeigen")
    delivery_show.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    delivery_show.set_defaults(func=cmd_delivery_show)
    
    # ─────────────────────────────────────────────────────────────────────────
    # COMPLETION
    # ─────────────────────────────────────────────────────────────────────────
    completion_parser = subparsers.add_parser("completion", help="Shell-Completion ausgeben")
    completion_subparsers = completion_parser.add_subparsers(dest="shell", help="Shell")
    
    for shell in ["bash", "zsh", "fish"]:
        shell_parser = completion_subparsers.add_parser(shell, help=f"{shell.upper()} Completion")
        shell_parser.set_defaults(func=cmd_completion, shell=shell)
    
    # ─────────────────────────────────────────────────────────────────────────
    # Parse and execute
    # ─────────────────────────────────────────────────────────────────────────
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return EXIT_OK
    
    # Handle subcommand defaults
    if args.command == "auth" and not getattr(args, 'auth_command', None):
        # Default: auth → auth status
        args.json = False
        return cmd_auth_status(args)
    
    if args.command == "config" and not getattr(args, 'config_command', None):
        # Default: config → config show
        args.json = False
        return cmd_config_show(args)
    
    if args.command == "account" and not getattr(args, 'account_command', None):
        # Default: account → account show
        args.json = False
        return cmd_account_show(args)
    
    if args.command == "product" and not getattr(args, 'product_command', None):
        product_parser.print_help()
        return EXIT_OK
    
    if args.command == "favorite" and not getattr(args, 'favorite_command', None):
        # Default: favorite → favorite list
        args.json = False
        args.limit = 50
        return cmd_favorite_list(args)
    
    if args.command == "cart" and not getattr(args, 'cart_command', None):
        # Default: cart → cart show
        args.json = False
        return cmd_cart_show(args)
    
    if args.command == "slot" and not getattr(args, 'slot_command', None):
        # Default: slot → slot list
        args.json = False
        args.limit = 5
        args.detailed = False
        return cmd_slot_list(args)
    
    if args.command == "order" and not getattr(args, 'order_command', None):
        # Default: order → order list
        args.json = False
        args.limit = 10
        return cmd_order_list(args)
    
    if args.command == "insight" and not getattr(args, 'insight_command', None):
        # Default: insight → insight frequent
        args.json = False
        args.limit = 10
        args.orders = 5
        return cmd_insight_frequent(args)
    
    if args.command == "delivery" and not getattr(args, 'delivery_command', None):
        # Default: delivery → delivery show
        args.json = False
        return cmd_delivery_show(args)
    
    if args.command == "completion" and not getattr(args, 'shell', None):
        completion_parser.print_help()
        return EXIT_OK
    
    # Execute command
    if hasattr(args, 'func'):
        return args.func(args)
    
    parser.print_help()
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())