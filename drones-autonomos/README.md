<div align="center">
  <img src="https://www.uaq.mx/informatica/images/fotos_descargas/LogosUAQ/Logotipo-Vertical.png" alt="Logo UAQ" width="150" />
  <img src="https://www.uaq.mx/informatica/images/fotos_descargas/LogosFIF/Escudo_FI.png" alt="Logo Facultad de Informática" width="150" style="margin-left: 20px;"/>
  
  # Drones Autónomos - Backend, Simulación y Control
  
  **Proyecto Integral de Vuelo Autónomo para la Facultad de Informática de la UAQ**
</div>

---

## 📖 Descripción del Repositorio

Este repositorio contiene el código correspondiente a la capa de **Backend, Integración con el Dron (simulación y control)** y **DevOps** del proyecto **"Drones Autónomos"**. 
El objetivo principal de este proyecto es implementar un sistema capaz de realizar vuelos autónomos, con control de misiones, transmisión de video, alertas basadas en visión por Inteligencia Artificial (detección de personas y humo) y grabación segura.

---

## 👥 Equipo Scrum

El proyecto se planifica en **11 sprints semanales** con Dailies los días martes y jueves de cada semana.

- **Product Owner / DEV 3:** Lu Bazaldua *(Define y prioriza backlog, valida entregables, Frontend/Web-Móvil/UX)*.
- **Scrum Master / DEV 2:** Angel Cenobio *(Facilita dailies, seguimiento, Backend, Arquitectura de Datos)*.
- **DEV 1:** Fernando Ramirez *(Integración con el dron (simulación/control) y DevOps)*.

---

## 🎯 Product Backlog (Priorizado)

### Prioridad Alta
- **RNF08 / RF04:** Vuelo autónomo básico en circuito cerrado (ida y vuelta) y control/programado de misiones.
- **RF11:** Control de acceso basado en roles (RBAC).
- **RF01:** Detección de personas fuera de horario mediante visión por IA.
- **RF02 / RF03:** Generación y envío de alertas con evidencia (foto, fecha, hora, ubicación).
- **(Sin ID):** Detección de humo mediante procesamiento de imágenes.
- **RF06:** Transmisión y visualización de video en vivo.
- **RNF03:** Cifrado y control de acceso al repositorio de video.
- **(Sin ID):** Pruebas de integración, documentación y presentación final.

### Prioridad Media
- **RF07:** Grabación continua y almacenamiento en repositorio seguro.
- **RF05:** Definición de zonas de exclusión (Geofencing).
- **RF08:** Purga automática de material audiovisual (retención de 30 días).
- **RF09:** Bitácora inmutable de vuelos.
- **RF10:** Auditoría de cambios y accesos.
- **RNF04:** Conectividad y tolerancia a fallos dron-estación.
- **RNF02 / RNF07:** Cobertura operativa por horarios y cumplimiento normativo (altura, peso).
- **RNF05:** Usabilidad de la interfaz web y móvil.

### Prioridad Baja
- **RNF06:** Integración con base de carga / helipuerto.

---

## 🗓️ Plan de Trabajo (Sprints)

| Sprint | Semana | Objetivo / Requerimientos |
| :---: | :---: | :--- |
| **1** | Semana 1 | **Fundamentos:** Arquitectura, entornos, MVP de vuelo en circuito cerrado y RBAC. |
| **2** | Semana 2 | Control y programación de misiones. |
| **3** | Semana 3 | Detección de personas fuera de horario (IA Visión). |
| **4** | Semana 4 | Detección de humo (Procesamiento de imágenes). |
| **5** | Semana 5 | Generación y envío de alertas con evidencia. |
| **6** | Semana 6 | Transmisión y visualización de video en vivo. |
| **7** | Semana 7 | Grabación continua y almacenamiento seguro. |
| **8** | Semana 8 | Geofencing y zonas de exclusión. |
| **9** | Semana 9 | Retención de datos (purga 30 días) y bitácora. |
| **10** | Semana 10 | Auditoría de accesos/cambios y usabilidad. |
| **11** | Semana 11 | Conectividad/tolerancia a fallos, hardware, pruebas finales, documentación y entrega. |

---

## 🚀 Sprint 1: Cimientos de Arquitectura, Entornos y MVP

**Meta del Sprint:** 
Establecer la arquitectura base del proyecto, configurar entornos, definir el modelo de datos inicial (RBAC) y tener un prototipo de vuelo autónomo simulado en circuito cerrado (Minimum Viable Product).

**Definition of Done (DoD) - Semana 1:**
- [ ] Todo código subido en GitHub con al menos un PR revisado por otro integrante.
- [ ] Entorno de simulación del dron ejecutando misión de ida y vuelta sin intervención manual.
- [ ] Login funcional End-to-End (Frontend consumiendo Backend).
- [ ] Modelo de datos inicial (Usuario, Rol) migrado a base de datos.
- [ ] Pipeline CI/CD ejecutando build exitosamente tras cada push a `main`.
- [ ] Demo de Review presentada al Product Owner sin errores críticos.

---
*Desarrollado para la Facultad de Informática de la UAQ.*
