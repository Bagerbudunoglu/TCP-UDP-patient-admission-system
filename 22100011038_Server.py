# 22100011038_Server.py
# Bu script bir hastane randevu sisteminin sunucu tarafını yönetir.
# Doktorlar TCP ile, hastalar TCP veya UDP ile bağlanabilir. Zamanlayıcı desteği ile hasta yanıtları beklenir.

import socket
import threading
import select
import sys

class HastaneServer:
    def __init__(self, host='localhost', port=12345):
        # Sunucu bağlantı bilgileri ve yapılandırmalar
        self.host = host
        self.port = port
        self.buffer_size = 1024

        # TCP ve UDP socket oluşturuluyor
        self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # TCP soket ayarları ve başlatma
        self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_socket.bind((self.host, self.port))
        self.tcp_socket.listen(5)

        # UDP soket başlatma
        self.udp_socket.bind((self.host, self.port))

        self.inputs = [self.tcp_socket, self.udp_socket]
        self.clients = {}         # TCP istemcileri (hasta/doktor)
        self.udp_clients = {}     # UDP istemcileri (hastalar)

        self.doctor_count = 0
        self.patient_count = 0
        self.doctors = {}         # Doktor bilgileri
        self.waiting_patients = []
        self.patient_timers = {}  # Hasta cevap bekleme zamanlayıcıları

        print(f"Hastane Sunucusu başlatıldı: {self.host}:{self.port}")

    def broadcast_to_doctors(self, message):
        # Tüm doktorlara mesaj gönder
        for doc in self.doctors.values():
            try:
                doc['socket'].send(message.encode())
            except:
                pass

    def send_to_client(self, sock, msg):
        # TCP istemciye mesaj gönder
        try:
            sock.send(msg.encode())
        except:
            pass

    def send_to_udp_client(self, addr, msg):
        # UDP istemciye mesaj gönder
        try:
            self.udp_socket.sendto(msg.encode(), addr)
        except:
            pass

    def handle_new_tcp_connection(self):
        # Yeni TCP bağlantısı işleniyor (hasta/doktor ayrımı yapılıyor)
        conn, addr = self.tcp_socket.accept()
        try:
            role = conn.recv(self.buffer_size).decode().strip()
            if role.lower().startswith("doktor"):
                # Maksimum 2 doktor bağlanabilir
                if self.doctor_count >= 2:
                    conn.send("Maksimum doktor sınırı dolu.".encode())
                    conn.close()
                    return
                self.doctor_count += 1
                name = f"Doktor{self.doctor_count}"
                self.doctors[name] = {'socket': conn, 'patients': [], 'current_patient': None}
                self.clients[conn] = {'type': 'Doktor', 'name': name}
                self.inputs.append(conn)
                conn.send(f"Hoşgeldiniz {name}".encode())
                self.broadcast_to_doctors(f"{name} sisteme bağlandı.")
                threading.Thread(target=self.handle_doctor, args=(conn, name), daemon=True).start()

            elif role.lower().startswith("hasta"):
                # Doktor yoksa hasta bağlanamaz
                if self.doctor_count == 0:
                    conn.send("Aktif doktor bulunmuyor.".encode())
                    conn.close()
                    return
                self.patient_count += 1
                name = f"Hasta{self.patient_count}"
                self.clients[conn] = {'type': 'Hasta', 'name': name}
                self.waiting_patients.append(name)
                self.inputs.append(conn)
                conn.send(f"Hoşgeldiniz {name}".encode())
                self.broadcast_to_doctors(f"{name} sisteme bağlandı.")
                self.distribute_patient(name)
            else:
                conn.send("Geçersiz rol.".encode())
                conn.close()
        except:
            conn.close()

    def handle_udp_message(self):
        # UDP hasta bağlantı ve cevapları işleniyor
        try:
            data, addr = self.udp_socket.recvfrom(self.buffer_size)
            msg = data.decode().strip()

            if addr in self.udp_clients and msg.lower() not in ["evet", "kabul", "hayır"]:
                return

            if msg.lower().startswith("hasta") and addr not in self.udp_clients:
                if self.doctor_count == 0:
                    self.send_to_udp_client(addr, "Doktor yok, bağlanamazsınız.")
                    return
                self.patient_count += 1
                name = f"Hasta{self.patient_count}"
                self.udp_clients[addr] = {'type': 'Hasta', 'name': name}
                self.waiting_patients.append(name)
                self.send_to_udp_client(addr, f"Hoşgeldiniz {name}")
                self.broadcast_to_doctors(f"{name} UDP ile bağlandı.")
                self.distribute_patient(name)

            elif msg.lower() in ["evet", "kabul"]:
                name = self.udp_clients[addr]['name']
                if name in self.patient_timers:
                    self.patient_timers[name].cancel()
                    del self.patient_timers[name]
                for doc_name, doc in self.doctors.items():
                    if doc['current_patient'] == name:
                        self.send_to_udp_client(addr, "Geçmiş olsun")
                        self.broadcast_to_doctors(f"{name} {doc_name} randevusunu kabul etti")
                        del self.udp_clients[addr]
                        if name in self.waiting_patients:
                            self.waiting_patients.remove(name)
                        self.check_shutdown()
                        break

            elif msg.lower() == "hayır":
                name = self.udp_clients[addr]['name']
                for doc_name, doc in self.doctors.items():
                    if doc['current_patient'] == name:
                        doc['patients'].append(name)
                        doc['current_patient'] = None
                        self.send_to_udp_client(addr, "Randevu reddedildi, sıraya alındınız.")
                        self.broadcast_to_doctors(f"{name} {doc_name} randevusunu reddetti")
                        break
        except:
            pass

    def handle_client_message(self, sock):
        # TCP istemcilerden gelen mesajlar işlenir (özellikle hasta cevapları)
        try:
            data = sock.recv(self.buffer_size)
            if not data:
                self.handle_disconnection(sock)
                return
            msg = data.decode().strip()
            info = self.clients[sock]

            if info['type'] == 'Doktor' and msg == "Hasta Kabul":
                self.call_next_patient(info['name'])

            elif info['type'] == 'Hasta':
                name = info['name']
                if msg.lower() in ["evet", "kabul"]:
                    if name in self.patient_timers:
                        self.patient_timers[name].cancel()
                        del self.patient_timers[name]
                    for doc_name, doc in self.doctors.items():
                        if doc['current_patient'] == name:
                            self.send_to_client(sock, "Geçmiş olsun")
                            self.broadcast_to_doctors(f"{name} {doc_name} randevusunu kabul etti")
                            self.handle_disconnection(sock)
                            break
                elif msg.lower() == "hayır":
                    for doc_name, doc in self.doctors.items():
                        if doc['current_patient'] == name:
                            doc['patients'].append(name)
                            doc['current_patient'] = None
                            self.send_to_client(sock, "Randevu reddedildi, sıraya alındınız.")
                            self.broadcast_to_doctors(f"{name} {doc_name} randevusunu reddetti")
                            break
        except:
            self.handle_disconnection(sock)

    def handle_doctor(self, sock, name):
        # Doktor istemcisi için girişleri dinleyen ayrı bir thread
        while sock in self.inputs:
            try:
                data = sock.recv(self.buffer_size)
                if not data:
                    break
                if data.decode().strip() == "Hasta Kabul":
                    self.call_next_patient(name)
            except:
                break
        self.handle_disconnection(sock)

    def distribute_patient(self, name):
        # Hastaları en az hastası olan doktora sıraya ekle
        if not self.doctors:
            return
        doc_name = min(self.doctors, key=lambda d: len(self.doctors[d]['patients']))
        self.doctors[doc_name]['patients'].append(name)
        self.broadcast_to_doctors(f"{name}, {doc_name}'a atandı.")

    def call_next_patient(self, doc_name):
        # Bir sonraki hastayı çağır
        doc = self.doctors[doc_name]
        current = doc['current_patient']
        if current:
            self.broadcast_to_doctors(f"{current} için randevu tamamlandı.")
            self.cleanup_patient(current)

        if doc['patients']:
            next_p = doc['patients'].pop(0)
            doc['current_patient'] = next_p

            log_message = f"{next_p} → {doc_name}"
            print(f"[LOG] {log_message}")
            self.broadcast_to_doctors(log_message)

            for sock, info in self.clients.items():
                if info['name'] == next_p:
                    self.send_to_client(sock, log_message)
                    self.send_to_client(sock, f"{doc_name} tarafından çağrıldınız. Randevuyu onaylıyor musunuz (evet/hayır)")
                    break
            for addr, info in self.udp_clients.items():
                if info['name'] == next_p:
                    self.send_to_udp_client(addr, log_message)
                    self.send_to_udp_client(addr, f"{doc_name} tarafından çağrıldınız. Randevuyu onaylıyor musunuz (evet/hayır)")
                    break

            timer = threading.Timer(10, self.handle_timeout, args=(doc_name, next_p))
            timer.start()
            self.patient_timers[next_p] = timer
        else:
            self.send_to_client(doc['socket'], "Bekleyen hasta bulunmamaktadır.")
            self.check_shutdown()

    def handle_timeout(self, doc_name, patient_name):
        # Hasta 10 saniyede cevap vermezse otomatik olarak sıradaki hastaya geç
        doc = self.doctors.get(doc_name)
        if not doc:
            return

        if doc['current_patient'] == patient_name:
            self.broadcast_to_doctors(f"{patient_name} 10 saniye içinde cevap vermedi, sıradaki hasta çağrılıyor...")
            doc['current_patient'] = None
            self.call_next_patient(doc_name)

        self.patient_timers.pop(patient_name, None)

    def cleanup_patient(self, name):
        # Hasta bağlantısını temizle ve geçmiş olsun gönder
        for sock, info in list(self.clients.items()):
            if info['name'] == name:
                self.send_to_client(sock, "Geçmiş olsun")
                self.handle_disconnection(sock)
                return
        for addr, info in list(self.udp_clients.items()):
            if info['name'] == name:
                self.send_to_udp_client(addr, "Geçmiş olsun")
                del self.udp_clients[addr]
                return

    def handle_disconnection(self, sock):
        # TCP istemcinin bağlantısını sonlandır
        if sock in self.clients:
            info = self.clients[sock]
            name = info['name']
            if info['type'] == 'Doktor':
                if name in self.doctors:
                    del self.doctors[name]
                self.doctor_count -= 1
            elif info['type'] == 'Hasta':
                if name in self.waiting_patients:
                    self.waiting_patients.remove(name)
            del self.clients[sock]
        if sock in self.inputs:
            self.inputs.remove(sock)
        try:
            sock.close()
        except:
            pass
        self.check_shutdown()

    def check_shutdown(self):
        # Sistem kapanışını kontrol et (hasta ve doktorlar bittiğinde)
        if not self.waiting_patients and all(not doc['patients'] and not doc['current_patient'] for doc in self.doctors.values()):
            self.shutdown_system()

    def shutdown_system(self):
        # Sistemi tüm bağlantıları kapatarak sonlandır
        msg = "Sistemde bekleyen hasta kalmadı. Sistem kapatılıyor..."
        print(msg)
        self.broadcast_to_doctors(msg)
        for sock in list(self.clients.keys()):
            try:
                sock.send(msg.encode())
                sock.close()
            except:
                pass
        for addr in list(self.udp_clients.keys()):
            try:
                self.udp_socket.sendto(msg.encode(), addr)
            except:
                pass
        self.tcp_socket.close()
        self.udp_socket.close()
        sys.exit(0)

    def run(self):
        # Ana sunucu döngüsü: TCP ve UDP bağlantılarını bekle
        try:
            while True:
                readable, _, _ = select.select(self.inputs, [], [])
                for sock in readable:
                    if sock is self.tcp_socket:
                        self.handle_new_tcp_connection()
                    elif sock is self.udp_socket:
                        self.handle_udp_message()
                    else:
                        self.handle_client_message(sock)
        except KeyboardInterrupt:
            print("Sunucu kapatıldı.")
            self.shutdown_system()

if __name__ == "__main__":
    server = HastaneServer()
    server.run()
