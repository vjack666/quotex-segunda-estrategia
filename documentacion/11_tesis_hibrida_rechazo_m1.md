# 11 - Tesis Hibrida de Rechazo M1 (Internet vs Sistema Actual)

## Tesis central

La operativa de rechazo en segundo 30 de una vela M1 es util como micro-timing,
pero no debe usarse aislada. La mejor version para este proyecto es un modelo
hibrido:

1. Contexto estructural (zonas, tendencia, sobreextension, score).
2. Confirmacion de rechazo (mechas + cuerpo + patron de reversa).
3. Timing de ejecucion (ventana de segundos dentro de la vela M1).

En otras palabras: el video aporta precision de entrada; el bot aporta filtro
de calidad y control de riesgo.

## Comparacion rapida

### Enfoque comun en internet

- Entrada en segundo 30 para aprovechar retroceso intravela.
- Importancia alta de la mecha en soporte/resistencia.
- Operativa visual y discrecional (cambiar activo cuando no hay setup claro).

### Enfoque del sistema actual

- Confirmacion cuantitativa con score + filtros estructurales.
- Validacion de rechazo por forma de vela (body y mechas minimas).
- Rechazo parcial o total configurable.
- Ventana temporal configurable para ejecutar rechazo M1.

## Respuestas operativas clave

### Papel de las mechas

Las mechas son evidencia de rechazo de precio. En este sistema son condicion
necesaria en rebotes, pero no suficiente: deben coexistir con direccion,
patron de reversa y contexto de zona.

### Tamano de mecha

- Mecha grande: mayor probabilidad de defensa de nivel.
- Mecha pequena: rechazo debil, mas riesgo de continuacion.

Se usan umbrales minimos distintos para CALL y PUT.

### Rechazo parcial vs total

- Parcial: hay rechazo, pero el cuerpo no muestra giro fuerte.
- Total: el cuerpo muestra giro mas contundente.

En el sistema:

- total: recibe mejor lectura de calidad.
- parcial: puede permitirse o bloquearse por configuracion.

### Por que cambiar de activo

Si no hay zona clara + mecha valida + patron + timing, es mas eficiente rotar
de activo que forzar entrada. El sistema lo replica al descartar candidatos
sin confirmacion y continuar escaneo global.

### Por que M1

M1 permite capturar rechazo rapido intravela. Se mantiene compatible con
expiracion de 300s al tratar M1 como trigger de entrada y 5m como contexto.

### Que buscar antes de operar

1. Zona de reaccion valida (piso/techo o nivel estructural equivalente).
2. Contexto favorable (sin sobreextension extrema en contra).
3. Vela de rechazo valida (direccion + cuerpo + mecha).
4. Patron de reversa que confirme.
5. Ventana temporal de ejecucion habilitada.

### Cuando evitar operar

- Fuera de ventana temporal configurada.
- Sin zona clara o con estructura contradictoria.
- Mecha/cuerpo por debajo de umbral.
- Patron no confirmante o contradictorio.
- Score insuficiente o bloqueos de riesgo activos.

### Volatilidad y zonas laterales

- Volatilidad alta: sube ruido y falsos rompimientos, exigir mas confirmacion.
- Lateralidad: operar extremos del rango, evitar centro del rango.

### Rol de Fibonacci y rompimiento

Fibonacci funciona como capa secundaria de confluencia de nivel. Un rompimiento
solo es util si confirma estructura y no viola filtros de persecucion.

## Regla practica recomendada

No ejecutar rechazos por una sola senal visual.
Ejecutar solo cuando coincidan:

- zona valida,
- rechazo de vela,
- patron confirmante,
- ventana temporal,
- y score/filtros del sistema.
