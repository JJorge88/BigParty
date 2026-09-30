# qr-scanner 1.4.2

Distribución oficial de `qr-scanner` publicada por Nimiq en npm:
https://registry.npmjs.org/qr-scanner/-/qr-scanner-1.4.2.tgz

Fuente y documentación: https://github.com/nimiq/qr-scanner
Licencia: MIT, conservada en `LICENSE`.

Se incluyen el módulo ES, su worker y ambos source maps oficiales para servirlos localmente.
Los source maps completan las referencias requeridas por collectstatic/WhiteNoise;
los archivos minificados se conservan idénticos a la distribución 1.4.2.
No se descargan scripts desde un CDN al operar el acceso. No editar los archivos
minificados; una actualización debe reemplazar el par módulo/worker y verificar
lectura de QR, compatibilidad de cámara y licencias.
