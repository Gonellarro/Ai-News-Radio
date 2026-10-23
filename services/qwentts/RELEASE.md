# Qwen TTS local 1.0.0

Primera versión funcional, identificada por el tag Git anotado `v1.0.0`.

Incluye biblioteca de voces clonadas, cola persistente de locuciones, generación
por fragmentos lógicos sin cortar frases, exportación WAV/MP3 y coordinación de
memoria con Ollama mediante el bloqueo de inferencia compartido.

El código, la web y la definición de Docker quedan versionados. `.env`, modelos,
grabaciones de referencia, voces importadas y locuciones permanecen fuera de Git
y requieren una copia de seguridad propia. No se vuelven a generar voces ni a
descargar modelos al crear esta versión.

La ficha del conjunto de servicios está en
`../news-orchestrator/docs/releases/v1.0.0.md`.
