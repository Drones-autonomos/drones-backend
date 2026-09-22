# Entorno de Simulación SITL (Software In The Loop)

Para el desarrollo y pruebas de las misiones autónomas del dron sin requerir hardware físico, utilizamos **ArduPilot SITL** en conjunto con **MAVProxy** y `dronekit`.

## Prerrequisitos

Asegúrate de tener instalado Python en tu sistema y **siempre usar un entorno virtual activo** para evitar conflictos con los paquetes del sistema.

### En Ubuntu / Debian / MacOS
```bash
python -m venv venv
source venv/bin/activate
pip install dronekit-sitl mavproxy
```

### En Arch Linux (Específico)
En Arch Linux, `pip` está bloqueado globalmente por defecto (PEP 668). Debes hacerlo estrictamente dentro de un entorno virtual. Además, si quieres que la consola gráfica de MAVProxy funcione (mapa, gráficos), es recomendable instalar `wxpython`.

```bash
# 1. Instalar dependencias del sistema (opcional pero recomendado para MAVProxy)
sudo pacman -S python python-pip tk wxpython

# 2. Crear y activar el entorno virtual
python -m venv venv
source venv/bin/activate

# 3. Instalar los binarios de simulación en el entorno virtual
pip install dronekit-sitl mavproxy
```

## Ejecución del Entorno

Debes usar múltiples terminales para levantar el entorno y luego comunicarte con él.

### 1. Iniciar el Simulador
En una nueva terminal, inicia el simulador de un cuadricóptero (`copter`).
Esto levantará la instancia del dron virtual escuchando conexiones TCP en el puerto local `5760`.

```bash
dronekit-sitl copter
```

### 2. Rutear la Telemetría (MAVProxy)
Nuestro backend (y los scripts de prueba) esperan interactuar con el dron a través de **UDP en el puerto `14550`**, que es el estándar habitual.
En otra terminal, corre MAVProxy para establecer el puente entre el simulador y nuestro backend:

```bash
mavproxy.py --master tcp:127.0.0.1:5760 --out udp:127.0.0.1:14550
```

> **Nota:** Al ejecutar este comando, tendrás acceso a una consola interactiva donde puedes introducir comandos de ArduPilot manualmente y monitorear el estado en tiempo real.

### 3. Probar la Conexión
Una vez que ambas herramientas estén corriendo, tu entorno de simulación está listo.
Puedes lanzar los scripts de validación, por ejemplo:

```bash
python scripts/drone_backend.py
```
O directamente iniciar el servidor FastAPI e interactuar con los endpoints de navegación.
