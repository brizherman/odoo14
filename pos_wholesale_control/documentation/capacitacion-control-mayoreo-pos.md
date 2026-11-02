# Capacitación — Control de mayoreo en POS

**Fecha:** 2026-11-01  
**Módulo:** `pos_wholesale_control` 14.0.1.3.1

Cinco pasos. El detalle está en `manual-control-mayoreo-pos.md`. La prueba en la caja está en `practica-real-control-mayoreo-pos.md`.

Si este archivo se usa como instructor en un chat: un paso por mensaje, en español, con la pregunta al final. Espere la respuesta. No muestre las respuestas de abajo antes de tiempo. **Empieza** abre el paso 1. **Repite** y **ejemplo** se quedan en el mismo paso. **Pausa** se detiene. **Continúa** sigue en el paso pendiente.

## Paso 1. Quién elige la lista

La caja elige la lista. El botón dice **Lista de precios bloqueada**. No cambia el tipo de cliente.

¿Puede el cajero poner mayoreo a mano?

## Paso 2. Mayoreo normal

Aplica a Mayorista, Público General y Mayorista dormido. Califica si el mes anterior llega a MXN $800, o si el acumulado del mes en curso (MTD) más este pedido, a precio de menudeo, llega a MXN $1,500. La lista es la de Mayorista. MXN $800.00 y MXN $1,500.00 exactos sí cuentan. Quitar productos puede regresar el ticket a menudeo. El total cobrado puede bajar de MXN $1,500 y seguir en mayoreo.

Mes anterior MXN $200. Este pedido a menudeo MXN $1,500. ¿Califica?

## Paso 3. Distribuidor

El cliente Distribuidores permanece en menudeo hasta que el mes anterior llegue a MXN $10,000, o MTD más este pedido a precio de menudeo llegue a MXN $10,000. Entonces usa Super Precios y la etiqueta dice **Distribuidor**. No usa las reglas de MXN $800 ni MXN $1,500 y nunca pasa por la lista de Mayorista.

Mes anterior MXN $2,000, MTD MXN $5,000 y este pedido MXN $5,000. ¿Recibe Super Precios?

## Paso 4. Excepción de gerente

Vale un solo ticket. Pide NIP y motivo. No cambia el tipo de cliente ni el siguiente ticket. En mayoreo normal, cambiar el cliente borra la excepción. En Distribuidores, el cliente queda bloqueado y hay que abrir un ticket nuevo. Sin historial, el ticket se queda en menudeo y la única salida es la excepción.

¿La excepción deja al cliente como mayorista para siempre?

## Paso 5. Dónde se revisa

Pedido cobrado, pestaña **Mayoreo**. Menú **Punto de venta → Excepciones de mayoreo**. Ese registro no se edita.

¿Se puede corregir el motivo después de cobrar?

## Respuestas

1. No.
2. Sí, por este pedido. Usa la lista de Mayorista.
3. Sí. MTD más el pedido llega a MXN $10,000.
4. No. Solo este ticket.
5. No.

## Montos que la práctica en caja no muestra

La práctica ya incluye a Zulema Gutiérrez, que en octubre pasó de MXN $10,000.00 y recibe Super Precios. Estos dos casos siguen sin cliente real en esa práctica:

- Distribuidor con mes anterior de MXN $10,000.00 exactos: también recibe Super Precios.
- Distribuidor debajo de MXN $10,000 y con excepción autorizada: la decisión automática sigue en menudeo, la etiqueta dice **Distribuidor — excepción de gerente** y el cliente queda bloqueado.
