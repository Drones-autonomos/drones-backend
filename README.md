<div align="center">

  <img src="https://upload.wikimedia.org/wikipedia/commons/4/4b/Logo_UAQ.png" alt="UAQ Logo" height="120px">

### Sistema de Drones Autónomos

[![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-2CA5E0?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?style=for-the-badge&logo=github-actions&logoColor=white)](https://github.com/features/actions)

---

Proyecto integral de Backend, Simulación y Control desarrollado para la Facultad de Informática de la Universidad Autónoma de Querétaro (UAQ).

</div>

---

## Tabla de Contenidos

- [Miembros del Equipo](#miembros-del-equipo)
- [Descripción de Arquitectura](#descripción-de-arquitectura)
- [Product Backlog (Priorizado)](#product-backlog-priorizado)
- [Cronograma de Ejecución (Roadmap)](#cronograma-de-ejecución-roadmap)
- [Sprint 1: Arquitectura Base, Entornos y MVP](#sprint-1-arquitectura-base-entornos-y-mvp)
- [Documentación Adicional](#documentación-adicional)

---

## Miembros del Equipo

- **Ángelica Cenobio** *(Scrum Master / DEV 2: Facilitación de ceremonias, mitigación de impedimentos, desarrollo de lógica de negocio en Backend y Arquitectura de Datos).*
- **Lu Álvarez** *(Product Owner / DEV 3: Gestión y priorización del Product Backlog, validación de criterios de aceptación, diseño de interfaz y desarrollo Frontend/Móvil).*
- **Fernando Ramírez** *(DEV 1: Desarrollo de módulos de control de vuelo, simulación, integración de hardware y automatización de despliegues CI/CD).*

---

## Descripción de Arquitectura

El presente repositorio agrupa el código fuente correspondiente a las capas de **Backend, Integración en Tiempo Real (Simulación y Control de Vuelo)** y la infraestructura **DevOps** del sistema de drones autónomos. 

La plataforma está diseñada para la ejecución de vuelos autónomos mediante el control estructurado de misiones, soportando transmisión de video de baja latencia, análisis en tiempo real basado en visión por computadora (detección de personas y presencia de humo) y mecanismos criptográficos para el almacenamiento seguro de la telemetría y material audiovisual.

---

## Product Backlog (Priorizado)

### Alta Prioridad
*   **RNF08 / RF04:** Implementación de vuelo autónomo básico en circuito cerrado (navegación multipunto) y ejecución de misiones programadas.
*   **RF11:** Control de acceso basado en roles (RBAC) para la plataforma de administración.
*   **RF01:** Módulo de visión computacional para la detección de personas fuera de horarios operativos.
*   **RF02 / RF03:** Sistema de mensajería para alertas en tiempo real con recolección de evidencia (captura de imagen, metadatos de tiempo y geolocalización).
*   **[Sin ID]:** Integración de modelo de clasificación de imágenes para detección de humo.
*   **RF06:** Protocolo de transmisión bidireccional y visualización de video en vivo.
*   **RNF03:** Implementación de cifrado en reposo para el almacenamiento del flujo de video.
*   **[Sin ID]:** Ejecución de pruebas de integración continua y estabilización del sistema para entrega en producción.

### Media Prioridad
*   **RF07:** Grabación continua y delegación de almacenamiento a repositorio seguro.
*   **RF05:** Configuración de perímetros virtuales restrictivos (Geofencing).
*   **RF08:** Automatización de purga de datos audiovisuales (política de retención a 30 días).
*   **RF09:** Implementación de bitácora transaccional e inmutable de telemetría de vuelo.
*   **RF10:** Registro y auditoría de eventos de acceso y mutación de estado.
*   **RNF04:** Protocolos de tolerancia a fallos en la capa de red (comunicación dron-estación base).
*   **RNF02 / RNF07:** Restricciones operativas a nivel software para cumplimiento normativo (límites de altitud y peso).
*   **RNF05:** Optimización de tiempos de respuesta en la interfaz web y móvil.

### Baja Prioridad
*   **RNF06:** API de integración para acoplamiento con infraestructura física (base de carga o helipuerto automatizado).

---

## Cronograma de Ejecución (Roadmap)

| Sprint | Hito Principal | Descripción de Entregables |
| :---: | :--- | :--- |
| **1** | **Fundamentos Arquitectónicos** | Definición de infraestructura, aprovisionamiento de entornos, MVP de vuelo autónomo y modelo de seguridad RBAC. |
| **2** | **Sistemas de Navegación** | Módulos de control y orquestación de misiones programadas. |
| **3** | **Análisis de Video (Personas)** | Integración de IA para detección de personas fuera de horario. |
| **4** | **Análisis de Video (Humo)** | Detección de humo en el procesamiento del flujo de imágenes. |
| **5** | **Sistema de Notificaciones** | Motor de reglas para generación de alertas con recolección de metadatos. |
| **6** | **Streaming** | Transmisión y visualización de video en tiempo real. |
| **7** | **Persistencia Segura** | Almacenamiento continuo con encriptación en reposo. |
| **8** | **Navegación Restringida** | Implementación del módulo de Geofencing y zonas de exclusión. |
| **9** | **Ciclo de Vida de Datos** | Política de retención (30 días) y auditoría inmutable de bitácoras. |
| **10** | **Trazabilidad y Usabilidad** | Auditoría integral de accesos y optimización de interacción de usuario. |
| **11** | **Estabilización Final** | Pruebas de tolerancia a fallos, revisión de hardware, documentación técnica y despliegue final. |

---

## Sprint 1: Arquitectura Base, Entornos y MVP

**Objetivo de la Iteración:**
Aprovisionar la infraestructura fundacional del proyecto, configurando los entornos de desarrollo e integración. Establecer el esquema de persistencia inicial (RBAC) y desplegar un Prototipo Mínimo Viable (MVP) para la simulación de vuelo autónomo en un circuito delimitado.

**Criterios de Aceptación (DoD):**
- [ ] Todo el código fuente está versionado en el repositorio principal, contando con al menos un Code Review (PR) aprobado.
- [ ] El simulador SITL ejecuta exitosamente una misión programada (trayectoria de ida y vuelta) sin intervención telemétrica manual.
- [ ] Flujo de autenticación completo (End-to-End) operativo entre Frontend y Backend.
- [ ] Esquema relacional base (entidades Usuario y Rol) inicializado en el motor de base de datos.
- [ ] Pipeline CI/CD configurado y ejecutando la fase de build exitosamente ante cada integración en la rama `main`.
- [ ] La iteración concluye con una demostración funcional al Product Owner sin deficiencias críticas o bloqueantes.

---

## Documentación Adicional

- [Guía de Configuración: Entorno de Simulación SITL](docs/SITL_SIMULATION.md)
