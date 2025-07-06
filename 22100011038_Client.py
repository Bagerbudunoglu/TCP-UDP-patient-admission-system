# 22100011038_Client.py
# Bu script bir hastane randevu sisteminin istemci tarafını yönetir.
# Doktorlar yalnızca TCP ile bağlanabilir. Hastalar ise TCP veya UDP kullanabilir.
# İstemci, sunucudan gelen çağrılara cevap verir ve kullanıcıdan girdi alır.

import socket
import threading
import sys
import time

class HastaneClient:
    def __init__(self, host='localhost', port=12345, client_type=None, connection_type=None):
        self.host = host
        self.port = port
        self.buffer_size = 1024
        self.client_type = client_type
        self.connection_type = connection_type
        self.socket = None
        self.running = False

        # Giriş doğrulama kontrolleri
        if self.client_type not in ['Doktor', 'Hasta']:
            print("İstemci tipi 'Doktor' veya 'Hasta' olmalıdır.")
            sys.exit(1)
        if self.connection_type not in ['TCP', 'UDP']:
            print("Bağlantı tipi 'TCP' veya 'UDP' olmalıdır.")
            sys.exit(1)
        if self.client_type == 'Doktor' and self.connection_type == 'UDP':
            print("Doktorlar sadece TCP ile bağlanabilir.")
            sys.exit(1)

    def connect(self):
        try:
            if self.connection_type == 'TCP':
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.connect((self.host, self.port))
                self.socket.send(f"{self.client_type}".encode())
                welcome = self.socket.recv(self.buffer_size).decode()
                print(f"[Sunucu] {welcome}")
                self.running = True
                threading.Thread(target=self.receive_messages_tcp, daemon=True).start()
                self.handle_input_tcp()
            else:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.socket.sendto(f"{self.client_type}".encode(), (self.host, self.port))
                msg, _ = self.socket.recvfrom(self.buffer_size)
                print(f"[Sunucu] {msg.decode()}")
                self.running = True
                threading.Thread(target=self.receive_messages_udp, daemon=True).start()
                self.handle_input_udp()
        except Exception as e:
            print(f"Bağlantı hatası: {e}")
            sys.exit(1)

    def receive_messages_tcp(self):
        try:
            while self.running:
                data = self.socket.recv(self.buffer_size)
                if not data:
                    break
                msg = data.decode()
                print(f"[Sunucu] {msg}")

                if "onaylıyor musunuz" in msg.lower():
                    threading.Thread(target=self.start_countdown, daemon=True).start()

                if "Geçmiş olsun" in msg or "Sistem kapatılıyor" in msg:
                    self.running = False
                    self.socket.close()
                    sys.exit(0)
        except Exception as e:
            print(f"Mesaj alma hatası: {e}")
            self.running = False

    def receive_messages_udp(self):
        try:
            while self.running:
                data, _ = self.socket.recvfrom(self.buffer_size)
                msg = data.decode()
                print(f"[Sunucu] {msg}")

                if "onaylıyor musunuz" in msg.lower():
                    threading.Thread(target=self.start_countdown, daemon=True).start()

                if "Geçmiş olsun" in msg or "Sistem kapatılıyor" in msg:
                    self.running = False
                    self.socket.close()
                    sys.exit(0)
        except Exception as e:
            print(f"UDP mesaj alma hatası: {e}")
            self.running = False

    def handle_input_tcp(self):
        # TCP istemciler için kullanıcıdan komut alır
        try:
            while self.running:
                msg = input(">> ").strip()
                if self.client_type == 'Doktor' and msg != "Hasta Kabul":
                    print("Sadece 'Hasta Kabul' komutu geçerlidir.")
                    continue
                self.socket.send(msg.encode())
        except:
            self.running = False

    def handle_input_udp(self):
        # UDP istemciler için kullanıcıdan komut alır
        try:
            while self.running:
                msg = input(">> ").strip()
                self.socket.sendto(msg.encode(), (self.host, self.port))
        except:
            self.running = False

    def start_countdown(self):
        # Hasta çağrıldığında 10 saniyelik sayaç başlatır
        for i in range(10, 0, -1):
            if not self.running:
                return
            print(f"[Sayaç] {i} saniye kaldı...")
            time.sleep(1)

    def run(self):
        self.connect()
        try:
            while self.running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\n[⛔] Istemci kapatılıyor...")
            self.running = False
            if self.connection_type == 'TCP' and self.socket:
                self.socket.close()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Kullanım: python 22100011038_Client.py <Doktor/Hasta> <TCP/UDP>")
        sys.exit(1)
    role = sys.argv[1]
    connection = sys.argv[2]
    client = HastaneClient(client_type=role, connection_type=connection)
    client.run()