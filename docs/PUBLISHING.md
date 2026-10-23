# Preparación para GitHub

El repositorio reúne los tres componentes, con sus commits originales importados
sin squash. Las etiquetas originales se conservan bajo `legacy/news-radio/`,
`legacy/orchestrator/` y `legacy/qwentts/`. `SOURCE_HISTORY.json` identifica la base
y si había cambios locales que se incorporaron al empaquetado.

`.gitignore` excluye `.env`, estado, copias, modelos, audios y voces personales.
Los ejemplos públicos de configuración no contienen la clave de YouTube ni una
dependencia de una red privada. Las dependencias de terceros conservan sus avisos.

Antes de publicar:

1. El código propio ya incluye `LICENSE` con la licencia MIT elegida por el autor.
2. Crea un repositorio vacío llamado, por ejemplo, `ai-news-radio` en GitHub.
3. En esta carpeta configura el remoto y sube la rama y las etiquetas:

```bash
git remote add origin https://github.com/TU_USUARIO/ai-news-radio.git
git push -u origin main
git push origin --tags
```

La creación del remoto y el envío no se ejecutan automáticamente. Nunca publiques
`state/`, `.env` ni un archivo de `backups/`. El archivo de verificación del montaje
documenta qué se ha comprobado y qué pruebas reales siguen dependiendo del destino.
