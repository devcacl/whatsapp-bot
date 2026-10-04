# WhatsApp Bot de Admisiones USTA

MVP de asistente de admisiones con FastAPI, WhatsApp Cloud API, Gemini, Cohere y PostgreSQL con pgvector. El alcance inicial es responder consultas a partir de los archivos versionados en `knowledge/`, mantener trazabilidad de fuentes y abstenerse cuando el contexto no es suficiente.

## Estructura

- `app/`: API, webhook, cola de mensajes, RAG y configuración Docker.
- `knowledge/`: base de conocimiento inicial aprobada como vigente por el usuario.
- `GUIA_IMPLEMENTACION.md`: arquitectura y plan evolutivo.
- `render.yaml`: Blueprint para desplegar API y PostgreSQL en Render.

## Inicio rápido

Consulta [`app/README.md`](app/README.md) para configurar variables, ejecutar localmente, cargar documentos y conectar WhatsApp. Nunca guardes claves API ni tokens en Git. Usa `.env` solo localmente y variables secretas en Render.

## Estado

MVP inicial en preparación. La integración real requiere configurar las cuentas, secretos y número institucional; revisar las limitaciones descritas en `app/README.md` antes de abrir un piloto.

