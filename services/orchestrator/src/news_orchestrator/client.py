import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class RemoteError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


class Client:
    def __init__(self, variable, default):
        self.url = os.environ.get(variable, default).rstrip("/")

    def request(self, path, data=None, timeout=30):
        request = Request(self.url + path, data=json.dumps(data, ensure_ascii=False).encode() if data is not None else None,
                          headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urlopen(request, timeout=timeout) as response:
                value = response.read(2 * 1024 * 1024 + 1)
                if len(value) > 2 * 1024 * 1024:
                    raise RemoteError("El servicio devolvió una respuesta demasiado grande.")
                result = json.loads(value)
                if not isinstance(result, dict):
                    raise RemoteError("El servicio no devolvió un objeto JSON.")
                return result
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read(8192)).get("error", str(exc))
            except (ValueError, AttributeError):
                detail = str(exc)
            finally:
                exc.close()
            raise RemoteError(str(detail), exc.code) from exc

    def download(self, path, target):
        temporary = Path(str(target) + ".part")
        try:
            with urlopen(self.url + path, timeout=60) as response, temporary.open("wb") as output:
                total = 0
                while chunk := response.read(65536):
                    total += len(chunk)
                    if total > 100 * 1024 * 1024:
                        raise RemoteError("El archivo de audio supera 100 MiB.")
                    output.write(chunk)
            if not total:
                raise RemoteError("El servicio devolvió un archivo vacío.")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
