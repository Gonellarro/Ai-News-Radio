# Operación y copias

```bash
./scripts/start.sh
./scripts/status.sh
docker compose logs -f --tail 100 orchestrator
docker compose logs -f --tail 100 news-radio
```

`stop.sh` pausa nuevos trabajos y espera la noticia completa, las valoraciones
pendientes, las redacciones manuales y las locuciones Qwen pendientes antes de parar los servicios. Puede esperar
hasta tres horas; al agotarse el plazo deja la automatización pausada y no corta
la tarea. `--force` solicita una parada inmediata explícita. Al finalizar una
parada ordenada se conserva el valor previo de automatización para el próximo arranque.

## Actualizar

1. Espera y detén con `./scripts/stop.sh`.
2. Guarda una copia con `./scripts/backup.sh`.
3. Actualiza el código mediante Git y revisa las notas del cambio.
4. Ejecuta `./scripts/start.sh`, que construye y recrea las imágenes.

En una reinstalación, bootstrap solo copia archivos que aún no existen. Nuevas
opciones deben tener sus valores por defecto o su migración en el código; no se
sobrescriben los JSON modificados desde la web.

## Copias privadas

```bash
./scripts/stop.sh
./scripts/backup.sh
./scripts/start.sh
```

La copia se rechaza si hay contenedores de este proyecto ejecutándose. Esto evita
mezclar estados de SQLite, voz, vídeo y referencias mientras cambian. No detiene
servicios automáticamente ni modifica proyectos ajenos.

Incluye `.env`, configuración, bases de datos, voces propias y medios operativos,
incluida la clave de YouTube si existe. Se crea bajo `backups/` con permisos privados;
no la subas a GitHub. Los modelos de Ollama y Qwen se excluyen por tamaño y pueden
descargarse de nuevo. Para incluirlos usa `./scripts/backup.sh --include-models`.
Los modelos Piper guardados con los datos sí quedan incluidos.

## Restaurar

```bash
./scripts/restore.sh /ruta/a/ai-news-radio-FECHA.tar.gz
```

Requiere servicios detenidos y `STATE_DIR` vacío. Rechaza archivos con rutas fuera
del destino, enlaces y archivos especiales. Conserva el `.env` actual y guarda
el del archivo como `.env.restored` para revisarlo. No implementa sobrescritura
destructiva de una instalación existente. Si la copia omitía modelos, recupéralos
mediante `install.sh` antes de activar producción.

Si la salida a YouTube estaba activa en la copia, puede reanudarse al habilitar
su perfil. Revisa esa configuración privada antes del arranque.

## Espacio

La retirada automática borra los medios de noticias que salen de parrilla; conserva
el historial pequeño para no volver a producir duplicados. Los pesos de modelos,
las voces propias y las copias no se borran por rotación. Administra esas copias
según tu política y comprueba el espacio libre antes de actualizar imágenes.
