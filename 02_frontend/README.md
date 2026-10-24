# Paso 7 · Dashboard Web AIoT de la Cava Inteligente

Aplicación estática para monitorear la zona de crianza y enviar órdenes manuales
al ESP32. HTML semántico, CSS responsive y JavaScript ES Modules, sin frameworks,
servidor de aplicación ni proceso de compilación. No implementa FastAPI ni Gemini.

## Abrir en Ubuntu

Desde la raíz de `unidad4-aiot-cava`:

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory 02_frontend
```

Abrir **http://127.0.0.1:8000/** en Firefox o Chrome. También se puede usar
http://localhost:8000/. Detener el servidor con **Ctrl+C**. Si el puerto está
ocupado, usar otro, por ejemplo `8001`, tanto en el comando como en la URL.
No abrir `index.html` con `file://`: los módulos requieren HTTP. Se necesita
Internet para descargar el SDK de Firebase y conectarse a la base.

El servidor se limita a la interfaz de loopback. No publica la aplicación en
Internet ni sirve archivos del firmware. No hace falta ejecutar `npm install`.
Las dependencias del navegador se obtienen del CDN oficial `www.gstatic.com`.

## Organización

| Archivo | Responsabilidad |
| --- | --- |
| `index.html` | Estructura accesible, navegación, métricas, controles, confirmación y supervisor. |
| `styles.css` | Verde oscuro/oliva, tarjetas, estados con texto además de color, vistas de móvil y escritorio. Respeta `prefers-reduced-motion`. |
| `app.js` | Inicio, eventos de botones/red y carga controlada de Firebase. |
| `firebase-config.js` | Inicialización existente de Firebase, sin cambios. Exporta `db`. |
| `firebase-client.js` | Adaptador del SDK modular: `onValue()` y escritura `update()`. |
| `dashboard-controller.js` | Suscripciones, escritura en curso, estado de conexión y temporizadores locales. |
| `dashboard-state.js` | Umbrales, validación estricta de tipos, timestamps y comparación de ACK. |
| `dashboard-view.js` | Presentación de datos/errores mediante `textContent`, sin interpretar HTML de Firebase. |
| `tests/dashboard.test.js` | Pruebas aisladas con dobles de Firebase/DOM; no contactan la base ni el ESP32. |
| `package.json` | Declara ES Modules y el comando opcional de pruebas; no agrega dependencias. |

## Conexión y lectura

Se reutiliza la instancia `db` de `firebase-config.js` y el SDK modular
**12.19.0** ya configurado. No se llama otra vez a `initializeApp()` ni se agregan
credenciales. La base es:

```text
https://unidad4-aiot-cava-default-rtdb.firebaseio.com
```

Se crea una suscripción `onValue()` por cada ruta concreta bajo
`bodega/zona_crianza/`:

- `ambiente/temperatura`, `ambiente/humedad`, `ambiente/timestamp`.
- `control/extractor_solicitado`, `control/origen`.
- `extractor_confirmado`.
- `supervisor/alerta_calidad`, `supervisor/forzar_climatizacion`,
  `supervisor/impacto_enologico`, `supervisor/ultima_evaluacion`.

Además, `.info/connected` indica la conexión **del navegador con Firebase**;
no acredita que el ESP32 esté conectado. `.info/serverTimeOffset` ajusta el
cálculo de antigüedad con el reloj del servidor. Las suscripciones se cancelan
al abandonar la página, conservándolas si el navegador usa su caché de navegación.
Firebase administra su transporte y reconexión. La aplicación no implementa
polling, `setInterval()` ni consultas HTTP periódicas.

Los campos inexistentes o de tipo inválido no se convierten a cero ni a `false`.
Se muestran `—`, `Sin datos` o `Estado desconocido`. Los errores de lectura
aparecen en su panel sin impedir el funcionamiento de los demás módulos.
Si el SDK no carga, aparece un error global y los controles siguen deshabilitados.
No hay modo demo ni datos de ejemplo usados como sustituto en la aplicación.

Documentación oficial:
[lecturas y escrituras](https://firebase.google.com/docs/database/web/read-and-write),
[conectividad y eventos locales](https://firebase.google.com/docs/database/web/offline-capabilities).

## Umbrales ambientales

| Variable | Ideal | Fuera del ideal, sin cruzar el umbral crítico | Crítica |
| --- | --- | --- | --- |
| Temperatura | 12–18 °C, inclusive | Menor de 12 °C; mayor de 18 hasta 22 °C | Estrictamente mayor de 22 °C |
| Humedad | 65–80 %, inclusive | 60 a menos de 65 %; mayor de 80 % | Estrictamente menor de 60 % |

Temperatura debe ser un número finito. Humedad debe ser un número finito entre
0 y 100. Strings numéricos en estas métricas no se aceptan silenciosamente.
Las escalas son indicadores del valor actual, no gráficos históricos; el marcador
de temperatura se limita visualmente a 0–35 °C sin alterar el número mostrado.
Los umbrales solo clasifican lecturas: **ninguno enciende automáticamente el
climatizador desde el dashboard**.

## Fechas y datos antiguos

La inspección de solo lectura de `ambiente/timestamp` durante la implementación
devolvió el número `1792851315451`, un epoch en **milisegundos**. Esto coincide con
el timestamp de servidor que escribe el firmware. También se contemplan epoch
en segundos, strings numéricos e ISO con zona horaria explícita. Los valores 0,
ausentes, inválidos, el objeto `.sv` sin resolver y `Sin evaluacion` no se presentan
como fechas de 1970. Se admiten fechas entre 2000 y 2100 para este proyecto.
La fecha visible usa el huso horario del navegador.

A los **20 segundos** sin un timestamp ambiental reciente aparece `Datos antiguos`.
Una fecha más de un minuto en el futuro genera otra advertencia. La detección usa
un `setTimeout()` local programado para el vencimiento y se recalcula al volver
a la pestaña; no solicita nuevos datos a Firebase. Una pérdida de conexión conserva
las últimas lecturas visibles con un aviso de que son el último registro recibido.
El timestamp del ambiente es común a las lecturas, no una marca individual de ACK.

## Control solicitado y estado confirmado

Los botones realizan una única escritura atómica:

```js
update(ref(db, "bodega/zona_crianza/control"), {
  extractor_solicitado: true, // ENCENDER; false para APAGAR
  origen: "manual",
});
```

`update()` conserva otros hijos de `control`. No se usa `set()` sobre nodos
padres. El frontend **jamás escribe** `extractor_confirmado`, ambiente o supervisor.

Hay tres situaciones separadas:

1. **Solicitud en tránsito:** el botón inició `update()`. Los dos botones se
   deshabilitan hasta que su promesa termina. Un evento optimista local de
   `onValue()` no se presenta como aceptación del servidor ni como un ACK nuevo.
2. **Firebase aceptó la solicitud:** la promesa se resolvió. Se habilitan los
   botones aunque el ACK siga pendiente. La aceptación no acredita ejecución
   física. Si la escritura falla se informa el error y se libera el control.
3. **Estado confirmado:** proviene exclusivamente del booleano publicado por el
   ESP32. Se muestra `Climatizador encendido`, `Climatizador apagado` o
   `Estado desconocido`, según el dato recibido.

Cuando solicitado y confirmado difieren, aparece exactamente **Orden pendiente
de confirmación del ESP32**. Después de **15 segundos** de divergencia observada
en esta sesión aparece una advertencia adicional. No se afirma una falla física
y se permite enviar una nueva orden una vez terminada la escritura anterior.
Al recargar la página, ese tiempo de observación vuelve a empezar.

Si los booleanos coinciden, se informa esa coincidencia. La estructura actual no
incluye ID de orden ni timestamp de ACK: no se puede probar que un valor igual
corresponda a una nueva ejecución, medir presencia de la placa ni verificar
eléctricamente el GPIO. Un ACK refleja el estado aplicado informado por el firmware.

Si la conexión se pierde durante una escritura, Firebase puede dejarla en tránsito
y enviarla al reconectar. A los **10 segundos** se advierte esa situación; no se
finge que la petición fue cancelada ni se libera para duplicar solicitudes aún
sin resolver. Esto es distinto de esperar el ACK, que no bloquea los botones.

## Supervisor AIoT

El panel muestra únicamente los cuatro valores existentes de Firebase. Con
`ultima_evaluacion` ausente o sin una fecha válida, informa **Supervisor IA pendiente
de integración**. Si hay fecha válida, indica que existe una evaluación registrada
en Firebase; eso no demuestra que Gemini esté integrado ni activo.

Los valores iniciales `false`, `Condiciones normales` y `Sin evaluacion` son
registros preexistentes, no resultados de una ejecución de IA. No se llama a
ninguna API de IA, no se generan textos de Gemini y no se escribe una orden al
recibir `forzar_climatizacion`: ese campo es solo informativo en este Paso 7.

## Probar con Firebase y el ESP32 físico

1. Iniciar el servidor, abrir la URL y esperar `Firebase conectado`. Ese indicador
   solo confirma la conexión del navegador. Si hay un error de permisos, revisar
   el mensaje del panel y las reglas actuales sin abrir permisos globales.
2. En Firebase Console, comparar `ambiente/temperatura`, `humedad` y `timestamp`
   con las tarjetas y la última actualización. No debe ser necesario recargar.
3. Con el firmware existente cargado, enviar `1`, `2` y `3` por el monitor serie
   para cambiar el escenario. Tras el próximo PATCH (turno de 5 s), comprobar:
   `1` → 16,0 °C/70 %; `2` → 24,0 °C crítica/70 %; `3` → 17,0 °C/55 % crítica.
   Esta verificación no requiere modificar el firmware.
4. Pulsar **ENCENDER**. Verificar en Firebase
   `control/extractor_solicitado=true` y `control/origen="manual"`. En la placa,
   comprobar recepción SSE, LED azul GPIO 2 y el PUT ACK. La tarjeta confirmada
   debe pasar a encendido solo al leer `extractor_confirmado=true`.
5. Pulsar **APAGAR** y repetir con ambos booleanos en `false` y el LED apagado.
   Durante una escritura no deben enviarse solicitudes por clics repetidos.
6. Para observar una divergencia persistente, apagar la placa, enviar una orden
   distinta del último confirmado y esperar 15 s. Firebase puede aceptar la orden
   sin que llegue un ACK. Debe verse pendiente y luego la advertencia, con los
   botones disponibles. Al recuperar la placa, verificar la convergencia por SSE/ACK.
7. Usar el escenario `9` o detener la placa: el timestamp ambiental deja de
   avanzar y debe aparecer `Datos antiguos` después de 20 s. No se atribuye
   automáticamente una falla física; puede faltar red o una lectura válida.
8. Cortar la red del navegador: conservar las últimas lecturas con aviso y
   deshabilitar los controles. Restaurarla y comprobar reconexión sin recargar.
9. Revisar el supervisor: sus campos deben coincidir con Firebase y no aparecer
   evaluaciones inventadas. La ausencia de datos o permisos debe afectar solo su panel.
10. Reducir la ventana a 320, 375 y 768 px, y ampliarla a escritorio. Comprobar
    navegación, tarjetas y botones, sin desplazamiento horizontal. Recorrer los
    controles con Tab, comprobar foco visible y mensajes legibles. La validación
    visual en un navegador real queda pendiente en esta sesión.

## Pruebas automatizadas y verificación realizada

Con Node.js 20 o superior, desde la raíz del repositorio:

```bash
node --experimental-vm-modules 02_frontend/tests/dashboard.test.js
```

También se puede ejecutar `npm test` dentro de `02_frontend/`, sin instalar
dependencias. El flag experimental se usa únicamente para enlazar el adaptador
Firebase con módulos simulados en las pruebas; no se usa en el navegador.

Pasaron **14 pruebas**: límites ambientales, valores ausentes/incorrectos,
timestamps, envejecimiento sin tráfico de red, offset de reloj, divergencia ACK,
promesas/clics duplicados, errores aislados, escritura atómica limitada a control,
suscripción `onValue()`, rechazo de escrituras fuera de localhost, representación
del estado confirmado, supervisor pendiente y tratamiento de textos como texto.

Se verificó que el servidor local responde HTTP 200 para HTML, CSS y módulos,
con tipos de contenido apropiados, y que los IDs/referencias locales del HTML
son válidos. Se comprobó por consultas de solo lectura la disponibilidad del
SDK 12.19.0 y el formato real del timestamp de Firebase. No se escribieron órdenes
reales durante estas pruebas ni se alteraron reglas, credenciales o firmware.

**Límites:** no había un navegador conectado a las herramientas de esta sesión.
Las pruebas de DOM usan un doble y no acreditan layout, responsive, foco ni
ejecución real del SDK en el navegador. Los eventos de Firebase en vivo, ambos
botones contra la base y el lazo SSE → GPIO → PUT necesitan la verificación
del usuario en su navegador y ESP32 físico.

## Seguridad antes de publicar

La configuración web existente identifica el proyecto Firebase y es pública por
diseño; no contiene una clave de administrador. No se agregaron contraseñas,
tokens privados, cuentas de servicio, APIs de IA ni acceso al `secrets.h` del ESP32.

El control manual de esta implementación se limita a los hosts exactos
`localhost`, `127.0.0.1` y el loopback IPv6. Fuera de ellos, interfaz y adaptador
rechazan las escrituras. Es una prevención de publicación accidental, **no una
barrera de seguridad para la base**: cualquiera con acceso permitido por las
reglas puede usar el SDK o REST directamente, sin este dashboard.

Antes de exponer controles públicamente se requiere Firebase Authentication y
reglas que autoricen por usuario/rol las lecturas y escrituras necesarias,
validen tipos y protejan el ACK para el dispositivo. Eso requiere diseñar la
autenticación del ESP32 existente; no cambiar reglas a ciegas y romper el firmware.
La implementación de autenticación y el despliegue quedan fuera del Paso 7 actual.
No publicar esta versión con reglas de escritura anónimas abiertas.

No se modificaron los Pasos 1 a 6, no se hizo commit ni push y no se desplegó el dashboard.
