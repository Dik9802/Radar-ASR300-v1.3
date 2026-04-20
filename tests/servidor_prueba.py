"""
servidor_minimalista.py
-----------------------
Versión minimalista del servidor de prueba
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
from datetime import datetime
import json

class TestHandler(BaseHTTPRequestHandler):
    
    def do_GET(self):
        # Parsear parámetros GET
        query_params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        
        # Timestamp para el log
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        
        # Mostrar en consola
        print(f"\n[{timestamp}] 📥 GET {self.path}")
        print("Parámetros recibidos:")
        for key, value in query_params.items():
            print(f"  {key}: {value[0] if value else ''}")
        
        # Responder al cliente
        response = {
            "status": "ok",
            "received": {k: v[0] for k, v in query_params.items()}
        }
        
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())

def run_simple_server():
    server = HTTPServer(('127.0.0.1', 5000), TestHandler)
    print("Servidor escuchando en http://127.0.0.1:5000")
    print("Presiona Ctrl+C para detener")
    server.serve_forever()

if __name__ == '__main__':
    run_simple_server()