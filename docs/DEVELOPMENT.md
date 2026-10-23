# Desarrollo

```bash
./scripts/start.sh --dev
```

Monta `src/` y `web/` de cada servicio sobre las imágenes normales. JavaScript y CSS
se recargan en el navegador. Reinicia el proceso correspondiente para cargar cambios
Python, después de que termine la noticia completa si afecta a producción.

Los cambios de dependencias o Dockerfiles requieren reconstruir. El Compose base
no monta código: contiene la copia construida en la imagen y configura únicamente
los volúmenes persistentes. No utiliza un servidor de desarrollo en producción.

Los módulos conservan sus responsabilidades originales. La documentación técnica
detallada se encuentra en `services/*/docs/`; las instrucciones de despliegue válidas
son las de la raíz. Las notas históricas de componentes pueden describir el montaje
anterior. No ejecutes instrucciones antiguas para cambiar la instalación unificada.

## Comprobaciones locales

```bash
python3 scripts/validate.py
docker compose --env-file .env.example config --quiet
docker compose --env-file .env.example --profile qwen --profile youtube -f compose.yaml -f compose.dev.yaml config --quiet
```

Las comprobaciones estáticas no descargan modelos ni simulan una noticia real.
Para comprobar una instalación limpia usa otro directorio `STATE_DIR`, un nombre
de proyecto distinto y puertos libres; no apuntes a una base de datos en uso.
Desactiva las fuentes en esa instancia si solo estás revisando infraestructura,
para no duplicar peticiones a Reddit ni a otros servidores.

La automatización de GitHub valida sintaxis, JSON y los perfiles Compose. No carga
modelos ni publica emisiones. Las pruebas originales se conservan en cada servicio;
no sustituyen una comprobación de síntesis y emisión en el equipo destino.
