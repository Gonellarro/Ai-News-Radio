# Migrar una instalación anterior

Este repositorio es independiente. Prepararlo no detiene ni cambia la instalación
original de tres proyectos. No se copian automáticamente sus datos, claves ni voces.

Para una migración real, programa una ventana de mantenimiento:

1. Termina la noticia y las valoraciones que estén en marcha en el sistema anterior.
2. Detén sus productores y sus procesos de emisión. Guarda sus bases y configuraciones.
3. Copia los archivos **con todos los procesos detenidos**, según esta tabla.
4. En `.env`, selecciona Qwen/Piper y los perfiles que utilice esa instalación.
5. Ejecuta `install.sh`; conserva la configuración existente y completa dependencias.
6. Comprueba el dashboard y la emisión local antes de habilitar el perfil YouTube.

| Proyecto anterior | Directorio dentro de `STATE_DIR` |
| --- | --- |
| news-radio/config | news-radio/config |
| news-radio/data | news-radio/data |
| news-orchestrator/config | orchestrator/config |
| news-orchestrator/data | orchestrator/data |
| qwentts/models | qwentts/models |
| qwentts/voices | qwentts/voices |
| qwentts/data | qwentts/data |

No montes el mismo SQLite en ambos despliegues ni copies una base activa como si
fuera un archivo estático. Se conservan los IDs, la deduplicación, las voces y la
parrilla si se copian conjuntamente. Los permisos deben coincidir con APP_UID/GID.

Los modelos Ollama del host anterior no se importan automáticamente: el contenedor
tiene su almacén independiente. El instalador puede descargarlos. Si decides copiar
un almacén existente, conserva blobs y manifests completos, y documenta el origen.

La configuración privada de YouTube puede incluir `enabled: true`. Déjala desactivada
o arranca sin perfil `youtube` hasta haber comprobado el nuevo montaje.
