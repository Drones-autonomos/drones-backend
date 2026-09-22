# Entorno de Simulación SITL (Software In The Loop)

Para el desarrollo y pruebas de las misiones autónomas del dron sin requerir hardware físico, utilizamos **ArduPilot SITL** en conjunto con **MAVProxy** y `dronekit`.

## Prerrequisitos

Asegúrate de tener instalado Python en tu sistema y **siempre usar un entorno virtual activo** para evitar conflictos con los paquetes del sistema.

### En Ubuntu / Debian / MacOS
```bash
python -m venv venv
source venv/bin/activate
pip install future dronekit-sitl mavproxy
```

### En Arch Linux (Específico)
En Arch Linux, `pip` está bloqueado globalmente por defecto (PEP 668). Debes hacerlo estrictamente dentro de un entorno virtual. Además, si quieres que la consola gráfica de MAVProxy funcione (mapa, gráficos), es recomendable instalar `python-wxpython` y `python-matplotlib` desde los repositorios del sistema.

```bash
# 1. Instalar dependencias del sistema (opcional pero recomendado para MAVProxy)
sudo pacman -S python python-pip tk python-wxpython python-matplotlib opencv

# 2. Crear entorno virtual heredando paquetes del sistema (para poder usar matplotlib/opencv)
python -m venv --system-site-packages venv
source venv/bin/activate

# 3. Instalar los binarios de simulación en el entorno virtual
pip install future dronekit-sitl mavproxy
```

## Ejecución del Entorno

Debes usar múltiples terminales para levantar el entorno y luego comunicarte con él.

### 1. Iniciar el Simulador (Facultad de Informática UAQ)
Hemos preconfigurado un script para que el dron virtual inicie directamente en el Campus Juriquilla de la UAQ y formatee cualquier dato previo (`eeprom`) para evitar problemas de caché con locaciones anteriores.

En una nueva terminal:
```bash
# Ejecutar el script que inicializa SITL en las coordenadas de la UAQ
./run_sitl.sh
```
*(Este script activa el entorno virtual y lanza `dronekit-sitl copter --home=... --wipe`)*

### 2. Rutear la Telemetría (MAVProxy)
Nuestro backend (y los scripts de prueba) esperan interactuar con el dron a través de **UDP en el puerto `14550`**, que es el estándar habitual.
En otra terminal, activa nuevamente tu entorno virtual y corre MAVProxy para establecer el puente. Además, puedes cargar el módulo del mapa interactivo:

```bash
source venv/bin/activate
```

```bash
mavproxy.py --master tcp:127.0.0.1:5760 --out udp:127.0.0.1:14550 --map
```

> **Nota:** Al ejecutar este comando, tendrás acceso a una consola interactiva y un mapa 2D donde puedes visualizar al dron en tiempo real moviéndose por el campus Juriquilla.

### 3. Probar la Conexión
Una vez que ambas herramientas estén corriendo, tu entorno de simulación está listo.
Puedes lanzar los scripts de validación que ejecutarán secuencias de vuelo autónomas con waypoints:

```bash
source venv/bin/activate
python scripts/drone_backend.py
```
*(Nota técnica: ArduCopter 3.3 simulado por SITL tiene incompatibilidades al aceptar `MAV_CMD_DO_SET_MODE` desde DroneKit, por lo que internamente los scripts utilizan `set_mode_send` en raw MAVLink).*
