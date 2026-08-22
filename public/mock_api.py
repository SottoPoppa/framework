import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


PRODUCTS = [
    {
        "id": 1,
        "title": "Essence Mascara Lash Princess",
        "description": "The Essence Mascara Lash Princess is a popular mascara.",
        "category": "beauty",
        "price": 9.99,
        "discountPercentage": 7.17,
        "rating": 4.94,
        "stock": 5,
        "brand": "Essence",
        "thumbnail": "https://cdn.dummyjson.com/product-images/beauty/essence-mascara-lash-princess/thumbnail.webp",
    },
    {
        "id": 2,
        "title": "Eyeshadow Palette with Mirror",
        "description": "The Eyeshadow Palette with Mirror is a versatile makeup kit.",
        "category": "beauty",
        "price": 19.99,
        "discountPercentage": 5.5,
        "rating": 3.28,
        "stock": 44,
        "brand": "Glamour Beauty",
        "thumbnail": "https://cdn.dummyjson.com/product-images/beauty/eyeshadow-palette-with-mirror/thumbnail.webp",
    },
    {
        "id": 3,
        "title": "Powder Canister",
        "description": "A practical powder canister for everyday use.",
        "category": "groceries",
        "price": 14.99,
        "discountPercentage": 13.1,
        "rating": 3.82,
        "stock": 59,
        "brand": "Velvet Touch",
        "thumbnail": "https://cdn.dummyjson.com/product-images/groceries/powder-canister/thumbnail.webp",
    },
    {
        "id": 4,
        "title": "Red Lipstick",
        "description": "A rich red lipstick with a smooth finish.",
        "category": "beauty",
        "price": 12.99,
        "discountPercentage": 13.1,
        "rating": 4.36,
        "stock": 91,
        "brand": "Chic Cosmetics",
        "thumbnail": "https://cdn.dummyjson.com/product-images/beauty/red-lipstick/thumbnail.webp",
    },
    {
        "id": 5,
        "title": "Red Nail Polish",
        "description": "A classic red nail polish with long-lasting color.",
        "category": "beauty",
        "price": 8.99,
        "discountPercentage": 9.0,
        "rating": 4.32,
        "stock": 71,
        "brand": "Nail Couture",
        "thumbnail": "https://cdn.dummyjson.com/product-images/beauty/red-nail-polish/thumbnail.webp",
    },
    {
        "id": 6,
        "title": "Calvin Klein CK One",
        "description": "A fresh and modern unisex fragrance.",
        "category": "fragrances",
        "price": 49.99,
        "discountPercentage": 7.0,
        "rating": 4.37,
        "stock": 17,
        "brand": "Calvin Klein",
        "thumbnail": "https://cdn.dummyjson.com/product-images/fragrances/calvin-klein-ck-one/thumbnail.webp",
    },
]


class MockApiHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/products":
            self.send_error(404, "Endpoint not found")
            return

        query = parse_qs(parsed.query)
        try:
            limit = max(1, int(query.get("limit", [30])[0]))
            skip = max(0, int(query.get("skip", [0])[0]))
        except ValueError:
            self.send_error(400, "limit and skip must be integers")
            return

        payload = {
            "products": PRODUCTS[skip:skip + limit],
            "total": len(PRODUCTS),
            "skip": skip,
            "limit": limit,
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string, *args):
        return


def start(host="127.0.0.1", port=8888):
    server = ThreadingHTTPServer((host, port), MockApiHandler)
    server.daemon_threads = True
    server.serve_forever()