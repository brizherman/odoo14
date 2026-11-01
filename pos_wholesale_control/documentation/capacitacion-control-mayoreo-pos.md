# Capacitación paso a paso — Control de mayoreo en POS

**Fecha:** 2026-10-30  
**Módulo:** `pos_wholesale_control` 14.0.1.1.0  
**Estado:** Borrador para revisión y aprobación  
**Alcance:** Funcionamiento actual del módulo. No incluye las reglas futuras de tres niveles.

**Avance del alumno (2026-10-30):** los pasos 1 a 7 quedaron comprendidos. El siguiente paso pendiente es el Paso 8.

## 1. Propósito del documento

Este documento sirve como guion para enseñar a configurar, usar y revisar el módulo actual de control de mayoreo en el Punto de Venta.

La capacitación debe impartirse un paso a la vez:

1. El instructor explica un solo tema.
2. El instructor hace la pregunta de comprobación.
3. El alumno responde antes de continuar.
4. Si la respuesta es incorrecta o incompleta, el instructor vuelve a explicar con un ejemplo.
5. Solo después de confirmar que el paso quedó entendido se continúa con el siguiente.

Las respuestas esperadas están al final para que el instructor pueda revisar el aprendizaje. No se recomienda mostrarlas al alumno antes de que responda.

## 2. Instrucciones obligatorias para el LLM instructor

Cuando este documento se adjunte o se mencione en un chat, el LLM debe actuar como instructor y seguir estas reglas:

### Inicio

- Si el usuario escribe **“empieza”**, **“comienza”** o una instrucción equivalente, iniciar inmediatamente en el **Paso 1**.
- No presentar un resumen completo antes de empezar.
- No pedir al usuario que vuelva a explicar qué quiere aprender.
- Si la conversación ya contiene pasos completados, continuar desde el siguiente paso pendiente.
- Si el encabezado indica que los pasos 1 a 7 quedaron comprendidos y no hay un avance posterior, continuar en el **Paso 8**.
- Si no es posible determinar el último paso completado, preguntar solamente: **“¿Desde qué paso quieres continuar?”**

### Presentación de cada paso

- Enseñar únicamente un paso por mensaje.
- Explicar el tema con lenguaje sencillo y en español.
- Mantener los nombres de menús, campos, botones y listas tal como aparecen en este documento.
- Terminar cada explicación con la pregunta de comprobación correspondiente.
- Esperar la respuesta del usuario antes de avanzar.
- No mostrar todavía el contenido del siguiente paso.

### Evaluación de la respuesta

- Evaluar el significado de la respuesta, no la ortografía.
- Aceptar respuestas breves cuando demuestren que el concepto fue comprendido.
- Si la respuesta es correcta, confirmarlo brevemente, explicar la razón en una frase y continuar con el siguiente paso.
- Si es parcialmente correcta, indicar qué parte falta y hacer una pregunta más sencilla sobre el mismo concepto.
- Si es incorrecta, corregirla con un ejemplo concreto y volver a preguntar antes de continuar.
- No revelar anticipadamente las respuestas de la sección **Respuestas esperadas para el instructor**.
- No convertir la capacitación en un examen rígido: el objetivo es que el usuario aprenda.

### Control del avance

- Mantener en la conversación el número del paso actual y cuáles ya fueron comprendidos.
- Si el usuario hace una pregunta relacionada, responderla y después regresar al mismo paso.
- Si el usuario escribe **“repite”**, explicar el paso actual de otra manera.
- Si el usuario escribe **“ejemplo”**, proporcionar un ejemplo adicional del paso actual.
- Si el usuario escribe **“siguiente”** sin responder la comprobación, recordar amablemente que primero debe contestarla, salvo que pida explícitamente omitir ese paso.
- Si el usuario escribe **“pausa”** o **“detente”**, indicar el número del paso donde quedó y no continuar.
- Si el usuario escribe **“continúa”** o **“reanuda”**, retomar el siguiente paso pendiente.

### Límites de la capacitación

- Enseñar solamente el funcionamiento actual descrito en este documento.
- No mezclar las reglas futuras de menudeo, mayoreo y distribuidor definidas en otros PRD o tareas.
- No afirmar que una función futura ya está disponible.
- No modificar archivos, configuración ni datos de Odoo durante la capacitación.
- Si el comportamiento observado por el usuario contradice este documento, detener el avance, registrar el paso y explicar que debe verificarse la configuración o la versión instalada.

### Finalización

- Después de completar el Paso 18, presentar los seis casos prácticos uno por uno.
- Esperar la respuesta del usuario en cada caso antes de mostrar el resultado.
- Al terminar, informar qué temas domina y cuáles conviene repasar.
- Preguntar si desea repetir algún paso.
- No marcar el documento como aprobado; la aprobación corresponde al responsable del negocio.

### Prompt mínimo de uso

En un chat nuevo, el usuario puede iniciar la capacitación con:

> Usa `@pos_wholesale_control/documentation/capacitacion-control-mayoreo-pos.md` como instructor y empieza.

---

## Parte A — Configuración

## Paso 1. Entrar a la sucursal correcta

La configuración es independiente para cada sucursal. Antes de cambiar cualquier valor:

1. Confirme la compañía o sucursal seleccionada en Odoo.
2. Entre a **Punto de venta → Configuración → Ajustes**.
3. Busque el bloque **Control de clientes mayoristas**.

El icono de edificio indica que los valores corresponden a la sucursal seleccionada.

El usuario que configura necesita el grupo **Administrador de mayoreo en POS**. Los administradores de Odoo ya cuentan con el acceso necesario.

### Pregunta de comprobación 1

Si configura los valores estando en la sucursal equivocada, ¿la configuración se aplica automáticamente a todas las sucursales?

---

## Paso 2. Mantener apagado el control durante la configuración

El interruptor **Activar control de mayoreo** debe permanecer apagado mientras se llenan y verifican los demás campos.

Al instalar o actualizar el módulo, el interruptor queda apagado. Mientras permanezca así, la sucursal sigue vendiendo como antes.

El control se activa solamente al final, cuando:

- Las listas están configuradas.
- Las asignaciones por tipo están completas.
- Las listas están disponibles en todas las cajas correspondientes.
- No aparece una advertencia de configuración.
- Los empleados y gerentes cuentan con los permisos necesarios.

### Pregunta de comprobación 2

¿Debe encenderse el control antes de configurar las listas y asignaciones?

---

## Paso 3. Configurar los mínimos y la zona horaria

Los valores actuales predeterminados son:

- **Mínimo del mes anterior:** MXN $800.00.
- **Mínimo del pedido actual:** MXN $1,500.00.
- **Zona horaria del negocio:** `America/Tijuana`.

El mínimo de MXN $800.00 revisa las compras netas del mes calendario inmediatamente anterior.

El mínimo de MXN $1,500.00 revisa el pedido actual calculado completamente a precio de menudeo, con descuentos e impuestos.

Los límites son inclusivos:

- MXN $799.99 no califica por el mes anterior.
- MXN $800.00 sí califica.
- MXN $1,499.99 no califica por el pedido actual.
- MXN $1,500.00 sí califica.

La zona horaria define cuándo empieza y termina cada mes para estas reglas.

### Pregunta de comprobación 3

Un cliente compró MXN $800.00 exactos durante el mes anterior. ¿Califica por historial?

---

## Paso 4. Configurar las listas principales

La sucursal necesita estas listas:

- **Lista de precios de menudeo:** Lista de precios a Público en General.
- **Lista de precios de mayoreo:** Lista de precios de Mayorista.

Ambas listas deben:

- Estar activas.
- Usar la misma moneda de la sucursal, normalmente MXN.
- Estar disponibles en cada caja de la sucursal.

El mismo nombre puede existir en más de un registro. Se debe elegir el registro que realmente está disponible en las cajas de esa sucursal.

### Pregunta de comprobación 4

¿Es suficiente seleccionar una lista por nombre aunque ese registro no esté disponible en la caja?

---

## Paso 5. Configurar las asignaciones por tipo de cliente

El módulo actual reconoce cuatro tipos:

| Tipo de cliente | Lista aplicada cuando califica |
|---|---|
| Mayorista | Lista de precios de Mayorista |
| Público General | Lista de precios de Mayorista |
| Mayorista dormido | Lista de precios de Mayorista |
| Distribuidores | Super Precios a Distribuidores |

Debe existir una sola fila activa por tipo y la lista asignada debe estar disponible en las cajas de la sucursal.

Estas asignaciones no cambian el tipo del cliente. Solamente indican qué lista utilizar en el ticket cuando el cliente califica.

En el módulo actual, Público General sí puede recibir mayoreo cuando cumple una regla. La futura restricción propuesta para mantenerlo siempre en menudeo todavía no está implementada.

### Pregunta de comprobación 5

Un cliente tipo Distribuidores califica. ¿Qué lista debe recibir en el módulo actual?

---

## Paso 6. Revisar empleados, gerente y NIP

Cada caja debe usar empleados de Punto de Venta mediante `pos_hr`.

Para autorizar excepciones, el gerente necesita:

- Estar vinculado con un empleado de Punto de Venta.
- Tener el grupo **Punto de venta / Responsable**.
- Tener un NIP de empleado configurado.

El cajero no debe conocer ni capturar un NIP ajeno sin la presencia del gerente autorizado.

### Pregunta de comprobación 6

¿Puede autorizar una excepción un gerente que no tiene NIP de empleado configurado?

---

## Paso 7. Resolver advertencias, activar y guardar

Si aparece una advertencia amarilla, normalmente significa que:

- Falta una asignación por tipo de cliente.
- Una lista no está disponible en alguna caja.
- Existe otra inconsistencia de configuración.

La advertencia debe corregirse antes de activar el control.

Cuando todo esté correcto:

1. Encienda **Activar control de mayoreo**.
2. Guarde los ajustes.
3. Abra o recargue la caja.
4. Después de una actualización del módulo, haga una recarga forzada del navegador para evitar usar archivos antiguos en caché.

### Pregunta de comprobación 7

¿Debe activarse el control si todavía aparece una advertencia amarilla?

---

## Parte B — Cómo decide la caja

## Paso 8. Primera regla: mes anterior

Al elegir un cliente, la caja consulta las compras netas del mes calendario anterior.

Si el total llega a MXN $800.00, el ticket completo califica para la lista asignada al tipo de cliente.

El historial:

- Suma todas las sucursales.
- Cuenta pedidos de POS pagados o facturados.
- Cuenta pedidos de venta confirmados.
- No cuenta borradores, cancelados ni pedidos de POS sin pagar.
- Resta devoluciones en el mes de la venta original.
- Usa la zona horaria `America/Tijuana`.

El acumulado del mes actual se muestra en el panel como MTD, pero no reemplaza al mes anterior para esta regla.

### Pregunta de comprobación 8

Un cliente compró MXN $2,000 este mes, pero solo MXN $200 el mes anterior. ¿Califica por la regla del mes anterior?

---

## Paso 9. Segunda regla: pedido actual

Si el mes anterior no alcanza MXN $800.00, la caja calcula el pedido actual a precio de menudeo.

Si ese valor llega a MXN $1,500.00, el ticket completo pasa a la lista asignada al tipo de cliente.

La referencia de menudeo incluye:

- Productos y cantidades.
- Descuentos.
- Impuestos.

Después de aplicar mayoreo, el total a pagar puede quedar por debajo de MXN $1,500.00. El ticket sigue calificando mientras su referencia independiente a menudeo continúe en MXN $1,500.00 o más.

### Pregunta de comprobación 9

El pedido vale MXN $1,550.00 a menudeo y baja a MXN $1,100.00 al aplicar mayoreo. ¿Debe volver a menudeo porque el total final quedó debajo de MXN $1,500.00?

---

## Paso 10. Regreso automático a menudeo

La caja vuelve a calcular cuando cambian:

- El cliente.
- Los productos.
- Las cantidades.
- Los descuentos.
- Los impuestos o líneas del pedido.

Si se quitan productos y el total de referencia a menudeo cae por debajo de MXN $1,500.00, la caja vuelve a menudeo siempre que el mes anterior tampoco alcance MXN $800.00.

### Pregunta de comprobación 10

El cliente no calificó por el mes anterior. Su pedido bajó de MXN $1,520.00 a MXN $1,400.00 a precio de menudeo. ¿Qué debe hacer la caja?

---

## Parte C — Operación diaria en la caja

## Paso 11. Seleccionar al cliente y leer el panel

Flujo normal:

1. Abra la sesión de Punto de Venta.
2. Seleccione al cliente.
3. Revise el panel **Control de mayoreo**.

El panel muestra:

- Cliente.
- Tipo de cliente.
- Decisión Menudeo o Mayoreo.
- Lista activa.
- Motivo de la decisión.
- Tres meses de historial.
- El mes actual marcado como MTD.

Sin cliente:

- El panel solicita identificarlo.
- No muestra los meses.
- El ticket permanece en menudeo.

### Pregunta de comprobación 11

¿Puede un ticket sin cliente identificado recibir automáticamente precio de mayoreo?

---

## Paso 12. Agregar productos sin cambiar la lista manualmente

El cajero agrega productos normalmente. La caja cambia la lista automáticamente cuando el ticket cruza un mínimo.

El cajero no debe intentar elegir una lista. El botón muestra:

**Lista de precios bloqueada**

Este comportamiento es intencional. La lista es una decisión del módulo, no del cajero.

### Pregunta de comprobación 12

¿Debe el cajero cambiar manualmente la lista cuando el pedido supera MXN $1,500.00?

---

## Paso 13. Validación antes de cobrar

Antes de aceptar el pago, el servidor vuelve a calcular:

- Historial.
- Total de referencia a menudeo.
- Decisión esperada.
- Lista esperada.
- Validez de cualquier excepción.

Si la lista no coincide, aparece:

**No se puede cobrar con la lista seleccionada**

La caja regresa a productos para corregir el ticket. Esta validación evita cobrar con una lista manipulada o desactualizada.

### Pregunta de comprobación 13

Si aparece el mensaje de lista incorrecta, ¿debe el cajero ignorarlo y continuar cobrando?

---

## Parte D — Excepción de gerente

## Paso 14. Cuándo usar una excepción

La excepción sirve para un solo ticket:

- Dar mayoreo aunque la decisión automática sea menudeo.
- Mantener menudeo aunque la decisión automática sea mayoreo.

No cambia:

- El tipo del cliente.
- Su lista permanente.
- El siguiente ticket.
- Su historial.

### Pregunta de comprobación 14

¿Una excepción convierte permanentemente al cliente en Mayorista?

---

## Paso 15. Autorizar correctamente la excepción

Para autorizar:

1. Pulse **Excepción de gerente** en el panel.
2. El gerente escribe su NIP.
3. El gerente captura un motivo obligatorio.
4. Confirme la excepción.

Un NIP incorrecto o un motivo vacío deben ser rechazados.

El panel debe seguir mostrando la decisión automática y señalar que existe una excepción.

Si se cambia el cliente, la excepción se elimina y debe autorizarse nuevamente.

### Pregunta de comprobación 15

Después de autorizar una excepción, el cajero cambia al cliente. ¿La excepción continúa activa?

---

## Parte E — Conexión, auditoría y revisión posterior

## Paso 16. Qué hacer sin conexión o sin historial

Si la caja no puede consultar el historial:

- El ticket permanece en menudeo.
- El panel muestra el error.
- La única salida a mayoreo es una excepción válida de gerente.
- La excepción queda registrada.

La caja no debe asumir que el cliente califica cuando no puede comprobarlo.

### Pregunta de comprobación 16

Si no se puede consultar el historial, ¿debe la caja aplicar mayoreo automáticamente por confianza?

---

## Paso 17. Revisar un pedido cobrado

Después del cobro, abra el pedido y revise la pestaña **Mayoreo**.

Debe mostrar:

- Decisión automática.
- Decisión final.
- Motivo.
- Monto del mes anterior.
- Total de referencia a menudeo.
- Mínimos utilizados.
- Lista aplicada.
- Indicador de excepción.

Estos datos sirven para explicar por qué se aplicó una lista.

### Pregunta de comprobación 17

¿Dónde se revisa la decisión automática y la decisión final de un pedido ya cobrado?

---

## Paso 18. Revisar excepciones

En **Punto de venta → Excepciones de mayoreo**, los usuarios autorizados pueden revisar:

- Gerente que autorizó.
- Cajero.
- Cliente.
- Motivo.
- Ticket.
- Decisiones automática y final.

Los registros son de auditoría. No deben crearse, editarse ni borrarse manualmente desde esa pantalla.

### Pregunta de comprobación 18

¿Puede un usuario editar el motivo de una excepción después de cobrar el ticket?

---

## Parte F — Casos prácticos

## Caso 1. No califica

- Mes anterior: MXN $500.00.
- Pedido actual a menudeo: MXN $900.00.

Resultado esperado: menudeo.

## Caso 2. Califica por historial

- Mes anterior: MXN $900.00.
- Pedido actual a menudeo: MXN $200.00.

Resultado esperado: lista asignada al tipo del cliente.

## Caso 3. Califica por pedido actual

- Mes anterior: MXN $200.00.
- Pedido actual a menudeo: MXN $1,500.00.

Resultado esperado: lista asignada al tipo del cliente para ese ticket.

## Caso 4. Distribuidores

- Tipo: Distribuidores.
- Mes anterior: MXN $900.00.
- Pedido actual a menudeo: MXN $200.00.

Resultado esperado: Super Precios a Distribuidores.

## Caso 5. Baja nuevamente a menudeo

- Mes anterior: MXN $200.00.
- Pedido inicial a menudeo: MXN $1,600.00.
- Después de quitar productos: MXN $1,300.00.

Resultado esperado: primero mayoreo y después menudeo.

## Caso 6. Total final inferior al mínimo

- Referencia a menudeo: MXN $1,550.00.
- Total después de mayoreo: MXN $1,100.00.

Resultado esperado: permanece en mayoreo porque la referencia a menudeo sigue calificando.

---

## Respuestas esperadas para el instructor

1. No. La configuración es por sucursal.
2. No. Debe permanecer apagado hasta terminar y validar la configuración.
3. Sí. MXN $800.00 exactos califican.
4. No. Debe ser el registro correcto y estar disponible en la caja.
5. Super Precios a Distribuidores.
6. No. Necesita un NIP de empleado configurado.
7. No. Primero debe corregirse la advertencia.
8. No. El mes actual no sustituye al mes anterior.
9. No. Permanece en mayoreo porque la referencia a menudeo sigue en MXN $1,500.00 o más.
10. Volver a menudeo.
11. No. Sin cliente permanece en menudeo.
12. No. La caja cambia la lista automáticamente.
13. No. Debe regresar y corregir el ticket.
14. No. La excepción solo afecta al ticket actual.
15. No. Cambiar el cliente elimina la excepción.
16. No. Debe permanecer en menudeo salvo una excepción válida.
17. En la pestaña **Mayoreo** del pedido cobrado.
18. No. El registro de auditoría no se puede editar.

---

## Lista de aprobación del documento

Antes de aprobar esta capacitación, confirmar:

- [ ] Los nombres de menús coinciden con la instalación.
- [ ] Los nombres visibles de las tres listas coinciden con la sucursal.
- [ ] Los límites de MXN $800.00 y MXN $1,500.00 siguen vigentes.
- [ ] La zona horaria continúa siendo `America/Tijuana`.
- [ ] Público General puede calificar para mayoreo en la versión actual.
- [ ] Distribuidores usa Super Precios a Distribuidores cuando califica.
- [ ] La explicación de excepciones coincide con la política del negocio.
- [ ] Los casos prácticos son suficientes para capacitar a cajeros y gerentes.
- [ ] El documento puede cambiar de **Borrador** a **Aprobado**.

