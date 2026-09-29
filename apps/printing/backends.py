"""Adaptadores de salida locales. No contienen acceso a la base de datos."""
from abc import ABC, abstractmethod
from pathlib import Path
import socket
import ipaddress
import queue
import threading
import time
import unicodedata
from django.conf import settings
from .rendering import clean


class PrinterError(Exception):
    def __init__(self, message, *, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


class PrinterBackend(ABC):
    @abstractmethod
    def send(self, job):
        """Acepta un PrintJob ya reclamado; devuelve ruta debug o cadena vacía."""


def encode_text(text, printer):
    text = clean(text).replace('×', 'x').replace('—', '-').replace('–', '-')
    if printer.transliterate:
        text = ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))
    # La sustitución ocurre solo en el transporte; el snapshot Unicode permanece íntegro.
    return text.encode(printer.encoding, errors='replace')


def escpos_payload(job):
    printer = job.printer
    data = b'\x1b@'
    if printer.codepage is not None:
        data += b'\x1bt' + bytes([printer.codepage])
    data += encode_text(job.payload_snapshot['text'], printer) + b'\n\n\n'
    if printer.supports_cut:
        data += b'\x1dV\x00'
    return data


class DebugPrinterBackend(PrinterBackend):
    def send(self, job):
        root = Path(settings.PRINTER_DEBUG_DIR)
        root.mkdir(parents=True, exist_ok=True)
        path = root / f'job-{job.pk:08d}-attempt-{job.attempt_count:03d}.txt'
        # Cada intento conserva su archivo; no se sobrescribe historia por un reintento.
        with path.open('x', encoding='utf-8') as stream:
            stream.write(job.payload_snapshot['text'])
        return str(path)


# Una resolución DNS bloqueada no debe congelar el POS ni crear hilos sin límite.
_dns_slots = threading.BoundedSemaphore(4)


def connect(host, port, timeout):
    deadline = time.monotonic() + timeout
    try:
        address = ipaddress.ip_address(host)
        family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        target = (host, port)
    except ValueError:
        if not _dns_slots.acquire(blocking=False):
            raise OSError('Resolución de nombres ocupada; configura una IP o reintenta.')
        result = queue.Queue(maxsize=1)
        def resolve():
            try:
                result.put(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
            except OSError as exc:
                result.put(exc)
            finally:
                _dns_slots.release()
        threading.Thread(target=resolve, daemon=True).start()
        try:
            addresses = result.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError('La resolución del host agotó el tiempo disponible.')
        if isinstance(addresses, Exception):
            raise addresses
        if not addresses:
            raise OSError('Host sin dirección TCP.')
        family, _, _, _, target = addresses[0]
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Se agotó el tiempo de conexión.')
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.settimeout(remaining)
        sock.connect(target)
    except OSError:
        sock.close()
        raise
    return sock


class NetworkEscPosBackend(PrinterBackend):
    def send(self, job):
        printer = job.printer
        if not printer.host:
            raise PrinterError('Impresora sin host configurado.')
        payload = escpos_payload(job)
        try:
            sock = connect(printer.host, printer.port, settings.PRINTER_CONNECT_TIMEOUT)
        except OSError as exc:
            raise PrinterError(f'No se pudo conectar: {exc}') from exc
        try:
            with sock:
                sock.settimeout(settings.PRINTER_WRITE_TIMEOUT)
                sock.sendall(payload)
        except OSError as exc:
            raise PrinterError(f'Envío interrumpido; comprueba si salió papel antes de reintentar: {exc}', uncertain=True) from exc
        return ''


def get_backend():
    return {'debug': DebugPrinterBackend, 'network': NetworkEscPosBackend}[settings.PRINTER_BACKEND]()
